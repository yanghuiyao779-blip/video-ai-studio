import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.db.models import Job
from app.db.assistant import VideoChunk, VideoKnowledgeIndex
from app.services.video_knowledge import timed_chunks, normalized_segments, requested_seconds, retrieve, index_video, ensure_lexical_index, invalidate_index, result_for_job
from app.services.assistant_artifacts import structured_artifact
from app.services.assistant_runner import validate_citations
from app.services.setting_store import update_llm_config


def test_timestamp_chunks_do_not_invent_segment_times():
    seg=[{"start":10,"end":20,"text":"x"*150},{"start":40,"end":50,"text":"y"*30}]
    chunks=timed_chunks(seg,64)
    assert all(len(c['text'])<=64 for c in chunks)
    assert all(c['start'] in {10,40} and c['end'] in {20,50} for c in chunks)
    assert ''.join(c['text'].replace('\n','') for c in chunks)=='x'*150+'y'*30
    with pytest.raises(ValueError):
        timed_chunks(seg,2)


@pytest.mark.parametrize('start,end',[(float('nan'),1),(-1,1),(3,2),(0,float('inf'))])
def test_bad_timestamp_rejected(start,end):
    with pytest.raises(ValueError):
        normalized_segments({'transcript':{'segments':[{'start':start,'end':end,'text':'x'}]}})


@pytest.mark.parametrize('question,answer',[('at 08:32',512),('1:02:03',3723),('第8分钟30秒',510),('ordinary question',None)])
def test_time_query(question,answer):
    assert requested_seconds(question)==answer


def test_lexical_chinese_search_source_scope_and_version(make_job):
    segments=[{'start':0,'end':30,'text':'企业知识库检索与索引更新'*160}, {'start':480,'end':520,'text':'八分钟介绍混合检索和关键词匹配'*100}]
    jid=make_job(segments=segments)
    secret=make_job(owner='alice',segments=[{'start':0,'end':1,'text':'PRIVATE'}])
    result=retrieve([jid],'08:10 说了什么')
    assert result['evidence'][0]['start_seconds']==480
    assert all(e['job_id']==jid for e in result['evidence'])
    assert secret not in json.dumps(result)
    oldhash=result['evidence'][0]['transcript_hash']
    with SessionLocal() as db:
        job=db.get(Job,jid)
        p=Path(job.output_dir)/'result.json'
        p.write_text(json.dumps({'transcript':{'segments':[{'start':1,'end':2,'text':'new corrected transcript'}]}}))
        invalidate_index(db,jid)
        db.commit()
    updated=retrieve([jid],'new')
    assert updated['evidence'][0]['transcript_hash']!=oldhash
    assert 'new corrected' in updated['evidence'][0]['excerpt']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(VideoChunk).where(VideoChunk.job_id==jid))==1


def test_index_failure_cannot_fail_media_job(make_job,monkeypatch):
    import app.services.video_knowledge as module
    jid=make_job(segments=[{'start':0,'end':8,'text':'documents and search'}])
    with SessionLocal() as db:
        update_llm_config(db,'custom','https://unit.test/v1','chat','key',.2,None,embedding_model='embedding')
    def broken(*args,**kw):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(module,'embed_texts',broken)
    index_video(jid)
    with SessionLocal() as db:
        assert db.get(Job,jid).status=='completed'
        assert db.get(VideoKnowledgeIndex,jid).status=='degraded'
    assert retrieve([jid],'search')['evidence']


def test_index_of_missing_transcript_is_terminal_not_busy_loop(make_job):
    jid=make_job(segments=None,status='failed')
    with SessionLocal() as db:
        db.add(VideoKnowledgeIndex(job_id=jid))
        db.commit()
    index_video(jid)
    with SessionLocal() as db:
        assert db.get(VideoKnowledgeIndex,jid).status=='failed'


def test_embedding_index_stale_result_never_overwrites_new_transcript(make_job,monkeypatch):
    import app.services.video_knowledge as module
    jid=make_job(segments=[{'start':0,'end':8,'text':'old'}])
    with SessionLocal() as db:
        update_llm_config(db,'custom','https://unit.test/v1','chat','key',.2,None,embedding_model='embedding')
    def edit_during_embedding(config,inputs):
        with SessionLocal() as db:
            job=db.get(Job,jid)
            p=Path(job.output_dir)/'result.json'
            p.write_text(json.dumps({'transcript':{'segments':[{'start':0,'end':8,'text':'new'}]}}))
            invalidate_index(db,jid)
            db.commit()
        ensure_lexical_index(jid)
        return [[.1]*1536 for _ in inputs]
    monkeypatch.setattr(module,'embed_texts',edit_during_embedding)
    index_video(jid)
    with SessionLocal() as db:
        chunks=list(db.scalars(select(VideoChunk).where(VideoChunk.job_id==jid)))
        assert chunks[0].content=='new' and chunks[0].embedding is None
        assert db.get(VideoKnowledgeIndex,jid).status=='lexical_ready'


def test_multivideo_summary_balances_sources_reports_sampling(make_job):
    ids=[make_job(name=f'V{i}',segments=[{'start':n*60,'end':n*60+50,'text':f'video{i} chapter{n} '+('x'*1300)} for n in range(25)]) for i in range(3)]
    r=retrieve(ids,'summary',broad=True,limit=12)
    assert {e['job_id'] for e in r['evidence']}==set(ids)
    assert r['coverage']['sampling'] and r['coverage']['selected_chunks']<=12
    assert r['warnings']


def test_transcript_path_escape_denied(tmp_path):
    path=tmp_path/'output'
    path.mkdir()
    (path/'result.json').write_text('{}')
    job=SimpleNamespace(output_dir=str(path))
    with pytest.raises(ValueError):
        result_for_job(job)


def test_structured_timeline_derives_times_and_rejects_unknown_ids():
    evidence=[{'id':'V1','job_id':'job','start_seconds':123,'end_seconds':145}]
    text,data=structured_artifact('timeline','{"chapters":[{"title":"One","source_id":"V1","start_seconds":999}]}',evidence)
    assert data['chapters'][0]['start_seconds']==123 and '02:03' in text
    with pytest.raises(ValueError):
        structured_artifact('timeline','{"chapters":[{"title":"One","source_id":"V99"}]}',evidence)


def test_mindmap_is_bounded_data_not_html_execution():
    _text,data=structured_artifact('mindmap','{"title":"<script>bad()</script>","children":[]}',[])
    assert data['title']=='<script>bad()</script>'  # UI React escapes it, never innerHTML.
    tree={'title':'root'}
    cursor=tree
    for _ in range(8):
        cursor['children']=[{'title':'deep'}]
        cursor=cursor['children'][0]
    with pytest.raises(ValueError):
        structured_artifact('mindmap',json.dumps(tree),[])


def test_invalid_citations_are_removed_not_fabricated():
    answer,bad=validate_citations('Fact [V1], other [V99], web [W2]',[{'id':'V1'}])
    assert '[V1]' in answer and '[V99]' not in answer and bad==['V99','W2']
