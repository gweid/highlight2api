import asyncio
import base64
import hashlib
from typing import Dict, Any, List, Tuple, Union

import httpx
from fastapi import HTTPException
from filetype import filetype
from loguru import logger

from .config import HIGHLIGHT_BASE_URL, USER_AGENT, TLS_VERIFY
from .models import Message

# 缓存文件上传信息，结构: { sha256: {"fileName": str, "fileId": str} }
file_upload_cache: Dict[str, Dict[str, str]] = {}


async def download_image(url: str) -> bytes:
    """下载图片数据（bytes）"""
    async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def is_base64_image(data: str) -> Tuple[bool, Union[bytes, None]]:
    """判断是否为base64图片字符串，是则返回(真，解码后的bytes)"""
    if data.startswith("data:image/"):
        try:
            _, base64_data = data.split(",", 1)
            decoded = base64.b64decode(base64_data)
            return True, decoded
        except Exception:
            return False, None
    return False, None


def detect_image_type_and_extension(image_bytes: bytes) -> tuple[str, str]:
    kind = filetype.guess(image_bytes)
    if kind is None or not kind.mime.startswith("image/"):
        raise ValueError("无法识别或不是图片格式")
    return kind.mime, kind.extension


async def prepare_file_upload(
        access_token: str, file_name: str, mime_type: str, file_size: int
) -> Dict[str, Any]:
    """调用文件准备接口，申请上传链接"""
    url = f"{HIGHLIGHT_BASE_URL}/api/v1/files/prepare"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    json_data = {"name": file_name, "type": mime_type, "size": file_size}
    async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=30.0) as client:
        resp = await client.post(url, headers=headers, json=json_data)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success") or "data" not in data:
            raise ValueError("文件准备接口返回失败")

        logger.debug(f'{file_size}{data}')
        return data["data"]


async def upload_file_to_url(upload_url: str, file_bytes: bytes, access_token: str) -> None:
    """PUT 请求上传文件二进制数据"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/octet-stream",
        "User-Agent": USER_AGENT,
    }
    async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=60.0) as client:
        resp = await client.put(upload_url, content=file_bytes, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise ValueError(f"上传文件失败 {resp.text}")


async def upload_single_image(
        access_token: str, image_data: str
) -> Dict[str, str]:
    """
    上传单张图片，支持base64和URL。
    返回: {"fileName": "...", "fileId": "..."}
    """
    # 先判断是否base64图片
    is_base64, image_bytes = is_base64_image(image_data)
    if not is_base64:
        # 否则按URL下载
        try:
            image_bytes = await download_image(image_data)
        except Exception as e:
            logger.error(f"下载图片失败：{e}")
            raise
    # 计算文件哈希用作缓存key
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    if sha256 in file_upload_cache:
        # 缓存命中，直接返回
        return file_upload_cache[sha256]
    # 探测图片类型及扩展名
    try:
        mime_type, ext = detect_image_type_and_extension(image_bytes)
    except Exception as e:
        logger.error(f"解析图片类型失败：{e}")
        raise HTTPException(status_code=400, detail=f"图片格式不支持：{str(e)}")
    file_name = f"image.{ext}"
    file_size = len(image_bytes)
    # 准备上传
    upload_info = await prepare_file_upload(access_token, file_name, mime_type, file_size)
    # 上传文件内容
    await upload_file_to_url(upload_info["uploadUrl"], image_bytes, access_token)
    result = {"fileName": file_name, "fileId": upload_info["id"]}
    # 缓存结果
    file_upload_cache[sha256] = result
    return result


async def messages_image_upload(messages: List[Message], access_token: str) -> List[Dict[str, str]]:
    """
    遍历消息，上传所有图片，返回文件名和文件ID列表
    每个元素示例：{"fileName": "...", "fileId": "..."}
    """
    results = []
    # 收集所有图片url/base64
    images: List[str] = []
    for message in messages:
        if message.content and isinstance(message.content, list):
            for content_item in message.content:
                if content_item.type == "image_url" and content_item.image_url:
                    url = content_item.image_url.get("url")
                    if url:
                        images.append(url)

    if not images:
        return results

    # 并行上传所有图片
    # 为节省资源，可以用信号量限制并发数，比如最多5个并发
    semaphore = asyncio.Semaphore(5)

    async def upload_wrapper(_url: str):
        async with semaphore:
            try:
                return await upload_single_image(access_token, _url)
            except Exception as e:
                logger.exception(f"上传图片失败: {_url}", e)
                return None

    upload_tasks = [upload_wrapper(url) for url in images]
    upload_results = await asyncio.gather(*upload_tasks)
    for r in upload_results:
        if r and r["fileId"]:
            results.append(r)
    results.reverse()
    return results
