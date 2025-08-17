import json
import time
import uuid
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from .auth import get_access_token, get_highlight_headers
from .config import HIGHLIGHT_BASE_URL, TLS_VERIFY
from .models import ChatCompletionResponse, Choice, Usage
from .retry_utils import retry_async, should_retry_http_error, should_retry_empty_response


async def parse_sse_line(line: str) -> Optional[str]:
    """解析SSE数据行"""
    line = line.strip()
    if line.startswith("data: "):
        return line[6:]  # 去掉 'data: ' 前缀
    return None


async def stream_generator(
        highlight_data: Dict[str, Any], access_token: str, identifier: str, model: str, rt: str
) -> AsyncGenerator[Dict[str, Any], None]:
    """生成流式响应"""
    response_id = f"chatcmpl-{str(uuid.uuid4())}"
    created = int(time.time())
    
    max_attempts = 3
    current_delay = 1.0
    backoff_factor = 2.0

    for attempt in range(max_attempts):
        try:
            logger.info(f"Stream attempt {attempt + 1}/{max_attempts} for model: {model}")
            
            # 使用httpx的流式请求
            headers = get_highlight_headers(access_token, identifier)
            timeout = httpx.Timeout(120.0, connect=30.0)  # 增加超时时间
            
            async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=timeout) as client:
                async with client.stream(
                        "POST",
                        HIGHLIGHT_BASE_URL + "/api/v1/chat",
                        headers=headers,
                        json=highlight_data,
                ) as response:
                    logger.info(f"Highlight API response status: {response.status_code}")
                    
                    if response.status_code == 401:
                        if attempt < max_attempts - 1:
                            logger.warning("Access token expired, refreshing...")
                            access_token = await get_access_token(rt, True)
                            await asyncio.sleep(current_delay)
                            current_delay *= backoff_factor
                            continue
                        else:
                            error_data = {
                                "error": {
                                    "message": "Authentication failed after token refresh",
                                    "type": "auth_error",
                                }
                            }
                            yield {"event": "error", "data": json.dumps(error_data)}
                            return
                    
                    if response.status_code != 200:
                        error_content = await response.aread()
                        logger.error(f"Highlight API error: {response.status_code} - {error_content}")
                        
                        # 如果是5xx错误，可以重试
                        if 500 <= response.status_code < 600 and attempt < max_attempts - 1:
                            logger.info(f"Retrying due to server error: {response.status_code}")
                            await asyncio.sleep(current_delay)
                            current_delay *= backoff_factor
                            continue
                        
                        error_data = {
                            "error": {
                                "message": f"Highlight API returned status code {response.status_code}",
                                "type": "api_error",
                            }
                        }
                        yield {"event": "error", "data": json.dumps(error_data)}
                        return

                    # 发送初始消息
                    initial_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant"},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield {"event": "data", "data": json.dumps(initial_chunk)}

                    # 处理流式响应
                    buffer = ""
                    has_content = False
                    content_received = False
                    
                    try:
                        async for chunk in response.aiter_bytes():
                            if chunk:
                                # 解码字节数据
                                try:
                                    chunk_text = chunk.decode("utf-8")
                                except UnicodeDecodeError:
                                    chunk_text = chunk.decode("utf-8", errors="ignore")

                                buffer += chunk_text

                                # 按行处理数据
                                while "\n" in buffer:
                                    line, buffer = buffer.split("\n", 1)

                                    # 解析SSE行
                                    data = await parse_sse_line(line)
                                    if data and data.strip():
                                        try:
                                            event_data = json.loads(data)
                                            if event_data.get("type") == "text":
                                                content = event_data.get("content", "")
                                                if content:
                                                    chunk_data = {
                                                        "id": response_id,
                                                        "object": "chat.completion.chunk",
                                                        "created": created,
                                                        "model": model,
                                                        "choices": [
                                                            {
                                                                "index": 0,
                                                                "delta": {"content": content},
                                                                "finish_reason": None,
                                                            }
                                                        ],
                                                    }
                                                    yield {"data": json.dumps(chunk_data)}
                                                    has_content = True
                                                    content_received = True
                                            elif event_data.get("type") == "toolUse":
                                                tool_name = event_data.get("name", "")
                                                tool_id = event_data.get("toolId", "")
                                                tool_input = event_data.get("input", "")
                                                if tool_name:
                                                    chunk_data = {
                                                        "id": response_id,
                                                        "object": "chat.completion.chunk",
                                                        "created": created,
                                                        "model": model,
                                                        "choices": [
                                                            {
                                                                "index": 0,
                                                                "delta": {
                                                                    "tool_calls": [
                                                                        {
                                                                            "index": 0,
                                                                            "id": tool_id,
                                                                            "type": "function",
                                                                            "function": {
                                                                                "name": tool_name,
                                                                                "arguments": tool_input,
                                                                            },
                                                                        }
                                                                    ]
                                                                },
                                                                "finish_reason": None,
                                                            }
                                                        ],
                                                    }
                                                    yield {"data": json.dumps(chunk_data)}
                                                    has_content = True
                                                    content_received = True
                                        except json.JSONDecodeError:
                                            # 忽略无效的JSON数据
                                            continue
                    except Exception as e:
                        logger.error(f"Error during stream processing: {str(e)}")
                        if attempt < max_attempts - 1:
                            logger.info("Retrying due to stream processing error")
                            await asyncio.sleep(current_delay)
                            current_delay *= backoff_factor
                            continue
                        else:
                            error_data = {
                                "error": {
                                    "message": f"Stream processing error: {str(e)}",
                                    "type": "stream_error",
                                }
                            }
                            yield {"event": "error", "data": json.dumps(error_data)}
                            return

                    # 检查是否收到了任何内容
                    if not content_received:
                        logger.warning("No content received in stream response")
                        if attempt < max_attempts - 1:
                            logger.info("Retrying due to empty response")
                            await asyncio.sleep(current_delay)
                            current_delay *= backoff_factor
                            continue
                        else:
                            # 即使没有内容，也要发送完成消息
                            logger.warning("Sending completion message despite empty content")

                    # 发送完成消息
                    final_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                    yield {"data": json.dumps(final_chunk)}
                    yield {"data": "[DONE]"}
                    return

        except httpx.HTTPError as e:
            logger.error(f"HTTP error in stream_generator: {str(e)}")
            if attempt < max_attempts - 1:
                logger.info("Retrying due to HTTP error")
                await asyncio.sleep(current_delay)
                current_delay *= backoff_factor
                continue
            else:
                error_data = {
                    "error": {"message": f"HTTP error: {str(e)}", "type": "http_error"}
                }
                yield {"event": "error", "data": json.dumps(error_data)}
                return
        except Exception as e:
            logger.error(f"Unexpected error in stream_generator: {str(e)}")
            if attempt < max_attempts - 1:
                logger.info("Retrying due to unexpected error")
                await asyncio.sleep(current_delay)
                current_delay *= backoff_factor
                continue
            else:
                error_data = {
                    "error": {"message": str(e), "type": "server_error"}
                }
                yield {"event": "error", "data": json.dumps(error_data)}
                return


