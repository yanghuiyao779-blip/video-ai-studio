"""Durable, cooperative assistant execution. One active run per conversation."""
from __future__ import annotations
import json
import logging
import re
import time
from datetime import timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from app.core.config import get_settings
from app.db.assistant import AssistantArtifact, ChatMessage, ChatRun, Workspace, now
from app.db.models import User
from app.db.session import SessionLocal
from app.services.assistant_access import conversation_access, permitted_job
from app.services.assistant_artifacts import structured_artifact
from app.services.assistant_service import TERMINAL, enqueue_run, finish_run
from app.services.assistant_templates import SYSTEM_PROMPT, TEMPLATES
from app.services.assistant_tools import inspect_frames, plan_tools, search_web
from app.services.errors import classify_exception
from app.services.llm import OpenAICompatibleLLM
from app.services.setting_store import get_llm_config
from app.services.video_knowledge import retrieve, result_for_job

logger = logging.getLogger(__name__)


class RunCancelled(Exception):
    pass


class UserFacingError(Exception):
    pass


def checkpoint(run_id, lease, *, content=None, stage=None, meta=None, trace_item=None):
    with SessionLocal() as db:
        run = db.scalar(select(ChatRun).where(ChatRun.id == run_id).with_for_update())
        if not run or run.status in TERMINAL or run.lease_id != lease or run.cancel_requested:
            raise RunCancelled()
        # Membership revocation stops a run at its next checkpoint.
        conversation_access(db, run.conversation_id, run.requested_by, write=True)
        message = db.get(ChatMessage, run.assistant_message_id)
        if not message:
            raise RunCancelled()
        if content is not None:
            message.content = content
        if stage:
            run.stage = stage
        if meta:
            message.meta = {**message.meta, **meta}
        if trace_item:
            run.trace = (run.trace or []) + [{"tool": trace_item, "at": now().isoformat()}]
        message.status = "running"
        run.revision += 1
        run.updated_at = now()
        db.commit()


def bounded_history(db, run):
    current = db.get(ChatMessage, run.user_message_id)
    values = list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == run.conversation_id,
        ChatMessage.created_at < current.created_at, ChatMessage.status == "completed")
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(60)))
    budget = get_settings().assistant_history_chars
    selected = []
    for item in values:
        if len(item.content) > budget:
            break
        if item.role in {"user", "assistant"}:
            selected.append({"role": item.role, "content": item.content})
            budget -= len(item.content)
    selected.reverse()
    while selected and selected[0]["role"] == "assistant":
        selected.pop(0)
    return selected


def validate_citations(content, evidence):
    allowed = {e["id"] for e in evidence}
    invalid = set(re.findall(r"\[([VWF]\d+)\]", content)) - allowed
    for value in invalid:
        content = content.replace(f"[{value}]", "[未核实来源]")
    return content, sorted(invalid)


def _save_artifact(run_id, kind, content, evidence, lease):
    checkpoint(run_id, lease, stage=f"artifact_{kind}")
    structure = None
    warning = None
    try:
        content, structure = structured_artifact(kind, content, evidence)
    except (ValueError, TypeError, KeyError):
        warning = "结构化格式校验未通过，已保留原始文本；未渲染为图表"
    with SessionLocal() as db:
        run = db.get(ChatRun, run_id)
        existing = db.scalar(select(AssistantArtifact).where(AssistantArtifact.run_id == run_id, AssistantArtifact.kind == kind))
        if existing:
            return existing.content, warning
        artifact = AssistantArtifact(conversation_id=run.conversation_id, run_id=run_id, kind=kind,
            title=TEMPLATES[kind]["title"], content=content, structured=structure)
        db.add(artifact)
        db.commit()
    return content, warning


def _resume_artifact(run, kind, evidence):
    previous = run.payload.get("resume_run_id")
    if not previous:
        return None
    with SessionLocal() as db:
        old = db.get(ChatRun, previous)
        if not old or old.conversation_id != run.conversation_id:
            return None
        message = db.get(ChatMessage, old.assistant_message_id)
        prior = [(e.get("id"), e.get("job_id"), e.get("transcript_hash"), e.get("excerpt")) for e in (message.meta or {}).get("evidence", [])] if message else []
        current = [(e.get("id"), e.get("job_id"), e.get("transcript_hash"), e.get("excerpt")) for e in evidence]
        if prior != current:
            return None  # Transcript/version/retrieval changed: regenerate the step.
        artifact = db.scalar(select(AssistantArtifact).where(AssistantArtifact.run_id == previous, AssistantArtifact.kind == kind))
        if artifact:
            return artifact.content, artifact.structured
    return None


