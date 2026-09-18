"""Real media API/storage regression tests; no downloader or ASR calls are faked."""
import json
from pathlib import Path
from sqlalchemy import select
from app.db.models import Job
from app.db.assistant import VideoKnowledgeIndex
from app.db.session import SessionLocal
from app.services.video_knowledge import ensure_lexical_index

SEGMENTS = [{"start": 0, "end": 10, "text": "Original transcript"}]


def test_existing_job_endpoints_enforce_ownership(client, auth, make_job):
    jid = make_job(segments=SEGMENTS)
    assert client.get(f"/api/jobs/{jid}", headers=auth()).status_code == 200
    for path in [f"/api/jobs/{jid}", f"/api/jobs/{jid}/result", f"/api/jobs/{jid}/artifacts/json"]:
        assert client.get(path, headers=auth("alice")).status_code == 404
    assert client.get("/api/jobs", headers=auth("alice")).json() == []
    assert client.post(f"/api/jobs/{jid}/retry", headers=auth("alice")).status_code == 404
    assert client.delete(f"/api/jobs/{jid}", headers=auth("alice")).status_code == 404
    assert client.put(f"/api/jobs/{jid}/transcript", headers=auth("alice"), json={"segments": SEGMENTS}).status_code == 404


def test_local_upload_has_owner_and_can_be_attached_to_chat(client, auth):
    # This tests upload persistence only; bytes are not sent to ASR.
    response = client.post("/api/jobs/upload", headers=auth("alice"),
        files={"file": ("test.mp4", b"test upload bytes", "video/mp4")}, data={"summary_enabled": "false"})
    assert response.status_code == 201, response.text
    jid = response.json()["id"]
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert job.owner_id == "alice"
        assert Path(job.source_path).read_bytes() == b"test upload bytes"
        assert job.status == "queued"
    cid = client.post("/api/assistant/conversations", headers=auth("alice"), json={}).json()["id"]
    assert client.post(f"/api/assistant/conversations/{cid}/resources", headers=auth("alice"), json={"job_id": jid}).status_code == 201
    assert client.get(f"/api/jobs/{jid}", headers=auth()).status_code == 404
    cancelled = client.post(f"/api/jobs/{jid}/cancel", headers=auth("alice"))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"


def test_empty_and_unsupported_uploads_do_not_create_jobs(client, auth):
    response = client.post("/api/jobs/upload", headers=auth(), files={"file": ("empty.mp4", b"", "video/mp4")})
    assert response.status_code == 400
    response = client.post("/api/jobs/upload", headers=auth(), files={"file": ("program.exe", b"x", "application/octet-stream")})
    assert response.status_code == 400
    with SessionLocal() as db:
        assert list(db.scalars(select(Job))) == []


def test_transcript_edit_rebuilds_exports_and_invalidates_qa(client, auth, make_job):
    jid = make_job(segments=SEGMENTS, summary="Old summary")
    ensure_lexical_index(jid)
    updated = [{"start": 1, "end": 9, "text": "Corrected transcript"}]
    response = client.put(f"/api/jobs/{jid}/transcript", headers=auth(), json={"segments": updated})
    assert response.status_code == 200, response.text
    assert response.json()["transcript"]["segments"] == updated
    assert response.json()["summary"] is None
    with SessionLocal() as db:
        job = db.get(Job, jid)
        assert db.get(VideoKnowledgeIndex, jid).status == "stale"
        assert json.loads(job.metadata_json)["transcript_edited"] is True
        assert (Path(job.output_dir)/"all-files.zip").is_file()
    download = client.get(f"/api/jobs/{jid}/artifacts/srt", headers=auth())
    assert download.status_code == 200
    assert "Corrected transcript" in download.text


def test_cannot_edit_transcript_while_media_worker_is_processing(client, auth, make_job):
    jid = make_job(segments=SEGMENTS, status="processing")
    assert client.put(f"/api/jobs/{jid}/transcript", headers=auth(), json={"segments": SEGMENTS}).status_code == 409


def test_regular_accounts_cannot_read_global_keys_or_admin_storage(client, auth):
    assert client.get("/api/settings/llm", headers=auth("alice")).status_code == 403
    assert client.get("/api/settings/storage", headers=auth("alice")).status_code == 403
    response = client.get("/api/settings/llm", headers=auth())
    assert response.status_code == 200
    assert "synthetic-unit-test-key" not in response.text


def test_regular_downloader_never_uses_deployment_platform_cookies(tmp_path, monkeypatch):
    from app.services.downloader import VideoDownloader
    from app.core.config import get_settings
    cookie = tmp_path / "cookie.txt"
    cookie.write_text("synthetic test cookie", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "ytdlp_cookies_file", str(cookie))
    downloader = VideoDownloader(allow_server_credentials=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("A regular account must not read admin cookies")
    monkeypatch.setattr(downloader, "_prepare_writable_cookie_file", forbidden)
    for url in ["https://www.douyin.com/video/123", "https://www.youtube.com/watch?v=x"]:
        assert "cookiefile" not in downloader._common_options(url)


def test_preview_applies_cookie_permissions_before_downloader_call(client, auth, monkeypatch):
    import app.api.jobs as api
    from app.services.downloader import VideoDownloader, PreviewResult
    observed = []
    monkeypatch.setattr(api, "validate_public_url", lambda url: None)
    def preview(self, url):
        observed.append(self.allow_server_credentials)
        return PreviewResult(title="Preview", metadata={})
    monkeypatch.setattr(VideoDownloader, "preview", preview)
    for user in ["alice", "admin"]:
        response = client.post("/api/jobs/preview", headers=auth(user), json={"source_url": "https://www.youtube.com/watch?v=x"})
        assert response.status_code == 200, response.text
    assert observed == [False, True]
