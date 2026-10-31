"""Governed employee self-service and mobile Web/PWA extension MVP services."""

from __future__ import annotations

import uuid
from typing import Any

from models import (
    ApprovalInstance,
    AttendanceRecord,
    Certificate,
    Employee,
    EmployeePortalAccount,
    MobileInsightSnapshot,
    Notification,
    PayrollRecord,
    db,
    money,
)
from services.extension_registry import extension_feature_maturity, extension_read_marker


MOBILE_FEATURES = {
    'self_service': 'extension.mobile.self_service',
    'pwa': 'extension.mobile.pwa',
    'approval': 'extension.mobile.approval',
    'attendance': 'extension.mobile.attendance',
    'payslip': 'extension.mobile.payslip',
    'certificate_download': 'extension.mobile.certificate_download',
    'notifications': 'extension.mobile.notifications',
    'offline_shell': 'extension.mobile.offline_shell',
}


def _amount(value: Any) -> float:
    return float(money(value) or 0)


class MobileService:
    @staticmethod
    def build_feature_summary(tenant_id: str, feature: str, operator_id: str | None = None) -> dict[str, Any]:
        if feature not in MOBILE_FEATURES:
            raise LookupError(feature)

        base = MobileService._base_context(tenant_id)
        builders = {
            'self_service': MobileService._self_service_payload,
            'pwa': MobileService._pwa_payload,
            'approval': MobileService._approval_payload,
            'attendance': MobileService._attendance_payload,
            'payslip': MobileService._payslip_payload,
            'certificate_download': MobileService._certificate_payload,
            'notifications': MobileService._notifications_payload,
            'offline_shell': MobileService._offline_payload,
        }
        payload = builders[feature](tenant_id, base)
        feature_key = MOBILE_FEATURES[feature]
        payload.update({
            'featureKey': feature_key,
            'status': extension_feature_maturity(feature_key),
        })
        payload.setdefault('summary', {})['dataScope'] = 'currentTenant'

        payload['snapshot'] = extension_read_marker(feature_key)
        return payload

    @staticmethod
    def _base_context(tenant_id: str) -> dict[str, Any]:
        employees = Employee.query.filter_by(tenant_id=tenant_id).order_by(Employee.name.asc()).all()
        portal_accounts = EmployeePortalAccount.query.filter_by(tenant_id=tenant_id).order_by(EmployeePortalAccount.created_at.desc()).all()
        approvals = ApprovalInstance.query.filter_by(tenant_id=tenant_id).order_by(ApprovalInstance.created_at.desc()).all()
        attendance = AttendanceRecord.query.filter_by(tenant_id=tenant_id).order_by(AttendanceRecord.attendance_date.desc()).all()
        payrolls = PayrollRecord.query.filter_by(tenant_id=tenant_id, employee_visible=True).order_by(PayrollRecord.created_at.desc()).all()
        certificates = Certificate.query.filter_by(tenant_id=tenant_id).order_by(Certificate.created_at.desc()).all()
        notifications = Notification.query.filter_by(tenant_id=tenant_id).order_by(Notification.created_at.desc()).all()
        return {
            'employees': employees,
            'portalAccounts': portal_accounts,
            'approvals': approvals,
            'attendance': attendance,
            'payrolls': payrolls,
            'certificates': certificates,
            'notifications': notifications,
        }

    @staticmethod
    def _self_service_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        accounts = [
            {
                'accountId': row.id,
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'employeeNo': row.employee.employee_no if row.employee else None,
                'status': row.status,
                'mustChangePassword': bool(row.must_change_password),
            }
            for row in base['portalAccounts']
        ]
        actions = [
            {'key': 'profile', 'label': '个人档案'},
            {'key': 'learning', 'label': '学习中心'},
            {'key': 'approval', 'label': '移动审批'},
            {'key': 'payslip', 'label': '工资条'},
            {'key': 'certificate', 'label': '证明/证书下载'},
        ]
        return {
            'summary': {
                'employeeCount': len(base['employees']),
                'portalAccountCount': len(accounts),
                'selfServiceActionCount': len(actions),
            },
            'accounts': accounts[:20],
            'actions': actions,
        }

    @staticmethod
    def _pwa_payload(_tenant_id: str, _base: dict[str, Any]) -> dict[str, Any]:
        capabilities = [
            {'key': 'installable', 'label': '可安装 Web App', 'status': 'planned'},
            {'key': 'responsive_shell', 'label': '移动端响应式外壳', 'status': 'implemented'},
            {'key': 'offline_cache', 'label': '离线资源缓存', 'status': 'planned'},
            {'key': 'push_placeholder', 'label': '推送适配占位', 'status': 'provider_optional'},
        ]
        return {
            'summary': {
                'installableCapabilityCount': len(capabilities),
                'deliveryMode': 'mobile_web_pwa',
            },
            'capabilities': capabilities,
        }

    @staticmethod
    def _approval_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        mobile_approvals = [
            {
                'id': row.id,
                'title': row.title,
                'businessType': row.business_type,
                'status': row.status,
                'currentStep': row.current_step,
            }
            for row in base['approvals']
        ]
        return {
            'summary': {
                'approvalCount': len(mobile_approvals),
                'pendingApprovalCount': sum(1 for row in mobile_approvals if row['status'] == 'pending'),
            },
            'approvals': mobile_approvals[:20],
        }

    @staticmethod
    def _attendance_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        rows = [
            {
                'recordId': row.id,
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'attendanceDate': row.attendance_date.isoformat() if row.attendance_date else None,
                'status': row.status,
                'workHours': _amount(row.work_hours),
                'source': row.source,
            }
            for row in base['attendance']
        ]
        return {
            'summary': {
                'mobileAttendanceRecordCount': len(rows),
                'normalRecordCount': sum(1 for row in rows if row['status'] in ('normal', 'present')),
            },
            'attendanceRecords': rows[:20],
        }

    @staticmethod
    def _payslip_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        payslips = [
            {
                'recordId': row.id,
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'payrollMonth': row.payroll_month,
                'status': row.status,
                'netSalary': _amount(row.net_salary),
            }
            for row in base['payrolls']
        ]
        return {
            'summary': {
                'visiblePayslipCount': len(payslips),
                'totalNetSalary': round(sum(row['netSalary'] for row in payslips), 2),
            },
            'payslips': payslips[:20],
        }

    @staticmethod
    def _certificate_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        certificates = [
            {
                'id': row.id,
                'employeeId': row.employee_id,
                'employeeName': row.employee_name,
                'courseTitle': row.course_title,
                'certNo': row.cert_no,
                'downloadUrl': row.image_url,
            }
            for row in base['certificates']
        ]
        return {
            'summary': {
                'certificateCount': len(certificates),
                'downloadReadyCount': sum(1 for row in certificates if row['downloadUrl']),
            },
            'certificates': certificates[:20],
        }

    @staticmethod
    def _notifications_payload(_tenant_id: str, base: dict[str, Any]) -> dict[str, Any]:
        notifications = [
            {
                'id': row.id,
                'employeeId': row.employee_id,
                'employeeName': row.employee.name if row.employee else None,
                'title': row.title,
                'noticeType': row.notice_type,
                'status': row.status,
                'linkUrl': row.link_url,
            }
            for row in base['notifications']
        ]
        return {
            'summary': {
                'notificationCount': len(notifications),
                'unreadNotificationCount': sum(1 for row in notifications if row['status'] == 'unread'),
            },
            'notifications': notifications[:20],
        }

    @staticmethod
    def _offline_payload(_tenant_id: str, _base: dict[str, Any]) -> dict[str, Any]:
        resources = [
            {'key': 'shell', 'label': '应用外壳', 'strategy': 'cache_first'},
            {'key': 'icons', 'label': '图标与字体', 'strategy': 'cache_first'},
            {'key': 'portal_home', 'label': '门户首页', 'strategy': 'stale_while_revalidate'},
            {'key': 'profile_snapshot', 'label': '个人资料快照', 'strategy': 'network_first'},
            {'key': 'payslip_snapshot', 'label': '工资条快照', 'strategy': 'network_first'},
        ]
        return {
            'summary': {
                'offlineResourceCount': len(resources),
                'offlineMode': 'pwa_cache_mvp',
            },
            'resources': resources,
        }
