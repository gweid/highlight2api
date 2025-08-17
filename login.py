import base64
import json
import re
import uuid

import requests
from loguru import logger


def main():
    print("浏览器打开: \nhttps://chat-backend.highlightai.com/api/v1/auth/signin?screenHint=sign-in")
    login_link = input('完成登录后复制 https://highlightai.com/deeplink?code=xxxxxxx 链接粘贴到此处: ')
    code = re.search(r'code=(.+)', login_link).group(1)
    chrome_device_id = str(uuid.uuid4())
    device_id = str(uuid.uuid4())
    headers = {
        'Content-Type': 'application/json',
    }

    json_data = {
        'code': code,
        'amplitudeDeviceId': chrome_device_id,
    }

    response = requests.post(
        'https://chat-backend.highlightai.com/api/v1/auth/exchange',
        headers=headers,
        json=json_data
    )
    suc = response.json()['success']
    if not suc:
        logger.error(f'登录失败 {response.status_code} {response.text}')
        return

    at = response.json()['data']['accessToken']
    rt = response.json()['data']['refreshToken']

    headers = {
        'Content-Type': 'application/json',
        'authorization': f'Bearer {at}'
    }

    json_data = {
        "client_uuid": device_id
    }

    requests.post('https://chat-backend.highlightai.com/api/v1/users/me/client', headers=headers, json=json_data)

    response = requests.get('https://chat-backend.highlightai.com/api/v1/auth/profile', headers=headers)
    user_id = response.json()['id']
    email = response.json()['email']

    logger.success(f'登录成功 {user_id} {email} {rt}')
    data = json.dumps({
        'rt': rt,
        'user_id': user_id,
        'email': email,
        'client_uuid': device_id
    })
    print("----API KEY----")
    print(base64.urlsafe_b64encode(data.encode('utf-8')).decode('utf-8'))
    print("----API KEY----")


if __name__ == '__main__':
    main()
