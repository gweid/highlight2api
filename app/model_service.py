from typing import Dict, Any

import httpx
from fastapi import HTTPException

from .config import HIGHLIGHT_BASE_URL, USER_AGENT, TLS_VERIFY

# 模型缓存，格式：{model_name: {"id": str, "name": str, "provider": str, "isFree": bool}}
model_cache: Dict[str, Dict[str, Any]] = {}


async def fetch_models_from_upstream(access_token: str) -> Dict[str, Dict[str, Any]]:
    """从上游获取模型列表"""
    async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=30.0) as client:
        try:
            response = await client.get(
                f"{HIGHLIGHT_BASE_URL}/api/v1/models",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": USER_AGENT,
                },
            )

            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="获取模型列表失败")

            resp_json = response.json()
            if not resp_json.get("success"):
                raise HTTPException(status_code=500, detail="获取模型数据失败")

            # 清空并重新填充缓存
            model_cache.clear()
            for model in resp_json["data"]:
                model_name = model["name"]
                model_cache[model_name] = {
                    "id": model["id"],
                    "name": model["name"],
                    "provider": model["provider"],
                    "isFree": model.get("pricing", {}).get("isFree", False),
                }

            return model_cache

        except httpx.HTTPError as e:
            raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


async def get_models(access_token: str) -> Dict[str, Dict[str, Any]]:
    """获取模型列表（带缓存）"""
    if not model_cache:
        # 缓存为空，从上游获取
        return await fetch_models_from_upstream(access_token)
    return model_cache
