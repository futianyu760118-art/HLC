"""统一推送抽象：notify(channel, receiver, content)。

通道：
- station：站内通知（写 notifications 表，演示用）
- wecom：企业微信（占位，未配置时跳过；计划 10/10 前接入）

接收人用 {employeeId, userId} 描述；只有 employeeId 时会自动映射到已绑定的门户用户。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from models import Notification, User, db

logger = logging.getLogger(__name__)

CHANNELS = ('station', 'wecom')


def notify(
    channel: str,
    *,
    tenant_id: str,
    title: str,
    content: str,
    employee_id: str | None = None,
    user_id: str | None = None,
    notice_type: str = 'system',
    link_url: str | None = None,
) -> bool:
    """向单个接收人推送一条消息。返回是否成功。"""
    if channel == 'station':
        return _send_station(
            tenant_id, title=title, content=content,
            employee_id=employee_id, user_id=user_id,
            notice_type=notice_type, link_url=link_url,
        )
    if channel == 'wecom':
        # 占位：待接入企业微信应用/secret 后实现
        logger.info('notify_wecom_placeholder', extra={'employeeId': employee_id, 'title': title})
        return False
    raise ValueError(f'不支持的推送通道：{channel}')


def notify_many(
    channels: list[str],
    receivers: list[dict],
    *,
    tenant_id: str,
    title: str,
    content: str,
    notice_type: str = 'system',
    link_url: str | None = None,
) -> dict:
    """多通道 + 多接收人推送。receivers 元素支持 employeeId / userId。"""
    channels = [c for c in (channels or ['station']) if c in CHANNELS] or ['station']
    sent = 0
    skipped = 0
    for receiver in receivers or []:
        delivered = False
        for channel in channels:
            try:
                if notify(
                    channel, tenant_id=tenant_id, title=title, content=content,
                    employee_id=receiver.get('employeeId'), user_id=receiver.get('userId'),
                    notice_type=notice_type, link_url=link_url,
                ):
                    delivered = True
            except Exception:  # noqa: BLE001
                logger.exception('notify_channel_failed', extra={'channel': channel})
        if delivered:
            sent += 1
        else:
            skipped += 1
    return {'channels': channels, 'receivers': len(receivers or []), 'sent': sent, 'skipped': skipped}


def _send_station(
    tenant_id: str,
    *,
    title: str,
    content: str,
    employee_id: str | None,
    user_id: str | None,
    notice_type: str,
    link_url: str | None,
) -> bool:
    if not user_id and employee_id:
        user = User.query.filter_by(employee_id=employee_id, tenant_id=tenant_id).first()
        if user is not None:
            user_id = user.id
    if not user_id and not employee_id:
        return False
    notification = Notification(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        employee_id=employee_id,
        title=title,
        content=content,
        notice_type=notice_type,
        status='unread',
        link_url=link_url,
        created_at=datetime.utcnow(),
    )
    db.session.add(notification)
    return True
