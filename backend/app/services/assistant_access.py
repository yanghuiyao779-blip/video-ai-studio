"""Authorization shared by new chat endpoints and existing media endpoints."""
from fastapi import Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.api.deps import current_user
from app.core.config import get_settings
from app.db.models import Job, User
from app.db.assistant import Conversation, Workspace, WorkspaceMember, WorkspaceResource


def deployment_admin(user: User = Depends(current_user)) -> User:
    if user.username != get_settings().admin_username:
        raise HTTPException(403, "仅部署管理员可操作")
    return user


def accessible_workspace_ids(db: Session, user_id: str):
    return select(Workspace.id).where(or_(Workspace.owner_id == user_id, Workspace.id.in_(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id))))


def workspace_access(db: Session, workspace_id: str, user_id: str, write: bool = False) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "项目不存在")
    if workspace.owner_id == user_id:
        return workspace
    role = db.scalar(select(WorkspaceMember.role).where(
        WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))
    if not role or (write and role != "editor"):
        raise HTTPException(404, "项目不存在或无权限")
    return workspace


def conversation_access(db: Session, conversation_id: str, user_id: str, write: bool = False) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "对话不存在")
    # Revoked workspace membership must also revoke access to conversations that
    # the member authored inside that workspace.
    if conversation.workspace_id:
        workspace_access(db, conversation.workspace_id, user_id, write)
    elif conversation.owner_id != user_id:
        raise HTTPException(404, "对话不存在")
    return conversation


def job_visibility(db: Session, user: User):
    return or_(Job.owner_id == user.id, Job.id.in_(select(WorkspaceResource.job_id).where(
        WorkspaceResource.workspace_id.in_(accessible_workspace_ids(db, user.id)))))


def permitted_job(db: Session, job_id: str, user: User, write: bool = False) -> Job:
    query = select(Job).where(Job.id == job_id)
    query = query.where(Job.owner_id == user.id) if write else query.where(job_visibility(db, user))
    job = db.scalar(query)
    if job is None:
        raise HTTPException(404, "任务不存在或无权限")
    return job
