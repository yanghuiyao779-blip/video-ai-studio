from __future__ import annotations

from pathlib import Path

from yt_dlp.utils import DownloadError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.services.assistant_access import deployment_admin
from app.api.schemas import (
    CreatorAnalysisResponse, CreatorCreate, CreatorPreviewResponse, CreatorResponse, CreatorSkillResponse,
    CreatorVideoImport, CreatorVideoResponse, CreatorAskRequest, CreatorDashboardResponse,
    CreatorOverviewResponse, CreatorResearchRunResponse, CreatorResearchStart, CreatorResearchControls, CreatorSyncRunResponse,
)
from app.core.config import get_settings
from app.db.models import Creator, CreatorAnalysisRun, CreatorResearchRun, CreatorSkillVersion, CreatorSyncRun, CreatorVideo, Job, User, VideoInsight
from app.db.session import get_db
from app.services.creator_intelligence import (
    ask_creator, build_skill, create_creator, creator_dashboard, creator_overview, create_research_run,
    dispatch_creator_jobs, import_video_urls, pause_creator_research, update_research_controls, _json, _serialize_creator, _serialize_research_run,
)
from app.services.douyin_resolver import resolve_douyin_creator

router = APIRouter(dependencies=[Depends(deployment_admin)], prefix="/creators", tags=["creators"])


def _creator_or_404(db: Session, creator_id: str) -> Creator:
    creator = db.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(status_code=404, detail="博主不存在")
    return creator


def _enqueue(task_name: str, *args: object) -> None:
    if get_settings().queue_mode != "celery":
        return
    from app.workers.celery_app import (
        advance_creator_research_task, analyze_video_insight_task, build_creator_profile_task, dispatch_creator_jobs_task,
        index_creator_corpus_task, start_creator_research_task, sync_creator_task,
    )
    tasks = {"sync": sync_creator_task, "dispatch": dispatch_creator_jobs_task, "insight": analyze_video_insight_task,
             "profile": build_creator_profile_task, "index": index_creator_corpus_task,
             "research_start": start_creator_research_task, "research_advance": advance_creator_research_task}
    tasks[task_name].delay(*args)


def _analysis_response(run: CreatorAnalysisRun) -> CreatorAnalysisResponse:
    return CreatorAnalysisResponse(
        id=run.id, creator_id=run.creator_id, status=run.status, prompt_version=run.prompt_version,
        input_snapshot=_json(run.input_snapshot_json, {}), profile=_json(run.profile_json, None),
        error_message=run.error_message, created_at=run.created_at, completed_at=run.completed_at,
    )


