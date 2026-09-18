from __future__ import annotations
import logging
import re
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.models import Creator, CreatorVideo, Job, User
from app.db.assistant import ChatMessage, ChatRun, Conversation, ConversationResource, VideoKnowledgeIndex, WorkspaceResource, now
from app.db.session import SessionLocal
from app.services.assistant_access import conversation_access, permitted_job
from app.services.assistant_templates import TEMPLATES
from app.services.assistant_urls import canonical_url, extract_urls, is_video_candidate
from app.services.jobs import serialize_job
from app.services.platforms import validate_public_url, UnsafeURLError
from app.services.setting_store import get_llm_config, task_defaults_public_view

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled"}


def message_view(message):
    return {"id": message.id, "role": message.role, "content": message.content,
        "status": message.status, "meta": message.meta, "created_at": message.created_at}


def conversation_view(conversation):
    return {"id": conversation.id, "title": conversation.title, "workspace_id": conversation.workspace_id,
        "pinned": conversation.pinned, "archived": conversation.archived, "tags": conversation.tags,
        "active_run_id": conversation.active_run_id, "created_at": conversation.created_at,
        "updated_at": conversation.updated_at}


def artifact_view(artifact):
    return {"id": artifact.id, "run_id": artifact.run_id, "kind": artifact.kind, "title": artifact.title,
        "content": artifact.content, "structured": artifact.structured, "created_at": artifact.created_at}


def run_view(db, run):
    message = db.get(ChatMessage, run.assistant_message_id)
    return {"id": run.id, "conversation_id": run.conversation_id, "status": run.status,
        "stage": run.stage, "revision": run.revision, "trace": run.trace,
        "error_message": run.error_message, "cancel_requested": run.cancel_requested,
        "message": message_view(message) if message else None, "updated_at": run.updated_at}


def resource_views(db, conversation_id, user):
    result = []
    rows = db.scalars(select(ConversationResource).where(ConversationResource.conversation_id == conversation_id).order_by(ConversationResource.created_at))
    for row in rows:
        value = {"id": row.id, "enabled": row.enabled, "job_id": row.job_id, "creator_id": row.creator_id}
        if row.job_id:
            job = db.get(Job, row.job_id)
            if not job:
                continue
            try:
                permitted_job(db, row.job_id, user)
            except HTTPException:
                # Keep a removable placeholder, not fresh metadata after access revocation.
                value.update(restricted=True, job=None, index={"status": "restricted"})
                result.append(value)
                continue
            value["job"] = serialize_job(job)
            value["can_reindex"] = job.owner_id == user.id
            index = db.get(VideoKnowledgeIndex, row.job_id)
            value["index"] = ({"status": index.status, "chunk_count": index.chunk_count,
                "error_message": index.error_message, "embedding_model": index.embedding_model} if index else {"status": "missing"})
        else:
            creator = db.get(Creator, row.creator_id)
            if not creator:
                continue
            value["creator"] = {"id": creator.id, "name": creator.name, "platform": creator.platform}
        result.append(value)
    return result


def attach_job(db: Session, conversation: Conversation, job: Job, user: User):
    existing = db.scalar(select(ConversationResource).where(
        ConversationResource.conversation_id == conversation.id, ConversationResource.job_id == job.id))
    if existing:
        existing.enabled = True
        return existing
    count = len(list(db.scalars(select(ConversationResource.id).where(ConversationResource.conversation_id == conversation.id))))
    if count >= get_settings().assistant_max_resources:
        raise HTTPException(400, "当前对话素材数量已达上限")
    if conversation.workspace_id:
        shared = db.scalar(select(WorkspaceResource).where(
            WorkspaceResource.workspace_id == conversation.workspace_id, WorkspaceResource.job_id == job.id))
        if not shared:
            if job.owner_id != user.id:
                raise HTTPException(403, "不能将他人素材转共享到另一项目")
            db.add(WorkspaceResource(workspace_id=conversation.workspace_id, job_id=job.id))
    resource = ConversationResource(conversation_id=conversation.id, job_id=job.id)
    db.add(resource)
    db.flush()
    return resource


def selected_job_ids(db, conversation, mode, user):
    if mode == "general":
        return []
    ids = []
    resources = db.scalars(select(ConversationResource).where(
        ConversationResource.conversation_id == conversation.id, ConversationResource.enabled.is_(True)))
    for resource in resources:
        if resource.job_id:
            permitted_job(db, resource.job_id, user)
            ids.append(resource.job_id)
        elif resource.creator_id:
            if user.username != get_settings().admin_username:
                raise HTTPException(403, "博主数据仅限部署管理员使用")
            ids.extend(db.scalars(select(CreatorVideo.job_id).where(
                CreatorVideo.creator_id == resource.creator_id, CreatorVideo.job_id.is_not(None))))
    if mode == "workspace" and conversation.workspace_id:
        ids.extend(db.scalars(select(WorkspaceResource.job_id).where(WorkspaceResource.workspace_id == conversation.workspace_id)))
    ids = list(dict.fromkeys(ids))
    if len(ids) > get_settings().assistant_max_resources:
        raise HTTPException(400, f"单次最多使用 {get_settings().assistant_max_resources} 个视频，请选择子集")
    return ids


