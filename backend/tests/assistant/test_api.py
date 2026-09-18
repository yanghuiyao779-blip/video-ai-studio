import io
import json
import zipfile
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, func
from app.db.models import AppSetting, Job
from app.db.assistant import ChatRun, ChatMessage, ConversationShare, now
from app.db.session import SessionLocal
from app.services.assistant_runner import process_run
from app.services.assistant_service import recover_stale_runs

PREFIX = "/api/assistant"
SEGMENTS = [{"start":0,"end":12,"text":"RAG retrieves company documents."},{"start":480,"end":495,"text":"At eight minutes, compare lexical search and embeddings."}]


def conversation(client, headers, **kw):
    r = client.post(PREFIX+"/conversations", json=kw, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def send(client, headers, cid, content="Explain RAG", **kw):
    return client.post(f"{PREFIX}/conversations/{cid}/messages", headers=headers,
        json={"content":content,"client_request_id":str(uuid4()),**kw})


def read(client, headers, cid):
    r=client.get(f"{PREFIX}/conversations/{cid}",headers=headers)
    assert r.status_code == 200,r.text
    return r.json()


def test_requires_login_and_capabilities_no_secret(client, auth):
    assert client.get(PREFIX+"/conversations").status_code == 401
    r=client.get(PREFIX+"/capabilities",headers=auth()).json()
    assert r["chat"] and not r["web"] and not r["visual"]
    assert "synthetic-unit-test-key" not in json.dumps(r)


def test_streaming_chat_persists_history_and_idempotency(client,auth,fake_llm):
    h=auth()
    cid=conversation(client,h)
    key=str(uuid4())
    r=send(client,h,cid,client_request_id=key)
    assert r.status_code == 202,r.text
    rid=r.json()["id"]
    duplicate=send(client,h,cid,client_request_id=key)
    assert duplicate.json()["id"]==rid
    assert send(client,h,cid).status_code==409
    process_run(rid)
    c=read(client,h,cid)
    assert len(c["messages"])==2 and c["active_run_id"] is None
    assert c["messages"][-1]["content"]=="Answer to your question."
    r2=send(client,h,cid,"Give an example")
    process_run(r2.json()["id"])
    assert len(read(client,h,cid)["messages"])==4
    history=fake_llm.calls[-1]
    assert any(m["content"]=="Explain RAG" for m in history)
    assert any(m["content"]=="Answer to your question." for m in history)
    stream=client.get(f"{PREFIX}/runs/{rid}/stream",headers=h)
    assert stream.status_code==200 and stream.text.count("event: snapshot")==1
    assert "no-store" in stream.headers["cache-control"]
    assert '"status": "completed"' in stream.text


def test_general_mode_does_not_download_a_video_link(client,auth,fake_llm):
    h=auth()
    cid=conversation(client,h)
    r=send(client,h,cid,"https://www.youtube.com/watch?v=test",mode="general")
    assert r.status_code==202,r.text
    process_run(r.json()["id"])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Job))==0
    assert not read(client,h,cid)["resources"]


def test_plain_webpage_is_chat_not_a_download(client,auth,fake_llm):
    h=auth()
    cid=conversation(client,h)
    r=send(client,h,cid,"Discuss https://example.org/article")
    assert r.status_code==202
    process_run(r.json()["id"])
    assert not read(client,h,cid)["resources"]


def test_url_creates_one_job_and_waiting_resumes(client,auth,fake_llm,monkeypatch):
    import app.services.assistant_service as service
    monkeypatch.setattr(service,"validate_public_url",lambda url:None)
    h=auth()
    cid=conversation(client,h)
    key=str(uuid4())
    url="https://www.youtube.com/watch?v=abc123"
    r=send(client,h,cid,"Summarize "+url,client_request_id=key)
    assert r.status_code==202,r.text
    rid=r.json()["id"]
    assert send(client,h,cid,"Summarize "+url,client_request_id=key).json()["id"]==rid
    process_run(rid)
    assert client.get(f"{PREFIX}/runs/{rid}",headers=h).json()["status"]=="waiting"
    c=read(client,h,cid)
    assert len(c["resources"])==1
    from app.core.config import get_settings
    jid=c["resources"][0]["job_id"]
    with SessionLocal() as db:
        job=db.get(Job,jid)
        assert job.owner_id=="admin"
        root=get_settings().data_dir/"jobs"/jid
        root.mkdir(parents=True)
        (root/"result.json").write_text(json.dumps({"transcript":{"segments":SEGMENTS}}))
        job.output_dir=str(root)
        job.status="completed"
        job.progress=100
        db.commit()
    process_run(rid)
    c=read(client,h,cid)
    assert c["messages"][-1]["status"]=="completed"
    assert c["messages"][-1]["meta"]["evidence"][0]["job_id"]==jid
    r=send(client,h,cid,"again "+url)
    assert r.status_code==202
    assert len(read(client,h,cid)["resources"])==1


