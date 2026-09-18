from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import current_user
from app.services.assistant_access import deployment_admin
from app.api.schemas import DouyinSessionStatus
from app.db.models import User
from app.services.douyin_browser_session import qr_path, session_status, start_login

router = APIRouter(dependencies=[Depends(deployment_admin)], prefix="/douyin/session", tags=["douyin-session"])


@router.post("/login", response_model=DouyinSessionStatus, status_code=202)
def login(_: User = Depends(current_user)) -> DouyinSessionStatus:
    return DouyinSessionStatus(**start_login())


@router.get("/status", response_model=DouyinSessionStatus)
def status(_: User = Depends(current_user)) -> DouyinSessionStatus:
    return DouyinSessionStatus(**session_status())


@router.get("/qr")
def qr(_: User = Depends(current_user)) -> FileResponse:
    path = qr_path()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="暂无登录二维码，请先发起连接")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
