"""重试机制工具"""
import time
import asyncio
from functools import wraps
from typing import Callable, Any, Optional
from loguru import logger


def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
    retry_condition: Optional[Callable[[Exception], bool]] = None
):
    """
    异步重试装饰器
    
    Args:
        max_attempts: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 延迟倍数因子
        exceptions: 需要重试的异常类型
        retry_condition: 自定义重试条件函数
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    result = await func(*args, **kwargs)
                    # 检查结果是否为空或无效
                    if result is None or result == "":
                        logger.warning(f"Function {func.__name__} returned empty result on attempt {attempt + 1}/{max_attempts}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(current_delay)
                            current_delay *= backoff_factor
                            continue
                    return result
                    
                except exceptions as e:
                    last_exception = e
                    logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed for {func.__name__}: {str(e)}")
                    
                    # 检查是否满足重试条件
                    if retry_condition and not retry_condition(e):
                        logger.warning(f"Retry condition not met for {func.__name__}, not retrying")
                        break
                    
                    if attempt < max_attempts - 1:
                        logger.info(f"Retrying {func.__name__} in {current_delay} seconds...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
            
            # 所有尝试都失败，抛出最后一个异常
            if last_exception:
                raise last_exception
            return None
            
        return wrapper
    return decorator


def should_retry_http_error(error: Exception) -> bool:
    """判断HTTP错误是否应该重试"""
    import httpx
    if isinstance(error, httpx.TimeoutException):
        return True
    if isinstance(error, httpx.NetworkError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        # 5xx 错误可以重试，4xx 错误不重试
        return 500 <= error.response.status_code < 600
    return False


def should_retry_empty_response(error: Exception) -> bool:
    """判断空响应是否应该重试"""
    # 如果是空响应或内容为空，应该重试
    if isinstance(error, ValueError) and "empty" in str(error).lower():
        return True
    return False