@retry_async(
    max_attempts=3,
    delay=1.0,
    backoff_factor=2.0,
    exceptions=(httpx.HTTPError, ValueError, json.JSONDecodeError),
    retry_condition=lambda e: should_retry_http_error(e) or should_retry_empty_response(e)
)
async def _make_highlight_request(
    highlight_data: Dict[str, Any],
    access_token: str,
    identifier: str,
    rt: str
) -> tuple:
    """向 Highlight API 发送请求并返回响应数据"""
    headers = get_highlight_headers(access_token, identifier)
    timeout = httpx.Timeout(120.0, connect=30.0)  # 增加超时时间
    
    logger.info(f"Making request to Highlight API with model: {highlight_data.get('modelId')}")
    
    async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=timeout) as client:
        async with client.stream(
            "POST",
            HIGHLIGHT_BASE_URL + "/api/v1/chat",
            headers=headers,
            json=highlight_data,
        ) as response:
            logger.info(f"Highlight API response status: {response.status_code}")
            
            if response.status_code == 401:
                logger.warning("Access token expired, refreshing...")
                access_token = await get_access_token(rt, True)
                headers = get_highlight_headers(access_token, identifier)
                # 重新发送请求
                async with client.stream(
                    "POST",
                    HIGHLIGHT_BASE_URL + "/api/v1/chat",
                    headers=headers,
                    json=highlight_data,
                ) as new_response:
                    if new_response.status_code != 200:
                        raise httpx.HTTPStatusError(
                            f"Highlight API returned status code {new_response.status_code}",
                            request=new_response.request,
                            response=new_response
                        )
                    response = new_response

            if response.status_code != 200:
                raise httpx.HTTPStatusError(
                    f"Highlight API returned status code {response.status_code}",
                    request=response.request,
                    response=response
                )

            # 收集完整响应
            full_response = ""
            tool_calls = []
            buffer = ""
            has_content = False

            async for chunk in response.aiter_bytes():
                if chunk:
                    # 解码字节数据
                    try:
                        chunk_text = chunk.decode("utf-8")
                    except UnicodeDecodeError:
                        chunk_text = chunk.decode("utf-8", errors="ignore")

                    buffer += chunk_text

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        data = await parse_sse_line(line)
                        if data and data.strip():
                            try:
                                event_data = json.loads(data)
                                if event_data.get("type") == "text":
                                    content = event_data.get("content", "")
                                    if content:
                                        full_response += content
                                        has_content = True
                                elif event_data.get("type") == "toolUse":
                                    tool_name = event_data.get("name", "")
                                    tool_id = event_data.get("toolId", "")
                                    tool_input = event_data.get("input", "")
                                    if tool_name:
                                        tool_calls.append({
                                            "id": tool_id,
                                            "type": "function",
                                            "function": {
                                                "name": tool_name,
                                                "arguments": tool_input,
                                            }
                                        })
                                        has_content = True
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse JSON: {e}")
                                continue

            # 检查是否有任何内容
            if not has_content:
                logger.warning("Highlight API returned empty response")
                raise ValueError("Empty response from Highlight API")

            return full_response, tool_calls


