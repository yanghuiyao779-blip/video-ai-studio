from __future__ import annotations
import asyncio
import hashlib
import io
import json
import secrets
import time
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import bearer, current_user
from app.api.assistant_schemas import (ConversationCreate, ConversationUpdate, MemberCreate, MessageCreate,
    ResourceCreate, ResourceUpdate, ShareCreate, UserCreate, WorkspaceCreate)
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Creator, User
from app.db.assistant import (AssistantArtifact, ChatMessage, ChatRun, Conversation, ConversationResource,
    ConversationShare, VideoKnowledgeIndex, Workspace, WorkspaceMember, WorkspaceResource, now)
from app.db.session import SessionLocal, get_db
from app.services.assistant_access import (accessible_workspace_ids, conversation_access, deployment_admin,
    permitted_job, workspace_access)
from app.services.assistant_service import (TERMINAL, artifact_view, attach_job, conversation_view,
    create_message, enqueue_index, finish_run, message_view, resource_views, retry_run, run_view)
from app.services.assistant_templates import TEMPLATES
from app.services.setting_store import get_llm_config

router = APIRouter(prefix="/assistant", tags=["assistant"])


def _run(db, run_id, user_id, write=False):
    run = db.get(ChatRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    conversation_access(db, run.conversation_id, user_id, write)
    return run


def _assert_idle(conversation):
    if conversation.active_run_id:
        raise HTTPException(409, "请先停止或等待当前回答完成")


@router.get("/capabilities")
def capabilities(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = get_settings()
    llm = get_llm_config(db)
    return {"chat": bool(llm), "model": llm.model if llm else None,
        "embedding": bool(llm and llm.embedding_model), "web": bool(cfg.assistant_web_api_key),
        "visual": bool(cfg.assistant_vision_model), "capture_frames": cfg.assistant_capture_frames,
        "max_resources": cfg.assistant_max_resources,
        "admin": user.username == cfg.admin_username,
        "actions": [{"id": key, "title": value["title"], "requires_video": value["requires_video"]}
                    for key, value in TEMPLATES.items()]}


@router.post("/conversations", status_code=201)
def create_conversation(payload: ConversationCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.workspace_id:
        workspace_access(db, payload.workspace_id, user.id, write=True)
    conversation = Conversation(owner_id=user.id, title=payload.title.strip(), workspace_id=payload.workspace_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation_view(conversation)


@router.get("/conversations")
def list_conversations(q: str = Query(default="", max_length=200), archived: bool = False,
    workspace_id: str | None = None, tag: str | None = None, pinned: bool | None = None, limit: int = Query(default=40, ge=1, le=100),
    offset: int = Query(default=0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)):
    visibility = or_((Conversation.owner_id == user.id) & Conversation.workspace_id.is_(None),
        Conversation.workspace_id.in_(accessible_workspace_ids(db, user.id)))
    query = select(Conversation).where(visibility, Conversation.archived == archived)
    if workspace_id:
        workspace_access(db, workspace_id, user.id)
        query = query.where(Conversation.workspace_id == workspace_id)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(or_(Conversation.title.ilike(pattern, escape="\\"), Conversation.id.in_(
            select(ChatMessage.conversation_id).where(ChatMessage.content.ilike(pattern, escape="\\")))))
    if pinned is not None:
        query = query.where(Conversation.pinned.is_(pinned))
    query = query.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
    if tag:
        # Exact JSON membership, before pagination; supported by SQLite and PG.
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy import cast
            from sqlalchemy.dialects.postgresql import JSONB
            query = query.where(cast(Conversation.tags, JSONB).contains([tag]))
        else:
            values = func.json_each(Conversation.tags).table_valued("value")
            query = query.where(select(1).select_from(values).where(values.c.value == tag).exists())
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    items = list(db.scalars(query.offset(offset).limit(limit)))
    return {"items": [conversation_view(c) for c in items], "total": total,
        "next_offset": offset + limit if offset + limit < total else None}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id)
    messages = list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(200)))
    total = db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
    artifacts = list(db.scalars(select(AssistantArtifact).where(AssistantArtifact.conversation_id == conversation_id).order_by(AssistantArtifact.created_at)))
    active_run = db.get(ChatRun, conversation.active_run_id) if conversation.active_run_id else None
    writable = True
    try:
        conversation_access(db, conversation_id, user.id, write=True)
    except HTTPException:
        writable = False
    return {**conversation_view(conversation), "messages": [message_view(m) for m in reversed(messages)],
        "resources": resource_views(db, conversation_id, user), "artifacts": [artifact_view(a) for a in artifacts],
        "active_run": run_view(db, active_run) if active_run else None,
        "message_count": total, "has_older_messages": total > len(messages), "can_edit": writable}


@router.get("/conversations/{conversation_id}/messages")
def older_messages(conversation_id: str, offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=200), user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation_access(db, conversation_id, user.id)
    rows = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).offset(offset).limit(limit))
    return [message_view(row) for row in reversed(list(rows))]