def test_untrusted_or_forbidden_url_does_not_create_jobs(client,auth,monkeypatch):
    import app.services.assistant_service as service
    from app.services.platforms import UnsafeURLError
    def reject(url):
        raise UnsafeURLError("private host")
    monkeypatch.setattr(service,"validate_public_url",reject)
    h=auth()
    cid=conversation(client,h)
    assert send(client,h,cid,"http://127.0.0.1/test.mp4").status_code==400
    assert not read(client,h,cid)["messages"]


def test_ordinary_users_cannot_read_other_private_conversations(client,auth):
    cid=conversation(client,auth("alice"))
    assert client.get(f"{PREFIX}/conversations/{cid}",headers=auth("bob")).status_code==404
    assert client.get(PREFIX+"/conversations",headers=auth("bob")).json()["total"]==0
    assert send(client,auth("bob"),cid).status_code==404


def test_private_video_and_mutations_are_scoped(client,auth,make_job):
    jid=make_job(owner="alice",segments=SEGMENTS)
    cid=conversation(client,auth("bob"))
    assert client.post(f"{PREFIX}/conversations/{cid}/resources",headers=auth("bob"),json={"job_id":jid}).status_code==404
    assert client.post(f"{PREFIX}/videos/{jid}/index",headers=auth("bob")).status_code==404


def test_source_qa_artifacts_citations_and_export(client,auth,make_job,fake_llm):
    h=auth()
    cid=conversation(client,h)
    jid=make_job(segments=SEGMENTS)
    assert client.post(f"{PREFIX}/conversations/{cid}/resources",headers=h,json={"job_id":jid}).status_code==201
    r=send(client,h,cid,action="study_pack")
    assert r.status_code==202,r.text
    process_run(r.json()["id"])
    c=read(client,h,cid)
    assert c["messages"][-1]["status"]=="completed",c
    assert {a["kind"] for a in c["artifacts"]}=={"notes","timeline","mindmap"}
    timeline=next(a for a in c["artifacts"] if a["kind"]=="timeline")
    assert timeline["structured"]["chapters"][0]["job_id"]==jid
    assert "run_id" in timeline
    r=client.get(f"{PREFIX}/conversations/{cid}/export?format=zip",headers=h)
    with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
        assert "conversation.json" in archive.namelist()
        assert len(archive.namelist())==7
    assert client.get(f"{PREFIX}/conversations/{cid}/export?format=json",headers=h).json()["messages"]


def test_source_toggle_and_no_secret_cross_video(client,auth,make_job,fake_llm):
    h=auth()
    cid=conversation(client,h)
    j1=make_job(segments=SEGMENTS)
    j2=make_job(owner="alice",segments=[{"start":0,"end":10,"text":"ALICE_PRIVATE_CONTENT"}])
    r=client.post(f"{PREFIX}/conversations/{cid}/resources",headers=h,json={"job_id":j1})
    resource=r.json()[0]["id"]
    client.patch(f"{PREFIX}/conversations/{cid}/resources/{resource}",headers=h,json={"enabled":False})
    r=send(client,h,cid)
    process_run(r.json()["id"])
    assert not read(client,h,cid)["messages"][-1]["meta"]["evidence"]
    assert "ALICE_PRIVATE_CONTENT" not in json.dumps(fake_llm.calls)
    assert j2 not in json.dumps(read(client,h,cid))


def test_compare_requires_two_sources_and_failed_validation_releases_lock(client,auth,make_job):
    h=auth()
    cid=conversation(client,h)
    jid=make_job(segments=SEGMENTS)
    assert send(client,h,cid,action="compare",job_ids=[jid]).status_code==400
    c=read(client,h,cid)
    assert c["active_run_id"] is None and c["messages"]==[] and c["resources"]==[]
    assert send(client,h,cid).status_code==202


def test_stop_queued_is_durable_retry_no_duplicate_user_message(client,auth,fake_llm):
    h=auth()
    cid=conversation(client,h)
    r=send(client,h,cid)
    rid=r.json()["id"]
    assert client.post(f"{PREFIX}/runs/{rid}/stop",headers=h).json()["status"]=="cancelled"
    process_run(rid)
    assert not fake_llm.calls
    r=client.post(f"{PREFIX}/runs/{rid}/retry",headers=h)
    assert r.status_code==202
    process_run(r.json()["id"])
    c=read(client,h,cid)
    assert len(c["messages"])==3
    assert sum(m["role"]=="user" for m in c["messages"])==1
    assert c["messages"][-1]["status"]=="completed"


