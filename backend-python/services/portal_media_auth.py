"""受保护媒体（视频/大文件）签名 URL 的生成与校验。

设计目标：
- 让 <video src> 能直接播放受保护视频，无需 Authorization header（<video> 无法带 header）。
- 不放宽静态文件访问：URL 短期有效，签名绑定 SECRET_KEY，不可伪造。
- 支持 Range 请求（send_from_directory 原生支持），可流式播放 / 拖动进度。

生成方：routes/portal.py::_signed_media_url
校验方：app.py::_api_media
"""
from __future__ import annotations

import hmac
import hashlib
import time
from typing import Tuple

from flask import current_app


MEDIA_URL_TTL = 2 * 60 * 60  # 签名有效期 2 小时


def _secret() -> bytes:
    """统一签名密钥来源（Config.SECRET_KEY）。"""
    return str(current_app.config.get('SECRET_KEY') or '').encode('utf-8')


def _payload(key: str, exp: int) -> bytes:
    return f'{key}:{exp}'.encode('utf-8')


def sign(key: str, exp: int) -> str:
    """返回签名 hex。"""
    return hmac.new(_secret(), _payload(key, exp), hashlib.sha256).hexdigest()


def build_signed_url(key: str, ttl: int = MEDIA_URL_TTL) -> str:
    """生成 /api/media/<key>?exp=&sig= 形式的签名 URL。"""
    if not key:
        return ''
    safe_key = str(key).lstrip('/')
    exp = int(time.time()) + ttl
    sig = sign(safe_key, exp)
    return f'/api/media/{safe_key}?exp={exp}&sig={sig}'


def verify_media_signature(key: str, exp_raw, sig_raw) -> Tuple[bool, str]:
    """校验签名与有效期。返回 (ok, reason)。"""
    if not key or not exp_raw or not sig_raw:
        return False, '缺少签名参数'
    try:
        exp = int(str(exp_raw))
    except (TypeError, ValueError):
        return False, '签名无效'
    # 过期判断留一点时钟容差
    if exp < int(time.time()) - 5:
        return False, '链接已过期'
    expected = sign(str(key).lstrip('/'), exp)
    if not hmac.compare_digest(expected, str(sig_raw)):
        return False, '签名无效'
    return True, ''