@router.patch("/conversations/{conversation_id}")
def edit_conversation(conversation_id: str, payload: ConversationUpdate,
    user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id, write=True)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(conversation, key, value.strip() if key == "title" else value)
    conversation.updated_at = now()
    db.commit()
    return conversation_view(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id, write=True)
    _assert_idle(conversation)
    db.delete(conversation)
    db.commit()


@router.post("/conversations/{conversation_id}/messages", status_code=202)
def send_message(conversation_id: str, payload: MessageCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return run_view(db, create_message(db, conversation_id, payload, user))


@router.post("/conversations/{conversation_id}/resources", status_code=201)
def add_resource(conversation_id: str, payload: ResourceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id, write=True)
    _assert_idle(conversation)
    if bool(payload.job_id) == bool(payload.creator_id):
        raise HTTPException(422, "Provide exactly one job_id or creator_id")
    if payload.job_id:
        attach_job(db, conversation, permitted_job(db, payload.job_id, user), user)
    else:
        deployment_admin(user)
        if conversation.workspace_id:
            raise HTTPException(400, "博主整库暂不可共享；请选择具体视频添加到项目")
        if not db.get(Creator, payload.creator_id):
            raise HTTPException(404, "Creator not found")
        existing = db.scalar(select(ConversationResource).where(ConversationResource.conversation_id == conversation_id,
            ConversationResource.creator_id == payload.creator_id))
        if not existing:
            db.add(ConversationResource(conversation_id=conversation_id, creator_id=payload.creator_id))
    conversation.updated_at = now()
    db.commit()
    if payload.job_id:
        try:
            enqueue_index(payload.job_id)
        except Exception:
            pass  # Retrieval itself can always build the lexical index on demand.
    return resource_views(db, conversation_id, user)


@router.patch("/conversations/{conversation_id}/resources/{resource_id}")
def toggle_resource(conversation_id: str, resource_id: str, payload: ResourceUpdate,
    user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id, write=True)
    _assert_idle(conversation)
    resource = db.get(ConversationResource, resource_id)
    if not resource or resource.conversation_id != conversation_id:
        raise HTTPException(404, "Resource not found")
    if payload.enabled and resource.job_id:
        permitted_job(db, resource.job_id, user)
    resource.enabled = payload.enabled
    db.commit()
    return resource_views(db, conversation_id, user)


@router.delete("/conversations/{conversation_id}/resources/{resource_id}", status_code=204)
def remove_resource(conversation_id: str, resource_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id, write=True)
    _assert_idle(conversation)
    resource = db.get(ConversationResource, resource_id)
    if not resource or resource.conversation_id != conversation_id:
        raise HTTPException(404, "Resource not found")
    db.delete(resource)
    db.commit()  # Does NOT delete the original video or project resource.


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return run_view(db, _run(db, run_id, user.id))


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    run = _run(db, run_id, user.id, write=True)
    if run.status not in TERMINAL:
        run.cancel_requested = True
        run.revision += 1
        db.commit()
        if run.status in {"queued", "waiting"}:
            finish_run(run.id, "cancelled")
    db.expire_all()
    return run_view(db, db.get(ChatRun, run_id))


@router.post("/runs/{run_id}/retry", status_code=202)
def retry(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return run_view(db, retry_run(db, _run(db, run_id, user.id, write=True), user))


def _stream_identity(credentials=Depends(bearer)):
    # Deliberately closes the auth DB session BEFORE returning a streaming response.
    with SessionLocal() as db:
        return current_user(credentials, db).id


def _snapshot(run_id, user_id):
    with SessionLocal() as db:
        return jsonable_encoder(run_view(db, _run(db, run_id, user_id)))


@router.get("/runs/{run_id}/stream")
def stream_run(run_id: str, user_id: str = Depends(_stream_identity)):
    _snapshot(run_id, user_id)

    async def events():
        revision, heartbeat = -1, time.monotonic()
        while True:
            try:
                snapshot = await asyncio.to_thread(_snapshot, run_id, user_id)
            except HTTPException:
                yield 'event: error\ndata: {"message":"Access revoked or run deleted"}\n\n'
                return
            if snapshot["revision"] != revision:
                revision = snapshot["revision"]
                yield f"id: {revision}\nevent: snapshot\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            if snapshot["status"] in TERMINAL:
                return
            if time.monotonic() - heartbeat >= 10:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            await asyncio.sleep(0.35)
    return StreamingResponse(events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})


@router.post("/videos/{job_id}/index", status_code=202)
def reindex(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    permitted_job(db, job_id, user, write=True)
    index = db.get(VideoKnowledgeIndex, job_id)
    if index:
        index.status = "stale"
    else:
        db.add(VideoKnowledgeIndex(job_id=job_id, status="missing"))
    db.commit()
    try:
        enqueue_index(job_id)
    except Exception as exc:
        raise HTTPException(503, "Index worker unavailable") from exc
    return {"status": "queued"}


@router.get("/conversations/{conversation_id}/export")
def export_conversation(conversation_id: str, format: str = Query(default="markdown", pattern="^(markdown|json|zip)$"),
    user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id)
    messages = list(db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.created_at, ChatMessage.id)))
    artifacts = list(db.scalars(select(AssistantArtifact).where(AssistantArtifact.conversation_id == conversation_id)))
    data = jsonable_encoder({"conversation": conversation_view(conversation), "messages": [message_view(m) for m in messages],
        "artifacts": [artifact_view(a) for a in artifacts]})
    markdown = f"# {conversation.title}\n\n" + "\n\n---\n\n".join(f"## {m.role}\n\n{m.content}" for m in messages)
    for m in messages:
        if m.meta.get("evidence"):
            markdown += f"\n\n### Evidence for {m.id}\n\n" + "\n".join(
                f"- [{e['id']}] {e.get('title', '')} {e.get('start_seconds', '')}: {e.get('excerpt', '')}" for e in m.meta["evidence"])
    if format == "zip":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("conversation.md", markdown)
            archive.writestr("conversation.json", json.dumps(data, ensure_ascii=False, indent=2))
            for a in artifacts:
                archive.writestr(f"artifacts/{a.kind}-{a.id}.md", a.content)
                if a.structured:
                    archive.writestr(f"artifacts/{a.kind}-{a.id}.json", json.dumps(a.structured, ensure_ascii=False, indent=2))
        body, mime, suffix = buffer.getvalue(), "application/zip", "zip"
    elif format == "json":
        body, mime, suffix = json.dumps(data, ensure_ascii=False, indent=2), "application/json", "json"
    else:
        body, mime, suffix = markdown, "text/markdown", "md"
    return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="conversation-{conversation_id}.{suffix}"'})