def test_provider_failure_keeps_partial_then_retry(client,auth,fake_llm,monkeypatch):
    h=auth()
    cid=conversation(client,h)
    def broken(self,messages):
        yield "partial"
        raise RuntimeError("provider disconnected")
    monkeypatch.setattr(fake_llm,"stream_messages",broken)
    r=send(client,h,cid)
    rid=r.json()["id"]
    process_run(rid)
    c=read(client,h,cid)
    assert c["messages"][-1]["content"]=="partial"
    assert c["messages"][-1]["status"]=="failed" and c["active_run_id"] is None
    assert client.post(f"{PREFIX}/runs/{rid}/retry",headers=h).status_code==202


def test_running_cancel_stops_at_checkpoint(client,auth,fake_llm,monkeypatch):
    h=auth()
    cid=conversation(client,h)
    r=send(client,h,cid)
    rid=r.json()["id"]
    def cancel(self,messages):
        yield "first"
        client.post(f"{PREFIX}/runs/{rid}/stop",headers=h)
        yield "last"
    monkeypatch.setattr(fake_llm,"stream_messages",cancel)
    process_run(rid)
    c=read(client,h,cid)
    assert c["messages"][-1]["status"]=="cancelled" and c["active_run_id"] is None


def test_share_is_snapshot_expirable_revocable_and_excludes_sources(client,auth,make_job,fake_llm):
    h=auth()
    cid=conversation(client,h)
    jid=make_job(segments=SEGMENTS)
    r=send(client,h,cid,job_ids=[jid])
    process_run(r.json()["id"])
    r=client.post(f"{PREFIX}/conversations/{cid}/shares",headers=h,json={})
    assert r.status_code==201
    s=r.json()
    token=s["path"].split('/')[-1]
    public=client.get(f"{PREFIX}/shared/{token}")
    assert public.status_code==200
    assert "evidence" not in public.json()["messages"][-1]
    assert jid not in public.text
    assert "no-store" in public.headers["cache-control"]
    next_run=send(client,h,cid,"new message")
    process_run(next_run.json()["id"])
    assert len(client.get(f"{PREFIX}/shared/{token}").json()["messages"])==2
    assert client.delete(f"{PREFIX}/conversations/{cid}/shares/{s['id']}",headers=h).status_code==204
    assert client.get(f"{PREFIX}/shared/{token}").status_code==404
    s=client.post(f"{PREFIX}/conversations/{cid}/shares",headers=h,json={}).json()
    with SessionLocal() as db:
        share=db.get(ConversationShare,s["id"])
        share.expires_at=now()-timedelta(days=1)
        db.commit()
    assert client.get(f"{PREFIX}/shared/{s['path'].split('/')[-1]}").status_code==404


def test_pin_tag_archive_search_pagination(client,auth):
    h=auth()
    ids=[conversation(client,h,title=f"topic {n}") for n in range(4)]
    for cid in ids[:2]:
        assert client.patch(f"{PREFIX}/conversations/{cid}",headers=h,json={"pinned":True,"tags":["RAG"]}).status_code==200
    result=client.get(PREFIX+"/conversations?tag=RAG&limit=1",headers=h).json()
    assert result["total"]==2 and len(result["items"])==1 and result["next_offset"]==1
    assert client.get(PREFIX+"/conversations?pinned=true",headers=h).json()["total"]==2
    client.patch(f"{PREFIX}/conversations/{ids[0]}",headers=h,json={"archived":True})
    assert client.get(PREFIX+"/conversations?archived=true",headers=h).json()["total"]==1
    assert send(client,h,ids[0]).status_code==409
    assert client.get(PREFIX+"/conversations?q=topic%202",headers=h).json()["total"]==1


def test_no_config_does_not_fake_ai_output(client,auth,make_job):
    with SessionLocal() as db:
        db.delete(db.get(AppSetting,"llm.api_key"))
        db.commit()
    h=auth()
    cid=conversation(client,h)
    assert send(client,h,cid).status_code==400
    jid=make_job(segments=SEGMENTS)
    r=send(client,h,cid,job_ids=[jid])
    assert r.status_code==202
    process_run(r.json()["id"])
    assert read(client,h,cid)["messages"][-1]["meta"]["mode"]=="transcript_only"


def test_media_summary_failure_can_use_saved_transcript(client,auth,make_job,fake_llm):
    h=auth()
    cid=conversation(client,h)
    jid=make_job(segments=SEGMENTS,status="failed")
    r=send(client,h,cid,job_ids=[jid])
    process_run(r.json()["id"])
    c=read(client,h,cid)
    assert c["messages"][-1]["status"]=="completed"
    assert c["messages"][-1]["meta"]["warnings"]


def test_unconfigured_or_unconsented_advanced_tools_are_rejected(client,auth,monkeypatch):
    h=auth()
    cid=conversation(client,h)
    assert send(client,h,cid,allow_web=True).status_code==400
    assert send(client,h,cid,allow_visual=True).status_code==400
    assert send(client,h,cid,action="research").status_code==400
    assert send(client,h,cid,action="visual").status_code==400
    assert send(client,h,cid,mode="workspace").status_code==400