def enqueue_run(run_id: str, countdown: int = 0):
    if get_settings().queue_mode == "celery":
        from app.workers.celery_app import assistant_run_task
        assistant_run_task.apply_async(args=[run_id], countdown=countdown)


def enqueue_media(job_id: str):
    if get_settings().queue_mode == "celery":
        from app.workers.celery_app import process_job_task
        process_job_task.delay(job_id)


def enqueue_index(job_id: str):
    if get_settings().queue_mode == "celery":
        from app.workers.celery_app import index_video_task
        index_video_task.delay(job_id)
    # Local assistant worker picks up missing / stale attached indexes.


def create_message(db: Session, conversation_id: str, payload, user: User):
    conversation = conversation_access(db, conversation_id, user.id, write=True)
    existing = db.scalar(select(ChatRun).where(ChatRun.conversation_id == conversation_id,
        ChatRun.client_request_id == payload.client_request_id))
    if existing:
        return existing  # Browser timeout/retry does not duplicate jobs or charges.
    if conversation.archived:
        raise HTTPException(409, "请先取消归档再继续对话")
    if not payload.content.strip():
        raise HTTPException(422, "请输入内容")
    urls = []
    if payload.mode != "general" and not re.search(r"不(?:要|需要)?(?:下载|解析)|别(?:下载|解析)", payload.content):
        urls = list(payload.urls) + [url for url in extract_urls(payload.content) if is_video_candidate(url)]
        urls = list(dict.fromkeys(canonical_url(url) for url in urls))
    if len(urls) > 8:
        raise HTTPException(400, "每次最多添加 8 个视频链接")
    for url in urls:
        if not is_video_candidate(url) and payload.mode != "video":
            raise HTTPException(400, "非视频链接不会自动下载；请明确选择视频模式")
        try:
            validate_public_url(url)
        except (UnsafeURLError, ValueError) as exc:
            raise HTTPException(400, "链接不安全或无法解析") from exc
    config = get_llm_config(db)
    if payload.allow_web and not get_settings().assistant_web_api_key:
        raise HTTPException(400, "管理员尚未配置联网搜索")
    if payload.allow_visual and not get_settings().assistant_vision_model:
        raise HTTPException(400, "管理员尚未配置视觉模型")
    if payload.action == "research" and not payload.allow_web:
        raise HTTPException(400, "联网研究需显式允许搜索；不联网请选择普通聊天")
    if payload.action == "visual" and not payload.allow_visual:
        raise HTTPException(400, "画面分析需显式允许发送抽样帧")
    if payload.mode == "workspace" and not conversation.workspace_id:
        raise HTTPException(400, "当前对话不属于项目")
    if payload.mode == "general" and payload.job_ids:
        raise HTTPException(400, "普通聊天不会使用视频，请更改回答范围")
    attached = [permitted_job(db, job_id, user) for job_id in payload.job_ids]
    # Serialize all writers through a conditional update, including SQLite.
    run_id = str(uuid4())
    locked = db.execute(update(Conversation).where(Conversation.id == conversation_id,
        Conversation.active_run_id.is_(None)).values(active_run_id=run_id, updated_at=now()))
    if not locked.rowcount:
        db.rollback()
        existing = db.scalar(select(ChatRun).where(ChatRun.conversation_id == conversation_id,
            ChatRun.client_request_id == payload.client_request_id))
        if existing:
            return existing
        raise HTTPException(409, "当前回答尚未结束，请等待或停止后再发送")
    queued_jobs = []
    try:
        for job in attached:
            attach_job(db, conversation, job, user)
        defaults = task_defaults_public_view(db)
        for url in urls:
            # Reuse only this conversation's existing resource, never another user's cache.
            job = db.scalar(select(Job).join(ConversationResource, ConversationResource.job_id == Job.id).where(
                ConversationResource.conversation_id == conversation_id, Job.source_url == url))
            if job is None:
                job = Job(id=str(uuid4()), owner_id=user.id, source_url=url, source_type="url",
                    title=None, status="queued", stage="queued", progress=0,
                    asr_model=defaults["asr_model"], language=defaults["language"] or None,
                    summary_enabled=bool(config) and defaults["summary_enabled"],
                    summary_language="Chinese", summary_preset="standard")
                db.add(job)
                db.flush()
                queued_jobs.append(job.id)
            attach_job(db, conversation, job, user)
        job_ids = selected_job_ids(db, conversation, payload.mode, user)
        if TEMPLATES[payload.action]["requires_video"] and not job_ids:
            raise HTTPException(400, "请先添加视频或从视频库选择素材")
        if payload.action == "compare" and len(job_ids) < 2:
            raise HTTPException(400, "多视频对比至少需要两个视频")
        if not config and not job_ids:
            raise HTTPException(400, "请先在设置中配置 AI 模型和 API Key")
        user_message = ChatMessage(id=str(uuid4()), conversation_id=conversation_id, role="user",
            content=payload.content.strip(), meta={"job_ids": list(dict.fromkeys([*payload.job_ids, *queued_jobs]))})
        assistant_message = ChatMessage(id=str(uuid4()), conversation_id=conversation_id, role="assistant",
            content="", status="queued", meta={"action": payload.action, "run_id": run_id})
        db.add_all([user_message, assistant_message])
        db.flush()
        data = payload.model_dump()
        data.update(job_ids=job_ids, created_job_ids=queued_jobs)
        run = ChatRun(id=run_id, conversation_id=conversation_id, requested_by=user.id,
            user_message_id=user_message.id, assistant_message_id=assistant_message.id,
            client_request_id=payload.client_request_id, payload=data)
        db.add(run)
        if conversation.title == "新对话":
            title = re.sub(r"https?://\S+", "", payload.content).strip()
            conversation.title = (title or "视频内容分析")[:60]
        conversation.updated_at = now()
        db.commit()
    except Exception:
        db.rollback()
        raise
    # Never hold the transaction open during queue/network work.
    try:
        for job_id in queued_jobs:
            enqueue_media(job_id)
        enqueue_run(run.id)
    except Exception:
        logger.exception("Assistant queue dispatch failed")
        for job_id in queued_jobs:
            job = db.get(Job, job_id)
            if job and job.status == "queued":
                job.status, job.stage = "failed", "failed"
                job.error_code, job.error_message = "queue_error", "任务队列不可用，请检查 Worker"
        db.commit()
        finish_run(run.id, "failed", error="任务队列不可用，请检查 Worker 后重试")
    db.expire_all()
    return db.get(ChatRun, run.id)