@router.get("/workspaces")
def workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Workspace).where(Workspace.id.in_(accessible_workspace_ids(db, user.id))).order_by(Workspace.created_at.desc()))
    result = []
    for row in rows:
        role = "owner" if row.owner_id == user.id else db.scalar(select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == row.id, WorkspaceMember.user_id == user.id))
        result.append({"id": row.id, "name": row.name, "instructions": row.instructions, "role": role})
    return result


@router.post("/workspaces", status_code=201)
def create_workspace(payload: WorkspaceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = Workspace(owner_id=user.id, name=payload.name.strip(), instructions=payload.instructions)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return {"id": workspace.id, "name": workspace.name, "instructions": workspace.instructions, "role": "owner"}


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, payload: WorkspaceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = workspace_access(db, workspace_id, user.id, write=True)
    workspace.name, workspace.instructions = payload.name.strip(), payload.instructions
    db.commit()
    return {"id": workspace.id, "name": workspace.name, "instructions": workspace.instructions}


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = workspace_access(db, workspace_id, user.id, write=True)
    if workspace.owner_id != user.id:
        raise HTTPException(403, "Only project owner may delete it")
    conversations = list(db.scalars(select(Conversation).where(Conversation.workspace_id == workspace_id)))
    for conversation in conversations:
        _assert_idle(conversation)
    for conversation in conversations:
        db.delete(conversation)
    db.delete(workspace)
    db.commit()


@router.get("/workspaces/{workspace_id}/members")
def members(workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = workspace_access(db, workspace_id, user.id)
    owner = db.get(User, workspace.owner_id)
    result = [{"id": owner.id, "username": owner.username, "role": "owner"}]
    rows = db.execute(select(WorkspaceMember, User).join(User, WorkspaceMember.user_id == User.id).where(WorkspaceMember.workspace_id == workspace_id))
    return result + [{"id": member.user_id, "username": account.username, "role": member.role} for member, account in rows]


@router.post("/workspaces/{workspace_id}/members")
def add_member(workspace_id: str, payload: MemberCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = workspace_access(db, workspace_id, user.id, write=True)
    if workspace.owner_id != user.id:
        raise HTTPException(403, "Only project owner may change membership")
    target = db.scalar(select(User).where(User.username == payload.username))
    if not target:
        raise HTTPException(404, "用户不存在；请先由管理员创建账号")
    if target.id == workspace.owner_id:
        raise HTTPException(400, "Cannot change project owner's role")
    member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == target.id))
    if member:
        member.role = payload.role
    else:
        db.add(WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=payload.role))
    db.commit()
    return {"id": target.id, "username": target.username, "role": payload.role}


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = workspace_access(db, workspace_id, user.id, write=True)
    if workspace.owner_id != user.id:
        raise HTTPException(403, "Only project owner may change membership")
    db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))
    db.commit()


