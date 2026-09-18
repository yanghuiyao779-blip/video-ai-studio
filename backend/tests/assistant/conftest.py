"""Offline integration harness: real SQLite/FastAPI, fake provider only.

Never reads or writes a deployment database. The normal API dependencies,
permissions, run executor and artifacts remain real in these tests.
"""
# ruff: noqa: E402
# Environment must be isolated before importing modules that bind the DB engine.
import atexit
import json
import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
import pytest

ROOT = Path(tempfile.mkdtemp(prefix="video-ai-tests-"))
atexit.register(shutil.rmtree, ROOT, True)
os.environ.update(APP_SECRET_KEY="a" * 48, APP_ENCRYPTION_KEY="b" * 48,
    ADMIN_PASSWORD="assistant-test-password", ADMIN_USERNAME="admin",
    DATABASE_URL=f"sqlite:///{ROOT / 'test.sqlite'}", DATA_DIR=str(ROOT / "data"),
    QUEUE_MODE="local", ASSISTANT_CAPTURE_FRAMES="false", ASSISTANT_VISION_MODEL="",
    ASSISTANT_WEB_API_KEY="")
from app.core.config import get_settings
get_settings.cache_clear()
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.models import User, Job
from app.db.session import SessionLocal, engine
from app.services.setting_store import update_llm_config
from app.api.assistant import router
from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.settings import router as settings_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


@pytest.fixture(autouse=True)
def isolated_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for username in ["admin", "alice", "bob"]:
            db.add(User(id=username, username=username, password_hash=hash_password("test-password-123")))
        db.commit()
        update_llm_config(db, "custom", "https://unit.test/v1", "test-chat",
            "synthetic-unit-test-key", .2, None)
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth():
    return lambda username="admin": {"Authorization": "Bearer " + create_access_token(username)}


@pytest.fixture
def make_job():
    def create(owner="admin", segments=None, status="completed", name="Test video", summary="Summary"):
        job_id = str(uuid4())
        path = get_settings().data_dir / "jobs" / job_id
        path.mkdir(parents=True)
        if segments is not None:
            (path / "result.json").write_text(json.dumps({"transcript": {"segments": segments}, "summary": summary}, ensure_ascii=False), encoding="utf-8")
        with SessionLocal() as db:
            job = Job(id=job_id, owner_id=owner, source_url="https://www.youtube.com/watch?v=" + job_id,
                title=name, status=status, stage=status, progress=100 if status=="completed" else 0,
                output_dir=str(path), summary_enabled=True)
            db.add(job)
            db.commit()
        return job_id
    return create


@pytest.fixture
def fake_llm(monkeypatch):
    import app.services.assistant_runner as runner
    class FakeLLM:
        calls = []
        def __init__(self, config):
            self.config = config
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def stream_messages(self, messages):
            self.calls.append(messages)
            prompt = messages[-1]["content"]
            if 'Return ONLY JSON: {"chapters"' in prompt:
                yield '{"chapters":[{"title":"Chapter","source_id":"V1","summary":"Grounded chapter"}]}'
            elif 'Return ONLY JSON: {"title"' in prompt:
                yield '{"title":"Topic","children":[{"title":"Point [V1]","children":[]}]}'
            else:
                yield "Answer "
                yield "[V1]" if '"id": "V1"' in prompt else "to your question."
    monkeypatch.setattr(runner, "OpenAICompatibleLLM", FakeLLM)
    return FakeLLM
