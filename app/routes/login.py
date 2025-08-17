from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse

from ..login_service import process_highlight_login
from ..models import LoginRequest, LoginResponse

router = APIRouter()


@router.post("/highlight_login_api", response_model=LoginResponse)
async def highlight_login_api(request: LoginRequest):
    """Highlight 登录 API"""
    result = await process_highlight_login(request.login_link)

    if result['success']:
        return LoginResponse(
            success=True,
            message="登录成功",
            api_key=result['api_key'],
            user_info=result['user_info']
        )
    else:
        return LoginResponse(
            success=False,
            message=f"登录失败: {result['error']}"
        )


@router.get("/highlight_login", response_class=HTMLResponse)
async def highlight_login_page():
    """Highlight 登录页面"""
    return FileResponse("static/login.html")