def finish_run(run_id, status, *, content=None, error=None, meta=None, lease_id=None, stale_before=None):
    with SessionLocal() as db:
        query = select(ChatRun).where(ChatRun.id == run_id).with_for_update()
        run = db.scalar(query)
        if not run or run.status in TERMINAL or (lease_id and run.lease_id != lease_id):
            return
        if stale_before is not None:
            from datetime import timezone
            updated = run.updated_at.replace(tzinfo=timezone.utc) if run.updated_at.tzinfo is None else run.updated_at
            if updated >= stale_before:
                return
        if run.cancel_requested:
            status = "cancelled"
        message = db.get(ChatMessage, run.assistant_message_id)
        if message:
            if content is not None:
                message.content = content
            message.status = status
            if meta:
                message.meta = {**message.meta, **meta}
            if error:
                message.meta = {**message.meta, "error": error}
        run.status, run.stage, run.error_message = status, status, error
        run.lease_id, run.updated_at = None, now()
        run.revision += 1
        db.execute(update(Conversation).where(Conversation.id == run.conversation_id,
            Conversation.active_run_id == run.id).values(active_run_id=None, updated_at=now()))
        db.commit()


def retry_run(db, old_run, user):
    conversation = conversation_access(db, old_run.conversation_id, user.id, write=True)
    if conversation.archived:
        raise HTTPException(409, "Unarchive conversation before retrying")
    if old_run.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "仅失败或已停止的回答可重试")
    run_id = str(uuid4())
    claimed = db.execute(update(Conversation).where(Conversation.id == conversation.id,
        Conversation.active_run_id.is_(None)).values(active_run_id=run_id, updated_at=now()))
    if not claimed.rowcount:
        db.rollback()
        raise HTTPException(409, "当前对话正在生成")
    message = ChatMessage(id=str(uuid4()), conversation_id=conversation.id, role="assistant", status="queued",
        meta={"action": old_run.payload.get("action", "chat"), "run_id": run_id, "retry_of": old_run.id})
    db.add(message)
    db.flush()
    data = {**old_run.payload, "resume_run_id": old_run.id}
    run = ChatRun(id=run_id, conversation_id=conversation.id, requested_by=user.id,
        user_message_id=old_run.user_message_id, assistant_message_id=message.id,
        client_request_id=str(uuid4()), payload=data)
    db.add(run)
    db.commit()
    try:
        enqueue_run(run.id)
    except Exception:
        finish_run(run.id, "failed", error="队列不可用，请检查 Worker")
    db.expire_all()
    return db.get(ChatRun, run.id)


def recover_stale_runs():
    cutoff = now() - timedelta(seconds=get_settings().assistant_run_lease_seconds)
    with SessionLocal() as db:
        ids = list(db.scalars(select(ChatRun.id).where(ChatRun.status == "running", ChatRun.updated_at < cutoff)))
    for run_id in ids:
        finish_run(run_id, "failed", error="执行进程中断，已保留部分结果；可点击重试", stale_before=cutoff)