def test_stale_lease_releases_slot_without_automatic_paid_retry(client,auth):
    h=auth()
    cid=conversation(client,h)
    r=send(client,h,cid)
    rid=r.json()["id"]
    with SessionLocal() as db:
        run=db.get(ChatRun,rid)
        run.status="running"
        run.lease_id="old"
        run.updated_at=now()-timedelta(hours=1)
        m=db.get(ChatMessage,run.assistant_message_id)
        m.content="kept"
        db.commit()
    recover_stale_runs()
    c=read(client,h,cid)
    assert c["active_run_id"] is None
    assert c["messages"][-1]["content"]=="kept" and c["messages"][-1]["status"]=="failed"


def test_delete_conversation_cascades_chat_but_preserves_video(client,auth,make_job,fake_llm):
    h=auth()
    cid=conversation(client,h)
    jid=make_job(segments=SEGMENTS)
    r=send(client,h,cid,job_ids=[jid])
    process_run(r.json()["id"])
    assert client.delete(f"{PREFIX}/conversations/{cid}",headers=h).status_code==204
    with SessionLocal() as db:
        assert db.get(Job,jid)
        assert db.scalar(select(func.count()).select_from(ChatMessage))==0
        assert db.scalar(select(func.count()).select_from(ChatRun))==0


def test_workspace_roles_revocation_and_resource_sharing(client,auth,make_job,fake_llm):
    alice,bob=auth("alice"),auth("bob")
    w=client.post(PREFIX+"/workspaces",headers=alice,json={"name":"Research","instructions":"Be precise"}).json()["id"]
    assert client.post(f"{PREFIX}/workspaces/{w}/members",headers=alice,json={"username":"bob","role":"viewer"}).status_code==200
    cid=conversation(client,alice,workspace_id=w)
    assert read(client,bob,cid)["can_edit"] is False
    assert send(client,bob,cid).status_code==404
    jid=make_job(owner="alice",segments=SEGMENTS)
    assert client.post(f"{PREFIX}/workspaces/{w}/resources",headers=alice,json={"job_id":jid}).status_code==201
    assert len(client.get(f"{PREFIX}/workspaces/{w}/resources",headers=bob).json())==1
    assert client.post(f"{PREFIX}/videos/{jid}/index",headers=bob).status_code==404
    assert client.post(f"{PREFIX}/workspaces/{w}/members",headers=alice,json={"username":"bob","role":"editor"}).status_code==200
    bc=conversation(client,bob,workspace_id=w)
    r=send(client,bob,bc,mode="workspace")
    assert r.status_code==202,r.text
    process_run(r.json()["id"])
    assert "Be precise" in fake_llm.calls[-1][-1]["content"]
    assert read(client,bob,bc)["messages"][-1]["meta"]["evidence"][0]["job_id"]==jid
    assert client.delete(f"{PREFIX}/workspaces/{w}/members/bob",headers=alice).status_code==204
    assert client.get(f"{PREFIX}/conversations/{bc}",headers=bob).status_code==404
    assert client.get(f"{PREFIX}/runs/{r.json()['id']}",headers=bob).status_code==404


def test_member_cannot_reshare_borrowed_job_to_another_project(client,auth,make_job):
    a,b=auth("alice"),auth("bob")
    jid=make_job(owner="alice",segments=SEGMENTS)
    w=client.post(PREFIX+"/workspaces",headers=a,json={"name":"A"}).json()["id"]
    client.post(f"{PREFIX}/workspaces/{w}/members",headers=a,json={"username":"bob","role":"editor"})
    client.post(f"{PREFIX}/workspaces/{w}/resources",headers=a,json={"job_id":jid})
    w2=client.post(PREFIX+"/workspaces",headers=b,json={"name":"B"}).json()["id"]
    cid=conversation(client,b,workspace_id=w2)
    r=client.post(f"{PREFIX}/conversations/{cid}/resources",headers=b,json={"job_id":jid})
    assert r.status_code==403


def test_admin_user_creation_and_role_required(client,auth):
    payload={"username":"charlie","password":"test-password-123"}
    assert client.post(PREFIX+"/users",headers=auth("alice"),json=payload).status_code==403
    assert client.post(PREFIX+"/users",headers=auth(),json=payload).status_code==201
    assert client.post(PREFIX+"/users",headers=auth(),json=payload).status_code==409
    w=client.post(PREFIX+"/workspaces",headers=auth(),json={"name":"X"}).json()["id"]
    assert client.post(f"{PREFIX}/workspaces/{w}/members",headers=auth(),json={"username":"charlie"}).status_code==422
