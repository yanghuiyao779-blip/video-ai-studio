import json
import shutil
import subprocess
from types import SimpleNamespace
import httpx
import pytest
from app.services.llm import OpenAICompatibleLLM, LLMEmptyContentError
from app.services.setting_store import LLMConfig
from app.services.embeddings import embed_texts
from app.services.assistant_tools import capture_video_frames, search_web, plan_tools, inspect_frames
from app.core.config import get_settings


def config():
    return LLMConfig('custom','https://unit.test/v1','model','synthetic-key',.2,None,'embedding')


def with_transport(monkeypatch, handler, module):
    original=httpx.Client
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))


def test_real_sse_parser_keeps_unicode_and_ignores_reasoning(monkeypatch):
    import app.services.llm as module
    def handler(request):
        data=json.loads(request.content)
        assert data['stream'] is True
        frames=[{'choices':[{'delta':{'reasoning_content':'HIDDEN'}}]}, {'choices':[{'delta':{'content':'你'}}]}, {'choices':[{'delta':{'content':'好'},'finish_reason':'stop'}]}]
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=(''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n').encode())
    with_transport(monkeypatch,handler,module)
    with OpenAICompatibleLLM(config()) as client:
        assert ''.join(client.stream_messages([{'role':'user','content':'hi'}]))=='你好'


@pytest.mark.parametrize('stream,error',[
 ('data: {bad}\n\n',RuntimeError),
 ('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',RuntimeError),
 ('data: {"choices":[{"delta":{"reasoning_content":"hidden"},"finish_reason":"stop"}]}\n\n',LLMEmptyContentError),
 ('data: {"choices":[{"delta":{"content":"partial"},"finish_reason":"length"}]}\n\n',RuntimeError),
])
def test_bad_sse_is_not_reported_as_completed(monkeypatch,stream,error):
    import app.services.llm as module
    with_transport(monkeypatch,lambda req:httpx.Response(200,headers={'content-type':'text/event-stream'},content=stream),module)
    with OpenAICompatibleLLM(config()) as client:
        with pytest.raises(error):
            list(client.stream_messages([]))


def test_non_streaming_compatible_provider_fallback(monkeypatch):
    import app.services.llm as module
    with_transport(monkeypatch,lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'Fallback'}}]}),module)
    with OpenAICompatibleLLM(config()) as client:
        assert list(client.stream_messages([]))==['Fallback']


def test_embeddings_validate_order_dimension_and_batching(monkeypatch):
    import app.services.embeddings as module
    requests=[]
    def handler(req):
        data=json.loads(req.content)
        requests.append(data)
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[float(i)]*1536} for i in reversed(range(len(data['input'])))]})
    with_transport(monkeypatch,handler,module)
    result=embed_texts(config(),['x']*35)
    assert len(requests)==2 and len(requests[0]['input'])==32
    assert result[1][0]==1. and len(result)==35


@pytest.mark.parametrize('data',[
 [{'index':0,'embedding':[1]}],
 [{'index':3,'embedding':[1]*1536}],
 [],
])
def test_invalid_embeddings_rejected(monkeypatch,data):
    import app.services.embeddings as module
    with_transport(monkeypatch,lambda req:httpx.Response(200,json={'data':data}),module)
    with pytest.raises(RuntimeError):
        embed_texts(config(),['x'])


def test_search_only_sends_query_and_filters_bad_links(monkeypatch):
    import app.services.assistant_tools as module
    monkeypatch.setattr(get_settings(),'assistant_web_api_key','unit-key')
    sent=[]
    def post(url,**kwargs):
        sent.append((url,kwargs))
        return httpx.Response(200,json={'results':[{'url':'javascript:alert(1)','content':'bad'},{'url':'https://example.org/article','title':'Source','content':'Search excerpt'}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(module.httpx,'post',post)
    r=search_web('topic')
    assert len(r)==1 and r[0]['id']=='W1'
    assert sent[0][1]['json']['query']=='topic'
    assert not sent[0][1]['json']['include_raw_content']
    assert 'transcript' not in sent[0][1]['json']


def test_agent_cannot_create_arbitrary_tool_calls(monkeypatch):
    import app.services.assistant_tools as module
    class BadPlanner:
        def __init__(self,c):
            pass
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def complete(self,*args):
            return SimpleNamespace(content='{"steps":[{"tool":"shell","query":"rm -rf /"}]}')
    monkeypatch.setattr(module,'OpenAICompatibleLLM',BadPlanner)
    steps=plan_tools(config(),'query',True,False,False)
    assert all(s.tool in {'search_video','summarize_video'} for s in steps)
    assert not plan_tools(config(),'query',False,False,False)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg not installed')
def test_actual_ffmpeg_sampled_frames_are_bounded(tmp_path,make_job,monkeypatch):
    jid=make_job(segments=[{'start':0,'end':2,'text':'test'}])
    video=tmp_path/'clip.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','color=size=160x90:rate=5','-t','2','-pix_fmt','yuv420p',str(video)],check=True,timeout=15)
    monkeypatch.setattr(get_settings(),'assistant_capture_frames',True)
    monkeypatch.setattr(get_settings(),'assistant_max_frames',3)
    frames=capture_video_frames(jid,video)
    assert len(frames)==3 and all(0<=f['seconds']<2 for f in frames)
    root=get_settings().data_dir/'jobs'/jid/'frames'
    assert all((root/f['file']).is_file() for f in frames)


def test_visual_requires_existing_frames_not_imagined_video(make_job,monkeypatch):
    jid=make_job(segments=[{'start':0,'end':1,'text':'x'}])
    monkeypatch.setattr(get_settings(),'assistant_vision_model','vision')
    with pytest.raises(ValueError,match='ASSISTANT_CAPTURE_FRAMES'):
        inspect_frames([jid],'question',config())
