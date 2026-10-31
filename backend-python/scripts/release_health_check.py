"""Fixed in-container release validation with no credential output."""

from __future__ import annotations

import json
import os
from urllib import request


def _json(url: str, *, payload=None, token=None):
    headers = {'Accept': 'application/json'}
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = request.Request(url, data=data, headers=headers, method='POST' if data else 'GET')
    with request.urlopen(req, timeout=20) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f'HTTP status {response.status}')
        return json.loads(response.read().decode('utf-8'))


def main() -> int:
    base = f"http://127.0.0.1:{os.getenv('PORT', '18888')}"
    health = _json(base + '/api/health')
    ready = _json(base + '/api/ready')
    if health.get('ok') is not True or ready.get('ok') is not True:
        raise RuntimeError('API health or readiness failed')
    email = os.getenv('PLATFORM_ADMIN_EMAIL')
    password = os.getenv('PLATFORM_ADMIN_PASSWORD')
    if not email or not password:
        raise RuntimeError('platform validation credentials are unavailable')
    login = _json(
        base + '/api/platform/auth/login',
        payload={'identifier': email, 'password': password},
    )
    token = login.get('token')
    if not token:
        raise RuntimeError('platform login returned no token')
    tenants = _json(base + '/api/platform/tenants', token=token)
    if not isinstance(tenants, list):
        raise RuntimeError('platform tenant navigation response is invalid')
    with request.urlopen('http://nginx/', timeout=20) as response:
        first_bytes = response.read(128)
        if response.status != 200 or not first_bytes:
            raise RuntimeError('Nginx file request failed')
    print(
        json.dumps(
            {
                'apiHealth': True,
                'apiReady': True,
                'fileRequest': True,
                'platformLogin': True,
                'tenantNavigation': True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
