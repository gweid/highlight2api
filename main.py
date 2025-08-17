"""Highlight AI API Proxy - 主应用入口"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes.api import router as api_router
from app.routes.login import router as login_router

app = FastAPI(title="Highlight AI API Proxy", version="1.0.0")

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册路由
app.include_router(api_router)
app.include_router(login_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=3003,
        reload=False,
        log_level="info",
    )