@router.post("/workspaces/{workspace_id}/resources", status_code=201)
def add_workspace_resource(workspace_id: str, payload: ResourceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace_access(db, workspace_id, user.id, write=True)
    if not payload.job_id or payload.creator_id:
        raise HTTPException(422, "Provide a job_id")
    job = permitted_job(db, payload.job_id, user, write=True)
    existing = db.scalar(select(WorkspaceResource).where(WorkspaceResource.workspace_id == workspace_id, WorkspaceResource.job_id == job.id))
    if not existing:
        db.add(WorkspaceResource(workspace_id=workspace_id, job_id=job.id))
        db.commit()
    return {"job_id": job.id}


@router.get("/workspaces/{workspace_id}/resources")
def workspace_resources(workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    from app.db.models import Job
    from app.services.jobs import serialize_job
    workspace_access(db, workspace_id, user.id)
    jobs = db.scalars(select(Job).join(WorkspaceResource, WorkspaceResource.job_id == Job.id).where(WorkspaceResource.workspace_id == workspace_id))
    return [serialize_job(job) for job in jobs]


@router.delete("/workspaces/{workspace_id}/resources/{job_id}", status_code=204)
def remove_workspace_resource(workspace_id: str, job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace_access(db, workspace_id, user.id, write=True)
    conversations = list(db.scalars(select(Conversation).where(Conversation.workspace_id == workspace_id)))
    for conversation in conversations:
        _assert_idle(conversation)
    ids = [c.id for c in conversations]
    db.execute(delete(ConversationResource).where(ConversationResource.conversation_id.in_(ids), ConversationResource.job_id == job_id))
    db.execute(delete(WorkspaceResource).where(WorkspaceResource.workspace_id == workspace_id, WorkspaceResource.job_id == job_id))
    db.commit()


@router.post("/users", status_code=201)
def create_user(payload: UserCreate, _: User = Depends(deployment_admin), db: Session = Depends(get_db)):
    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Username already exists") from exc
    return {"id": user.id, "username": user.username}


@router.post("/conversations/{conversation_id}/shares", status_code=201)
def share_conversation(conversation_id: str, payload: ShareCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = conversation_access(db, conversation_id, user.id, write=True)
    _assert_idle(conversation)
    messages = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.created_at, ChatMessage.id))
    clean_messages = []
    for message in messages:
        value = {"role": message.role, "content": message.content}
        if payload.include_sources:
            value["evidence"] = [{k: v for k, v in evidence.items() if k in {"id", "title", "excerpt", "start_seconds", "end_seconds", "url"}}
                for evidence in message.meta.get("evidence", [])]
        clean_messages.append(value)
    token = secrets.token_urlsafe(32)
    share = ConversationShare(conversation_id=conversation_id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
        snapshot={"title": conversation.title, "messages": clean_messages}, expires_at=now() + timedelta(days=payload.expires_in_days))
    db.add(share)
    db.commit()
    db.refresh(share)
    return {"id": share.id, "path": f"/share/{token}", "expires_at": share.expires_at}


@router.get("/conversations/{conversation_id}/shares")
def list_shares(conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation_access(db, conversation_id, user.id, write=True)
    rows = db.scalars(select(ConversationShare).where(ConversationShare.conversation_id == conversation_id))
    return [{"id": s.id, "expires_at": s.expires_at, "revoked": s.revoked} for s in rows]


@router.delete("/conversations/{conversation_id}/shares/{share_id}", status_code=204)
def revoke_share(conversation_id: str, share_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation_access(db, conversation_id, user.id, write=True)
    share = db.get(ConversationShare, share_id)
    if not share or share.conversation_id != conversation_id:
        raise HTTPException(404, "Share not found")
    share.revoked = True
    db.commit()


@router.get("/shared/{token}")
def shared_snapshot(token: str, db: Session = Depends(get_db)):
    if not 32 <= len(token) <= 100:
        raise HTTPException(404, "Share unavailable")
    share = db.scalar(select(ConversationShare).where(ConversationShare.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    expiry = share.expires_at.replace(tzinfo=timezone.utc) if share and share.expires_at.tzinfo is None else (share.expires_at if share else None)
    if not share or share.revoked or expiry <= datetime.now(timezone.utc):
        raise HTTPException(404, "分享已失效或已撤销")
    return JSONResponse(share.snapshot, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"})