async def non_stream_response(
        highlight_data: Dict[str, Any], access_token: str, identifier: str, model: str, rt: str
) -> JSONResponse:  # type: ignore
    """处理非流式响应"""
    try:
        # 使用重试机制发送请求
        full_response, tool_calls = await _make_highlight_request(
            highlight_data, access_token, identifier, rt
        )
        
        logger.info(f"Successfully received response: {len(full_response)} chars, {len(tool_calls)} tool calls")

        # 创建 OpenAI 格式的响应
        response_id = f"chatcmpl-{str(uuid.uuid4())}"
        created = int(time.time())

        # 构建消息内容
        message_content: Dict[str, any] = {"role": "assistant"}
        if full_response:
            message_content["content"] = full_response
        if tool_calls:
            message_content["tool_calls"] = tool_calls

        response_data = ChatCompletionResponse(
            id=response_id,
            object="chat.completion",
            created=created,
            model=model,
            choices=[
                Choice(
                    index=0,
                    message=message_content,
                    finish_reason="stop",
                )
            ],
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )
        return JSONResponse(content=response_data.model_dump())

    except httpx.HTTPError as e:
        logger.error(f"HTTP error in non_stream_response: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {"message": f"HTTP error: {str(e)}", "type": "http_error"}
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in non_stream_response: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={"error": {"message": str(e), "type": "server_error"}},
        )