@router.post("", response_model=CreatorResponse, status_code=status.HTTP_201_CREATED)
def create(payload: CreatorCreate, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorResponse:
    try:
        creator = create_creator(db, str(payload.profile_url), payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"无法创建博主：{str(exc)[:240]}") from exc
    return CreatorResponse(**_serialize_creator(db, creator))


@router.post("/preview", response_model=CreatorPreviewResponse)
def preview(payload: CreatorCreate, _: User = Depends(current_user)) -> CreatorPreviewResponse:
    try:
        identity = resolve_douyin_creator(str(payload.profile_url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DownloadError as exc:
        raise HTTPException(status_code=422, detail="该抖音链接无法解析为作者；请使用视频页、主页或先连接抖音账号后重试") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        # Browser navigation and upstream anti-bot failures are expected
        # integration errors, never an internal-server error for the user.
        raise HTTPException(status_code=422, detail=f"无法识别该抖音链接：{str(exc)[:240]}") from exc
    return CreatorPreviewResponse(
        platform=identity.platform, source_url=identity.source_url, canonical_url=identity.canonical_url,
        sec_user_id=identity.sec_user_id, uid=identity.uid, nickname=identity.nickname,
        resolution_method=identity.resolution_method, source_video_id=identity.source_video_id,
    )


@router.get("/dashboard", response_model=CreatorDashboardResponse)
def dashboard(_: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorDashboardResponse:
    return CreatorDashboardResponse(**creator_dashboard(db))


@router.get("", response_model=list[CreatorResponse])
def list_creators(_: User = Depends(current_user), db: Session = Depends(get_db)) -> list[CreatorResponse]:
    creators = list(db.scalars(select(Creator).order_by(desc(Creator.updated_at))))
    return [CreatorResponse(**_serialize_creator(db, creator)) for creator in creators]


@router.get("/{creator_id}/overview", response_model=CreatorOverviewResponse)
def overview(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorOverviewResponse:
    return CreatorOverviewResponse(**creator_overview(db, _creator_or_404(db, creator_id)))


@router.get("/{creator_id}/sync-runs", response_model=list[CreatorSyncRunResponse])
def sync_runs(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> list[CreatorSyncRunResponse]:
    _creator_or_404(db, creator_id)
    rows = db.scalars(select(CreatorSyncRun).where(CreatorSyncRun.creator_id == creator_id).order_by(desc(CreatorSyncRun.created_at))).all()
    return [CreatorSyncRunResponse(id=row.id, status=row.status, discovered_count=row.discovered_count, created_count=row.created_count, error_message=row.error_message, created_at=row.created_at, completed_at=row.completed_at) for row in rows]


@router.get("/{creator_id}", response_model=CreatorResponse)
def detail(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorResponse:
    return CreatorResponse(**_serialize_creator(db, _creator_or_404(db, creator_id)))


@router.post("/{creator_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def sync(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    creator = _creator_or_404(db, creator_id)
    run = CreatorSyncRun(creator_id=creator.id, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    _enqueue("sync", run.id)
    return {"id": run.id, "status": run.status}


@router.post("/{creator_id}/research/start", response_model=CreatorResearchRunResponse, status_code=status.HTTP_202_ACCEPTED)
def start_research(creator_id: str, payload: CreatorResearchStart, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorResearchRunResponse:
    run = create_research_run(
        db, _creator_or_404(db, creator_id), payload.batch_size, payload.auto_continue,
        payload.target_video_limit, payload.failure_threshold_percent,
    )
    if run.status == "queued":
        if get_settings().queue_mode == "celery":
            _enqueue("research_start", run.id)
        else:
            from app.services.creator_intelligence import start_creator_research
            start_creator_research(run.id)
        db.refresh(run)
    return CreatorResearchRunResponse(**_serialize_research_run(run))


@router.patch("/{creator_id}/research/{research_run_id}", response_model=CreatorResearchRunResponse)
def update_research(
    creator_id: str,
    research_run_id: str,
    payload: CreatorResearchControls,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CreatorResearchRunResponse:
    _creator_or_404(db, creator_id)
    run = db.get(CreatorResearchRun, research_run_id)
    if run is None or run.creator_id != creator_id:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    try:
        run = update_research_controls(
            db, run,
            batch_size=payload.batch_size,
            auto_continue=payload.auto_continue,
            target_video_limit=payload.target_video_limit,
            failure_threshold_percent=payload.failure_threshold_percent,
            clear_target_limit="target_video_limit" in payload.model_fields_set and payload.target_video_limit is None,
            clear_failure_threshold="failure_threshold_percent" in payload.model_fields_set and payload.failure_threshold_percent is None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run.auto_continue and run.status in {"ready_to_process", "transcribing", "analyzing", "profiling"}:
        _enqueue("research_advance", run.id)
    return CreatorResearchRunResponse(**_serialize_research_run(run))


@router.post("/{creator_id}/research/continue", response_model=CreatorResearchRunResponse, status_code=status.HTTP_202_ACCEPTED)
def continue_research(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorResearchRunResponse:
    _creator_or_404(db, creator_id)
    run = db.scalar(select(CreatorResearchRun).where(
        CreatorResearchRun.creator_id == creator_id,
        CreatorResearchRun.status.in_({"ready_to_process", "paused", "transcribing", "analyzing", "profiling"}),
    ).order_by(desc(CreatorResearchRun.created_at)))
    if run is None:
        raise HTTPException(status_code=409, detail="没有可继续的研究任务，请先开始研究")
    if run.status == "paused":
        run.status = "ready_to_process"
        db.commit()
        db.refresh(run)
    if get_settings().queue_mode == "celery":
        _enqueue("research_advance", run.id)
    else:
        from app.services.creator_intelligence import advance_creator_research
        advance_creator_research(run.id)
    return CreatorResearchRunResponse(**_serialize_research_run(run))


@router.post("/{creator_id}/research/{research_run_id}/pause", response_model=CreatorResearchRunResponse)
def pause_research(creator_id: str, research_run_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorResearchRunResponse:
    _creator_or_404(db, creator_id)
    run = db.get(CreatorResearchRun, research_run_id)
    if run is None or run.creator_id != creator_id:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return CreatorResearchRunResponse(**_serialize_research_run(pause_creator_research(db, research_run_id)))


@router.post("/{creator_id}/videos/import", status_code=status.HTTP_201_CREATED)
def import_videos(creator_id: str, payload: CreatorVideoImport, _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    creator = _creator_or_404(db, creator_id)
    try:
        count = import_video_urls(db, creator, [str(url) for url in payload.urls])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"added": count}


@router.get("/{creator_id}/videos", response_model=list[CreatorVideoResponse])
def list_videos(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> list[CreatorVideoResponse]:
    _creator_or_404(db, creator_id)
    videos = list(db.scalars(select(CreatorVideo).where(CreatorVideo.creator_id == creator_id).order_by(desc(CreatorVideo.created_at))))
    result = []
    for video in videos:
        job = db.get(Job, video.job_id) if video.job_id else None
        insight = db.scalar(select(VideoInsight).where(VideoInsight.creator_video_id == video.id).order_by(desc(VideoInsight.created_at)))
        result.append(CreatorVideoResponse(id=video.id, video_url=video.video_url, title=video.title, platform_video_id=video.platform_video_id, duration=video.duration, job_id=video.job_id, job_status=job.status if job else None, ingest_status=video.ingest_status, insight_status=insight.status if insight else None))
    return result


@router.post("/{creator_id}/dispatch", status_code=status.HTTP_202_ACCEPTED)
def dispatch(creator_id: str, limit: int = Query(default=3, ge=1, le=10), _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _creator_or_404(db, creator_id)
    if get_settings().queue_mode == "celery":
        _enqueue("dispatch", creator_id, limit)
        return {"status": "queued", "limit": limit}
    return {"status": "created", "count": dispatch_creator_jobs(creator_id, limit)}


@router.post("/{creator_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
def analyze(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _creator_or_404(db, creator_id)
    videos = list(db.scalars(select(CreatorVideo).join(Job, CreatorVideo.job_id == Job.id).where(CreatorVideo.creator_id == creator_id, Job.status == "completed")))
    for video in videos:
        if video.ingest_status != "analyzed":
            video.ingest_status = "transcribed"
        _enqueue("insight", video.id)
    db.commit()
    return {"status": "queued", "video_count": len(videos)}


@router.post("/{creator_id}/analysis-runs", response_model=CreatorAnalysisResponse, status_code=status.HTTP_202_ACCEPTED)
def create_analysis(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorAnalysisResponse:
    _creator_or_404(db, creator_id)
    completed = db.scalar(select(VideoInsight).join(CreatorVideo).where(CreatorVideo.creator_id == creator_id, VideoInsight.status == "completed").limit(1))
    if completed is None:
        raise HTTPException(status_code=409, detail="尚无已完成的 Video Insight，请先完成文字稿与认知提取")
    run = CreatorAnalysisRun(creator_id=creator_id, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    _enqueue("profile", run.id)
    return _analysis_response(run)


@router.get("/{creator_id}/analysis-runs", response_model=list[CreatorAnalysisResponse])
def analysis_runs(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> list[CreatorAnalysisResponse]:
    _creator_or_404(db, creator_id)
    return [_analysis_response(run) for run in db.scalars(select(CreatorAnalysisRun).where(CreatorAnalysisRun.creator_id == creator_id).order_by(desc(CreatorAnalysisRun.created_at)))]


@router.post("/{creator_id}/skills", response_model=CreatorSkillResponse, status_code=status.HTTP_201_CREATED)
def create_skill(creator_id: str, analysis_run_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> CreatorSkillResponse:
    _creator_or_404(db, creator_id)
    run = db.get(CreatorAnalysisRun, analysis_run_id)
    if run is None or run.creator_id != creator_id:
        raise HTTPException(status_code=404, detail="认知模型不存在")
    try:
        skill = build_skill(db, run)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CreatorSkillResponse(id=skill.id, creator_id=skill.creator_id, analysis_run_id=skill.analysis_run_id, version=skill.version, status=skill.status, created_at=skill.created_at, download_url=f"/api/creators/{creator_id}/skills/{skill.id}/download")


@router.post("/{creator_id}/index", status_code=status.HTTP_202_ACCEPTED)
def index(creator_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _creator_or_404(db, creator_id)
    _enqueue("index", creator_id)
    return {"status": "queued"}


@router.post("/{creator_id}/ask")
def ask(creator_id: str, payload: CreatorAskRequest, _: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    _creator_or_404(db, creator_id)
    try:
        return ask_creator(creator_id, payload.question, payload.top_k)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)[:1000]) from exc


@router.get("/{creator_id}/skills/{skill_id}/download")
def download_skill(creator_id: str, skill_id: str, _: User = Depends(current_user), db: Session = Depends(get_db)):
    skill = db.get(CreatorSkillVersion, skill_id)
    if skill is None or skill.creator_id != creator_id or not skill.artifact_dir:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    allowed = (get_settings().data_dir / "creators").resolve()
    path = (Path(skill.artifact_dir) / "SKILL.md").resolve()
    if allowed not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Skill 文件不存在")
    return FileResponse(path, filename=f"creator-skill-v{skill.version}.md")
