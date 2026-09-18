import io
import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select

from app.db.assistant import AssistantArtifact, ChatRun
from app.db.models import Job
from app.db.session import SessionLocal, engine
from app.services.assistant_runner import process_run

PREFIX = "/api/assistant"
SEGMENTS = [{"start": 1, "end": 9, "text": "Retrieval uses documents and evidence."}]


def start(client, headers, job_id, action="study_pack"):
    cid = client.post(PREFIX + "/conversations", headers=headers, json={}).json()["id"]
    run = client.post(f"{PREFIX}/conversations/{cid}/messages", headers=headers, json={
        "content": "Make study notes", "client_request_id": str(uuid4()),
        "action": action, "job_ids": [job_id],
    })
    assert run.status_code == 202, run.text
    return cid, run.json()["id"]


def test_workflow_resume_reuses_valid_completed_step(client, auth, make_job, monkeypatch):
    import app.services.assistant_runner as runner
    state = {"fail": True, "notes": 0}

    class Provider:
        def __init__(self, config):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def stream_messages(self, messages):
            prompt = messages[-1]["content"]
            if 'Return ONLY JSON: {"chapters"' in prompt:
                if state["fail"]:
                    raise RuntimeError("Synthetic provider failure")
                yield '{"chapters":[{"title":"Chapter","source_id":"V1","summary":"Detail"}]}'
            elif 'Return ONLY JSON: {"title"' in prompt:
                yield '{"title":"Concept","children":[]}'
            else:
                state["notes"] += 1
                yield "Notes with evidence [V1]"

    monkeypatch.setattr(runner, "OpenAICompatibleLLM", Provider)
    cid, rid = start(client, auth(), make_job(segments=SEGMENTS))
    process_run(rid)
    with SessionLocal() as db:
        assert db.get(ChatRun, rid).status == "failed"
        artifacts = list(db.scalars(select(AssistantArtifact).where(AssistantArtifact.run_id == rid)))
        assert [a.kind for a in artifacts] == ["notes"]
    state["fail"] = False
    retry = client.post(f"{PREFIX}/runs/{rid}/retry", headers=auth())
    assert retry.status_code == 202
    new_id = retry.json()["id"]
    process_run(new_id)
    with SessionLocal() as db:
        assert db.get(ChatRun, new_id).status == "completed"
        assert len(list(db.scalars(select(AssistantArtifact).where(AssistantArtifact.run_id == new_id)))) == 3
    assert state["notes"] == 1
    conversation = client.get(f"{PREFIX}/conversations/{cid}", headers=auth()).json()
    assert len([m for m in conversation["messages"] if m["role"] == "user"]) == 1


def test_duplicate_worker_dispatch_cannot_repeat_completed_generation(client, auth, make_job, fake_llm):
    _cid, rid = start(client, auth(), make_job(segments=SEGMENTS), action="notes")
    process_run(rid)
    calls = len(fake_llm.calls)
    process_run(rid)
    assert len(fake_llm.calls) == calls
    assert client.get(f"{PREFIX}/runs/{rid}", headers=auth()).json()["status"] == "completed"


def test_revoked_project_source_no_longer_exposes_live_metadata(client, auth, make_job):
    admin, alice = auth(), auth("alice")
    jid = make_job(segments=SEGMENTS)
    wid = client.post(PREFIX + "/workspaces", headers=admin, json={"name": "Shared"}).json()["id"]
    assert client.post(f"{PREFIX}/workspaces/{wid}/resources", headers=admin, json={"job_id": jid}).status_code == 201
    assert client.post(f"{PREFIX}/workspaces/{wid}/members", headers=admin, json={"username": "alice", "role": "editor"}).status_code == 200
    cid = client.post(PREFIX + "/conversations", headers=alice, json={}).json()["id"]
    assert client.post(f"{PREFIX}/conversations/{cid}/resources", headers=alice, json={"job_id": jid}).status_code == 201
    assert client.delete(f"{PREFIX}/workspaces/{wid}/members/alice", headers=admin).status_code == 204
    with SessionLocal() as db:
        db.get(Job, jid).title = "NEW PRIVATE DATA AFTER REVOCATION"
        db.commit()
    response = client.get(f"{PREFIX}/conversations/{cid}", headers=alice)
    assert response.status_code == 200
    assert "NEW PRIVATE DATA" not in response.text
    source = response.json()["resources"][0]
    assert source["restricted"] and source["job"] is None
    assert client.patch(f"{PREFIX}/conversations/{cid}/resources/{source['id']}", headers=alice, json={"enabled": True}).status_code in {403, 404}
    assert client.delete(f"{PREFIX}/conversations/{cid}/resources/{source['id']}", headers=alice).status_code == 204


def test_frozen_postgres_migration_compiles_offline():
    # SQL generation validates the frozen migration, not PostgreSQL execution.
    path = Path(__file__).parents[2] / "alembic/versions/0009_assistant_workspace.py"
    spec = importlib.util.spec_from_file_location("assistant_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = buffer.getvalue()
    assert sql.count("CREATE TABLE") == 11
    assert "vector(1536)" in sql
    assert "DROP CONSTRAINT fk_jobs_owner_id" in sql
    assert "ALTER TABLE jobs ADD COLUMN owner_id" in sql


def test_bootstrap_adopts_legacy_unowned_jobs_without_deleting_results(make_job):
    from app.db.bootstrap import bootstrap_database
    jid = make_job(segments=SEGMENTS)
    with SessionLocal() as db:
        job = db.get(Job, jid)
        output = Path(job.output_dir) / "result.json"
        previous = output.read_bytes()
        job.owner_id = None
        db.commit()
    bootstrap_database()
    with SessionLocal() as db:
        assert db.get(Job, jid).owner_id == "admin"
    assert output.read_bytes() == previous
    assert "conversations" in inspect(engine).get_table_names()


def test_json_fallback_rejects_truncated_answers():
    import httpx
    from app.services.llm import OpenAICompatibleLLM
    from app.services.setting_store import LLMConfig
    import pytest
    config = LLMConfig(provider="custom", base_url="https://unit.test/v1", model="test", api_key="test", temperature=.2, custom_prompt=None)
    with OpenAICompatibleLLM(config) as llm:
        llm.client.close()
        llm.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": "incomplete"}, "finish_reason": "length"}]})))
        with pytest.raises(RuntimeError, match="complete answer"):
            list(llm.stream_messages([{"role": "user", "content": "Hello"}]))
