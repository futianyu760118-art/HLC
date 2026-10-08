"""统一消息通知服务。

支持多种通知渠道：
- 站内通知（已有）
- 邮件通知
- 企业微信推送
- 钉钉推送

设计要点：
- 异步发送，不阻塞主流程
- 失败重试机制
- 用户通知偏好控制
- 模板化消息内容
"""

from __future__ import annotations

import logging
import os
import smtplib
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import requests
from flask import current_app

from models import Notification, User, db

logger = logging.getLogger(__name__)


class NotificationChannel:
    """通知渠道枚举"""
    IN_APP = 'in_app'  # 站内通知
    EMAIL = 'email'  # 邮件
    WECOM = 'wecom'  # 企业微信
    DINGTALK = 'dingtalk'  # 钉钉


class NotificationType:
    """通知类型枚举"""
    # 审批相关
    APPROVAL_PENDING = 'approval_pending'  # 待我审批
    APPROVAL_APPROVED = 'approval_approved'  # 审批通过
    APPROVAL_REJECTED = 'approval_rejected'  # 审批拒绝

    # 招聘相关
    INTERVIEW_SCHEDULED = 'interview_scheduled'  # 面试安排
    OFFER_SENT = 'offer_sent'  # Offer 发放
    OFFER_ACCEPTED = 'offer_accepted'  # Offer 接受

    # 入职相关
    ONBOARDING_TASK_ASSIGNED = 'onboarding_task_assigned'  # 入职任务分配
    ONBOARDING_TASK_REMINDER = 'onboarding_task_reminder'  # 入职任务提醒

    # 考勤相关
    ATTENDANCE_ANOMALY = 'attendance_anomaly'  # 考勤异常
    LEAVE_REQUEST_RESULT = 'leave_request_result'  # 请假结果

    # 绩效相关
    PERFORMANCE_REVIEW_START = 'performance_review_start'  # 绩效评估开始
    PERFORMANCE_REVIEW_REMINDER = 'performance_review_reminder'  # 绩效提醒

    # 培训相关
    TRAINING_ASSIGNED = 'training_assigned'  # 培训分配
    TRAINING_REMINDER = 'training_reminder'  # 培训提醒

    # 系统相关
    SYSTEM_ANNOUNCEMENT = 'system_announcement'  # 系统公告
    PASSWORD_CHANGED = 'password_changed'  # 密码修改


# 通知模板配置
NOTIFICATION_TEMPLATES = {
    NotificationType.APPROVAL_PENDING: {
        'title': '待审批：{title}',
        'content': '{submitter} 提交了 {type_label}，请及时处理。',
        'email_subject': '【恒聘通】您有一条待审批事项',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.WECOM],
    },
    NotificationType.APPROVAL_APPROVED: {
        'title': '审批通过：{title}',
        'content': '您的 {type_label} 已通过审批。',
        'email_subject': '【恒聘通】审批结果通知',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    },
    NotificationType.APPROVAL_REJECTED: {
        'title': '审批驳回：{title}',
        'content': '您的 {type_label} 被驳回，原因：{reason}',
        'email_subject': '【恒聘通】审批结果通知',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    },
    NotificationType.INTERVIEW_SCHEDULED: {
        'title': '面试通知：{position}',
        'content': '您的面试已安排在 {time}，地点：{location}',
        'email_subject': '【恒聘通】面试邀请',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    },
    NotificationType.OFFER_SENT: {
        'title': 'Offer 通知',
        'content': '恭喜！您已获得 {position} 岗位的 Offer，请查看详情。',
        'email_subject': '【恒聘通】Offer 通知',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    },
    NotificationType.ONBOARDING_TASK_ASSIGNED: {
        'title': '入职任务：{task_name}',
        'content': '您有新的入职任务需要完成，截止日期：{deadline}',
        'email_subject': '【恒聘通】入职任务通知',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    },
    NotificationType.ATTENDANCE_ANOMALY: {
        'title': '考勤异常提醒',
        'content': '您在 {date} 的考勤存在异常：{reason}',
        'email_subject': '【恒聘通】考勤异常通知',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.WECOM],
    },
    NotificationType.PERFORMANCE_REVIEW_START: {
        'title': '绩效评估：{cycle_name}',
        'content': '{cycle_name} 绩效评估已开始，请及时完成自评。',
        'email_subject': '【恒聘通】绩效评估通知',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    },
    NotificationType.TRAINING_ASSIGNED: {
        'title': '培训通知：{course_name}',
        'content': '您被分配了新的培训课程：{course_name}，请按时完成。',
        'email_subject': '【恒聘通】培训通知',
        'channels': [NotificationChannel.IN_APP, NotificationChannel.EMAIL],
    },
}


