import base64
import json
import time
from typing import Dict, Any, Optional

import httpx
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from loguru import logger

from .config import HIGHLIGHT_BASE_URL, USER_AGENT, TLS_VERIFY

# 存储格式：{rt: {"access_token": str, "expires_at": int}}
access_tokens: Dict[str, Dict[str, Any]] = {}


def parse_api_key(api_key_base64: str) -> Optional[Dict[str, Any]]:
    """解析base64编码的JSON API Key"""
    try:
        decoded_bytes = base64.b64decode(api_key_base64)
        data = json.loads(decoded_bytes)
        return data
    except Exception:
        return None


def parse_jwt_payload(jwt_token: str) -> Optional[Dict[str, Any]]:
    """解析JWT token的payload部分"""
    try:
        # JWT格式：header.payload.signature
        parts = jwt_token.split(".")
        if len(parts) != 3:
            return None

        # 解析payload部分（第二部分）
        payload = parts[1]
        # 补齐base64编码所需的padding
        padding = len(payload) % 4
        if padding:
            payload += "=" * (4 - padding)

        decoded_bytes = base64.urlsafe_b64decode(payload)
        payload_data = json.loads(decoded_bytes)
        return payload_data
    except Exception:
        return None


async def get_user_info_from_token(credentials: HTTPAuthorizationCredentials) -> Dict[str, Any]:
    """从认证令牌中获取用户信息"""
    token = credentials.credentials

    # 尝试解析为base64编码的JSON
    user_info = parse_api_key(token)
    if user_info:
        return user_info

    # 尝试解析为JWT token
    jwt_payload = parse_jwt_payload(token)
    if jwt_payload:
        # 从JWT payload中提取必要信息
        # 这里需要根据实际的JWT结构来调整
        return {
            "rt": jwt_payload.get("rt"),
            "user_id": jwt_payload.get("user_id"),
            "client_uuid": jwt_payload.get("client_uuid"),
            "email": jwt_payload.get("email"),
        }

    raise HTTPException(status_code=401, detail="Invalid authorization token format")


async def refresh_access_token(rt: str) -> str:
    """使用refresh token获取新的access token"""
    logger.debug(f"{rt} 刷新")
    url = f"{HIGHLIGHT_BASE_URL}/api/v1/auth/refresh"
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    json_data = {"refreshToken": rt}

    async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=json_data)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to refresh access token, response: {response.status_code} {response.text}"
                )

            resp_json = response.json()
            if not resp_json.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to refresh access token, response: {response.status_code} {response.text}"
                )

            access_token = resp_json["data"]["accessToken"]
            expires_in = resp_json["data"].get("expiresIn", 3600)  # 默认1小时
            expires_at = int(time.time()) + expires_in - 60  # 提前1分钟过期

            # 更新缓存
            access_tokens[rt] = {"access_token": access_token, "expires_at": expires_at}

            return access_token

        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500, detail=f"HTTP error during token refresh: {str(e)}"
            )


async def get_access_token(rt: str, refresh=False) -> str:
    """获取access token（带缓存）"""
    if refresh:
        return await refresh_access_token(rt)

    current_time = int(time.time())

    # 检查缓存
    if rt in access_tokens:
        token_info = access_tokens[rt]
        if current_time < token_info["expires_at"]:
            return token_info["access_token"]

    # 缓存过期或不存在，刷新token
    return await refresh_access_token(rt)


def get_highlight_headers(access_token: str, identifier: str) -> Dict[str, str]:
    """获取Highlight API请求头"""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Highlight-Identifier": identifier,
    }