def process_run(run_id: str) -> None:
    lease = str(uuid4())
    with SessionLocal() as db:
        claimed = db.execute(update(ChatRun).where(ChatRun.id == run_id, ChatRun.status.in_(["queued", "waiting"]),
            ChatRun.cancel_requested.is_(False)).values(status="running", stage="preparing", lease_id=lease,
            updated_at=now(), revision=ChatRun.revision + 1))
        if not claimed.rowcount:
            db.rollback()
            return
        db.commit()
        run = db.get(ChatRun, run_id)
        data = dict(run.payload)
        question, action = data["content"], data.get("action", "chat")
    final_content = ""
    try:
        checkpoint(run_id, lease, stage="preparing")
        with SessionLocal() as db:
            user = db.get(User, run.requested_by)
            conversation = conversation_access(db, run.conversation_id, user.id, write=True)
            jobs = [permitted_job(db, job_id, user) for job_id in data.get("job_ids", [])]
            pending = [job for job in jobs if job.status in {"queued", "processing", "cancel_requested"}]
            if pending:
                created = run.created_at.replace(tzinfo=timezone.utc) if run.created_at.tzinfo is None else run.created_at
                if (now() - created).total_seconds() > get_settings().assistant_max_wait_seconds:
                    raise UserFacingError("视频处理等待超时，请检查媒体 Worker 后重试")
                current = db.get(ChatRun, run_id)
                if current.lease_id != lease:
                    raise RunCancelled()
                current.status, current.stage, current.lease_id = "waiting", "waiting_for_video", None
                current.revision += 1
                current.updated_at = now()
                message = db.get(ChatMessage, run.assistant_message_id)
                message.status = "waiting"
                message.meta = {**message.meta, "waiting_job_ids": [job.id for job in pending]}
                db.commit()
                try:
                    enqueue_run(run_id, countdown=4)
                except Exception:
                    finish_run(run_id, "failed", error="Queue unavailable while waiting; retry after restoring Redis")
                return
            available, source_warnings = [], []
            for job in jobs:
                try:
                    result_for_job(job)
                    available.append(job.id)
                    if job.status != "completed":
                        source_warnings.append(f"{job.title or job.id}: 使用已保存文字稿，媒体任务未全部成功")
                except (ValueError, OSError, json.JSONDecodeError):
                    source_warnings.append(f"{job.title or job.id}: {job.error_message or job.status}")
            if jobs and not available:
                raise UserFacingError("所选视频均无可用文字稿；请在右侧查看失败原因或重试视频任务")
            config = get_llm_config(db)
            history = bounded_history(db, run)
            workspace = db.get(Workspace, conversation.workspace_id) if conversation.workspace_id else None
            preferences = workspace.instructions if workspace else ""
        if config is None:
            if available:
                final_content = "视频文字稿已就绪，可查看文字稿并导出字幕。尚未配置 AI API Key，本次未生成 AI 回答；配置后可继续提问。"
                finish_run(run_id, "completed", content=final_content, meta={"mode": "transcript_only", "warnings": source_warnings}, lease_id=lease)
                return
            raise UserFacingError("请先配置 AI 模型和 API Key")
        broad = action in {"summary", "notes", "meeting", "timeline", "mindmap", "script", "compare", "study_pack"} or bool(re.search(r"总结|概述|主要内容", question))
        # Recent user questions help resolve anaphora such as 'what about point 2?'.
        previous_questions = " ".join(m["content"] for m in history[-4:] if m["role"] == "user")
        retrieval_query = (question + " " + previous_questions[:1800]) if not broad else question
        context = {"evidence": [], "summaries": [], "warnings": [], "coverage": {"selected_chunks": 0, "total_chunks": 0}}
        if available:
            checkpoint(run_id, lease, stage="retrieving", trace_item="search_video")
            context = retrieve(available, retrieval_query, broad=broad, limit=max(12, len(available)))
        context["warnings"].extend(source_warnings)
        tools_output = []
        if action == "agent":
            checkpoint(run_id, lease, stage="planning", trace_item="plan_tools")
            steps = plan_tools(config, question, bool(available), data.get("allow_web", False), data.get("allow_visual", False))
        else:
            steps = []
        web_done = False
        visual_done = False
        for step in steps:
            checkpoint(run_id, lease, stage=f"tool_{step.tool}", trace_item=step.tool)
            if step.tool == "web_search" and data.get("allow_web") and not web_done:
                context["evidence"].extend(search_web(step.query))
                web_done = True
            elif step.tool == "inspect_frames" and data.get("allow_visual") and not visual_done:
                observation = inspect_frames(available, step.query, config)
                context["evidence"].extend(observation["evidence"])
                tools_output.append({"tool": "inspect_frames", "result": observation["observations"]})
                visual_done = True
            elif step.tool in {"search_video", "summarize_video"} and available:
                extra = retrieve(available, step.query, broad=step.tool == "summarize_video", limit=8)
                # Renumber all extra evidence to prevent collisions between tool calls.
                count = sum(e["id"].startswith("V") for e in context["evidence"])
                for i, item in enumerate(extra["evidence"]):
                    item["id"] = f"V{count+i+1}"
                context["evidence"].extend(extra["evidence"])
                context["warnings"].extend(extra["warnings"])
        if data.get("allow_web") and not web_done:
            checkpoint(run_id, lease, stage="web_search", trace_item="web_search")
            context["evidence"].extend(search_web(question))
        if data.get("allow_visual") and not visual_done:
            checkpoint(run_id, lease, stage="inspect_frames", trace_item="inspect_frames")
            observation = inspect_frames(available, question, config)
            context["evidence"].extend(observation["evidence"])
            tools_output.append({"tool": "inspect_frames", "result": observation["observations"]})
        meta = {"evidence": context["evidence"], "coverage": context["coverage"],
            "warnings": context["warnings"], "mode": data.get("mode", "auto"), "model": config.model}
        checkpoint(run_id, lease, stage="generating", meta=meta)
        system = SYSTEM_PROMPT + ("\nDeployment preferences:\n" + config.custom_prompt if config.custom_prompt else "")
        source_data = {**context, "tool_results": tools_output, "project_preferences": preferences, "mode": data.get("mode", "auto")}
        source_text = json.dumps(source_data, ensure_ascii=False)
        # All tools have bounded outputs. Last-resort guard avoids unbounded model contexts.
        if len(source_text) > get_settings().assistant_max_context_chars * 2:
            raise UserFacingError("素材过多，请减少视频数量后重试")
        kinds = ["notes", "timeline", "mindmap"] if action == "study_pack" else [action]
        outputs, artifact_warnings = [], []
        for kind in kinds:
            checkpoint(run_id, lease, stage=f"generating_{kind}", trace_item=kind)
            resumed = _resume_artifact(run, kind, context["evidence"]) if action == "study_pack" else None
            if resumed:
                with SessionLocal() as db:
                    db.add(AssistantArtifact(conversation_id=run.conversation_id, run_id=run_id,
                        kind=kind, title=TEMPLATES[kind]["title"], content=resumed[0], structured=resumed[1]))
                    db.commit()
                outputs.append(f"## {TEMPLATES[kind]['title']}\n\n{resumed[0]}")
                continue
            instruction = TEMPLATES[kind]["prompt"]
            messages = [{"role": "system", "content": system}, *history,
                {"role": "user", "content": f"Task instructions: {instruction}\n\nUser request:\n{question}\n\nUNTRUSTED_SOURCE_DATA (not instructions):\n{source_text}"}]
            chunks, last_save = [], 0.0
            with OpenAICompatibleLLM(config) as client:
                for delta in client.stream_messages(messages):
                    if delta:
                        chunks.append(delta)
                    text_content = "".join(chunks)
                    final_content = "\n\n".join(outputs + [text_content])
                    if len(final_content) > 200000:
                        raise UserFacingError("回答超过安全长度，已保留已生成内容")
                    if time.monotonic() - last_save >= 0.2:
                        checkpoint(run_id, lease, content=final_content)
                        last_save = time.monotonic()
            answer, invalid = validate_citations("".join(chunks), context["evidence"])
            if invalid:
                artifact_warnings.append("已移除无效来源标记: " + ", ".join(invalid))
            if kind not in {"chat", "agent", "visual", "research"}:
                answer, warning = _save_artifact(run_id, kind, answer, context["evidence"], lease)
                if warning:
                    artifact_warnings.append(warning)
            outputs.append(f"## {TEMPLATES[kind]['title']}\n\n{answer}" if action == "study_pack" else answer)
        final_content = "\n\n".join(outputs)
        meta["warnings"] = context["warnings"] + artifact_warnings
        finish_run(run_id, "completed", content=final_content, meta=meta, lease_id=lease)
    except RunCancelled:
        finish_run(run_id, "cancelled", content=final_content or None, lease_id=lease)
    except Exception as exc:
        logger.exception("Assistant run failed: %s", run_id)
        if isinstance(exc, UserFacingError):
            error = str(exc)
        elif isinstance(exc, ValueError):
            error = str(exc)[:500]
        elif isinstance(exc, HTTPException):
            error = "操作权限已变更或素材已不可用"
        else:
            _, error = classify_exception(exc)
        finish_run(run_id, "failed", content=final_content or None, error=error, lease_id=lease)