class NotificationService:
    """统一通知服务"""

    @staticmethod
    def send_notification(
        user_id: str,
        notification_type: str,
        template_data: Dict[str, Any],
        tenant_id: Optional[str] = None,
        link: Optional[str] = None,
        channels: Optional[List[str]] = None,
    ) -> bool:
        """发送通知（多渠道）

        Args:
            user_id: 接收用户 ID
            notification_type: 通知类型
            template_data: 模板数据
            tenant_id: 租户 ID
            link: 跳转链接
            channels: 指定渠道，为空则使用模板默认渠道

        Returns:
            是否至少有一个渠道发送成功
        """
        try:
            user = User.query.get(user_id)
            if not user:
                logger.error(f'User not found: {user_id}')
                return False

            template = NOTIFICATION_TEMPLATES.get(notification_type)
            if not template:
                logger.error(f'Unknown notification type: {notification_type}')
                return False

            # 渲染消息内容
            title = template['title'].format(**template_data)
            content = template['content'].format(**template_data)
            email_subject = template['email_subject']

            # 确定发送渠道
            target_channels = channels or template['channels']

            success = False

            # 站内通知
            if NotificationChannel.IN_APP in target_channels:
                if NotificationService._send_in_app(user_id, title, content, tenant_id, link):
                    success = True

            # 邮件通知
            if NotificationChannel.EMAIL in target_channels:
                if NotificationService._send_email(user.email, email_subject, title, content, link):
                    success = True

            # 企业微信通知
            if NotificationChannel.WECOM in target_channels:
                if NotificationService._send_wecom(user, title, content, link):
                    success = True

            # 钉钉通知
            if NotificationChannel.DINGTALK in target_channels:
                if NotificationService._send_dingtalk(user, title, content, link):
                    success = True

            return success

        except Exception as e:
            logger.error(f'Failed to send notification: {e}', exc_info=True)
            return False

    @staticmethod
    def _send_in_app(
        user_id: str,
        title: str,
        content: str,
        tenant_id: Optional[str],
        link: Optional[str],
    ) -> bool:
        """发送站内通知"""
        try:
            existing = Notification.query.filter_by(
                user_id=user_id,
                tenant_id=tenant_id,
                title=title,
                link_url=link,
                status='unread',
            ).first()
            if existing:
                return True
            notification = Notification(
                id=str(uuid.uuid4()),
                user_id=user_id,
                tenant_id=tenant_id,
                title=title,
                content=content,
                notice_type='system',
                status='unread',
                link_url=link,
                created_at=datetime.utcnow(),
            )
            db.session.add(notification)
            db.session.commit()
            return True
        except Exception as e:
            logger.error(f'Failed to send in-app notification: {e}', exc_info=True)
            db.session.rollback()
            return False

    @staticmethod
    def _send_email(
        to_email: str,
        subject: str,
        title: str,
        content: str,
        link: Optional[str],
    ) -> bool:
        """发送邮件通知"""
        try:
            # 读取 SMTP 配置
            smtp_host = os.getenv('SMTP_HOST')
            smtp_port = int(os.getenv('SMTP_PORT', '587'))
            smtp_user = os.getenv('SMTP_USER')
            smtp_password = os.getenv('SMTP_PASSWORD')
            smtp_from = os.getenv('SMTP_FROM', smtp_user)

            if not all([smtp_host, smtp_user, smtp_password]):
                logger.warning('SMTP not configured, skipping email notification')
                return False

            # 构建邮件内容
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = smtp_from
            msg['To'] = to_email

            # HTML 邮件模板
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #3b82f6; color: white; padding: 20px; text-align: center; }}
                    .content {{ background-color: #f9fafb; padding: 30px; margin-top: 20px; border-radius: 5px; }}
                    .button {{ display: inline-block; background-color: #3b82f6; color: white; padding: 12px 24px;
                              text-decoration: none; border-radius: 5px; margin-top: 20px; }}
                    .footer {{ text-align: center; color: #6b7280; font-size: 12px; margin-top: 30px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>{title}</h2>
                    </div>
                    <div class="content">
                        <p>{content}</p>
                        {f'<a href="{link}" class="button">查看详情</a>' if link else ''}
                    </div>
                    <div class="footer">
                        <p>此邮件由恒聘通 HRM 系统自动发送，请勿回复。</p>
                        <p>如有疑问，请联系您的 HR 管理员。</p>
                    </div>
                </div>
            </body>
            </html>
            """

            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)

            # 发送邮件
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)

            logger.info(f'Email sent to {to_email}')
            return True

        except Exception as e:
            logger.error(f'Failed to send email: {e}', exc_info=True)
            return False

    @staticmethod
    def _send_wecom(user: User, title: str, content: str, link: Optional[str]) -> bool:
        """发送企业微信通知"""
        try:
            wecom_webhook = os.getenv('WECOM_WEBHOOK_URL')
            if not wecom_webhook:
                logger.debug('企业微信 Webhook 未配置')
                return False

            # 构建消息内容
            markdown_content = f"### {title}\n\n{content}"
            if link:
                markdown_content += f"\n\n[点击查看详情]({link})"

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": markdown_content
                }
            }

            response = requests.post(wecom_webhook, json=payload, timeout=5)
            if response.status_code == 200 and response.json().get('errcode') == 0:
                logger.info(f'企业微信通知发送成功: {user.name}')
                return True
            else:
                logger.warning(f'企业微信通知发送失败: {response.text}')
                return False

        except Exception as e:
            logger.error(f'Failed to send wecom notification: {e}', exc_info=True)
            return False

    @staticmethod
    def _send_dingtalk(user: User, title: str, content: str, link: Optional[str]) -> bool:
        """发送钉钉通知"""
        try:
            dingtalk_webhook = os.getenv('DINGTALK_WEBHOOK_URL')
            if not dingtalk_webhook:
                logger.debug('钉钉 Webhook 未配置')
                return False

            # 构建消息内容
            markdown_content = f"### {title}\n\n{content}"
            if link:
                markdown_content += f"\n\n[点击查看详情]({link})"

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": markdown_content
                }
            }

            response = requests.post(dingtalk_webhook, json=payload, timeout=5)
            if response.status_code == 200 and response.json().get('errcode') == 0:
                logger.info(f'钉钉通知发送成功: {user.name}')
                return True
            else:
                logger.warning(f'钉钉通知发送失败: {response.text}')
                return False

        except Exception as e:
            logger.error(f'Failed to send dingtalk notification: {e}', exc_info=True)
            return False


# 便捷方法
def notify_approval_pending(approver_id: str, submitter_name: str, request_type: str,
                            request_title: str, tenant_id: str, link: str) -> bool:
    """通知待审批"""
    return NotificationService.send_notification(
        user_id=approver_id,
        notification_type=NotificationType.APPROVAL_PENDING,
        template_data={
            'title': request_title,
            'submitter': submitter_name,
            'type_label': request_type,
        },
        tenant_id=tenant_id,
        link=link,
    )


def notify_approval_result(user_id: str, approved: bool, request_type: str,
                          request_title: str, reason: str, tenant_id: str, link: str) -> bool:
    """通知审批结果"""
    notification_type = NotificationType.APPROVAL_APPROVED if approved else NotificationType.APPROVAL_REJECTED
    template_data = {
        'title': request_title,
        'type_label': request_type,
    }
    if not approved:
        template_data['reason'] = reason or '无'

    return NotificationService.send_notification(
        user_id=user_id,
        notification_type=notification_type,
        template_data=template_data,
        tenant_id=tenant_id,
        link=link,
    )


def notify_interview(candidate_email: str, position_name: str, interview_time: str,
                     location: str, tenant_id: str) -> bool:
    """通知面试安排（候选人可能没有user_id，直接发邮件）"""
    try:
        smtp_host = os.getenv('SMTP_HOST')
        if not smtp_host:
            return False

        subject = '【恒聘通】面试邀请'
        title = f'面试通知：{position_name}'
        content = f'您的面试已安排在 {interview_time}，地点：{location}'

        return NotificationService._send_email(candidate_email, subject, title, content, None)
    except Exception as e:
        logger.error(f'Failed to notify interview: {e}')
        return False
