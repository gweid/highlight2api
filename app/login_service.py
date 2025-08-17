import base64
import json
import re
import uuid
from typing import Dict, Any

import httpx
from loguru import logger

from .config import HIGHLIGHT_BASE_URL, TLS_VERIFY


async def process_highlight_login(login_link: str) -> Dict[str, Any]:
    """处理 Highlight 登录流程"""
    try:
        # 提取 code
        code_match = re.search(r'code=(.+)', login_link)
        if not code_match:
            raise ValueError("无法从链接中提取 code")

        code = code_match.group(1)
        chrome_device_id = str(uuid.uuid4())
        device_id = str(uuid.uuid4())

        # 第一步：交换 token
        headers = {'Content-Type': 'application/json'}
        json_data = {
            'code': code,
            'amplitudeDeviceId': chrome_device_id,
        }

        async with httpx.AsyncClient(verify=TLS_VERIFY, timeout=30.0) as client:
            response = await client.post(
                f'{HIGHLIGHT_BASE_URL}/api/v1/auth/exchange',
                headers=headers,
                json=json_data
            )

            if response.status_code != 200:
                raise ValueError(f'登录失败 {response.status_code} {response.text}')

            result = response.json()
            if not result.get('success'):
                raise ValueError(f'登录失败 {result}')

            at = result['data']['accessToken']
            rt = result['data']['refreshToken']

            # 第二步：注册客户端
            headers = {
                'Content-Type': 'application/json',
                'authorization': f'Bearer {at}'
            }

            json_data = {"client_uuid": device_id}

            await client.post(
                f'{HIGHLIGHT_BASE_URL}/api/v1/users/me/client',
                headers=headers,
                json=json_data
            )

            # 第三步：获取用户信息
            response = await client.get(
                f'{HIGHLIGHT_BASE_URL}/api/v1/auth/profile',
                headers=headers
            )

            if response.status_code != 200:
                raise ValueError(f'获取用户信息失败 {response.status_code}')

            profile = response.json()
            user_id = profile['id']
            email = profile['email']

            # 生成 API Key
            data = json.dumps({
                'rt': rt,
                'user_id': user_id,
                'email': email,
                'client_uuid': device_id
            })
            api_key = base64.urlsafe_b64encode(data.encode('utf-8')).decode('utf-8')

            return {
                'success': True,
                'api_key': api_key,
                'user_info': {
                    'user_id': user_id,
                    'email': email,
                    'client_uuid': device_id
                }
            }

    except Exception as e:
        logger.error(f"登录处理失败: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
