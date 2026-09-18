from typing import Literal
from pydantic import BaseModel, Field, field_validator


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=200)
    workspace_id: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=12)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags):
        if tags is None:
            return None
        result = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        if any(len(t) > 32 for t in result):
            raise ValueError("Tag length must be <=32")
        return result


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=16000)
    client_request_id: str = Field(min_length=8, max_length=80)
    action: Literal["chat", "summary", "notes", "meeting", "timeline", "mindmap", "script", "compare", "research", "visual", "agent", "study_pack"] = "chat"
    mode: Literal["auto", "general", "video", "workspace"] = "auto"
    urls: list[str] = Field(default_factory=list, max_length=8)
    job_ids: list[str] = Field(default_factory=list, max_length=20)
    allow_web: bool = False
    allow_visual: bool = False


class ResourceCreate(BaseModel):
    job_id: str | None = None
    creator_id: str | None = None


class ResourceUpdate(BaseModel):
    enabled: bool


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=8000)


class MemberCreate(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    role: Literal["viewer", "editor"]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120, pattern=r"^[\w.@-]+$")
    password: str = Field(min_length=12, max_length=128)


class ShareCreate(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=30)
    include_sources: bool = False
