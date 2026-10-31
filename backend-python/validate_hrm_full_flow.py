"""End-to-end HRM validation against the running Flask app.

The script is intentionally scenario-oriented: it verifies that demo data and
business actions connect across modules, not just that individual tables exist.
Run inside the backend container after ``seed_demo_data.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app import create_app
from models import (
    ApprovalInstance,
    AssistantAuditLog,
    Candidate,
    Contract,
    Department,
    Employee,
    EmployeeChange,
    EmployeeRequest,
    Interview,
    Job,
    Notification,
    OperationLog,
    Offer,
    OnboardingTask,
    PayrollRecord,
    PerformanceReview,
    Position,
    Probation,
    Resignation,
    Resume,
    Role,
    SalaryProfile,
    TrainingRecord,
    User,
    db,
)
from seed_demo_data import seed_demo_data


ADMIN_EMAIL = 'admin@hengpintong.demo'
EMPLOYEE_EMAIL = 'employee@hengpintong.demo'
PASSWORD = 'Demo@123456'


@dataclass
class Scenario:
    name: str
    checks: List[str] = field(default_factory=list)


class Validator:
    def __init__(self) -> None:
        self.app = create_app()
        self.client = self.app.test_client()
        self.admin_headers = self._login(ADMIN_EMAIL)
        self.employee_headers = self._login(EMPLOYEE_EMAIL)
        self.scenarios: List[Scenario] = []
        self.failures: List[str] = []

    def _login(self, email: str) -> Dict[str, str]:
        resp = self.client.post('/api/auth/login', json={'email': email, 'password': PASSWORD})
        self._assert_response(resp, f'login:{email}')
        token = resp.get_json()['token']
        return {'Authorization': f'Bearer {token}'}

    def _assert_response(self, resp, label: str, expected: int = 200) -> None:
        if resp.status_code != expected:
            payload = resp.get_data(as_text=True)[:500]
            raise AssertionError(f'{label} expected {expected}, got {resp.status_code}: {payload}')

    def get(self, path: str, *, employee: bool = False, expected: int = 200) -> Any:
        headers = self.employee_headers if employee else self.admin_headers
        resp = self.client.get(path, headers=headers)
        self._assert_response(resp, path, expected)
        if expected >= 400:
            return None
        return resp.get_json()

    def post(self, path: str, payload: Optional[Dict[str, Any]] = None, *, expected: int = 200) -> Any:
        resp = self.client.post(path, headers=self.admin_headers, json=payload or {})
        self._assert_response(resp, path, expected)
        if expected >= 400:
            return None
        return resp.get_json()

    def scenario(self, name: str, func: Callable[[Scenario], None]) -> None:
        item = Scenario(name)
        try:
            func(item)
        except Exception as exc:  # noqa: BLE001 - collect all scenario failures
            self.failures.append(f'{name}: {exc}')
        self.scenarios.append(item)

    def check(self, scenario: Scenario, condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)
        scenario.checks.append(message)

    def count(self, model, **filters) -> int:
        return model.query.filter_by(**filters).count()

    def validate_full_lifecycle_person(self, scenario: Scenario) -> None:
        employee_id = 'demo-emp-rd-wuminghua'
        self.check(scenario, self.count(Resume, candidate_name='吴明华') == 1, 'resume exists')
        self.check(scenario, self.count(Candidate, id='demo-cand-wuminghua', status='converted') == 1, 'candidate converted')
        self.check(scenario, self.count(Interview, resume_id='demo-resume-wuminghua', status='completed') == 1, 'interview completed')
        self.check(scenario, self.count(Offer, id='demo-offer-wuminghua', employee_id=employee_id, status='converted') == 1, 'offer converted')
        self.check(scenario, self.count(Employee, id=employee_id, status='resigned') == 1, 'employee resigned')
        self.check(scenario, self.count(OnboardingTask, employee_id=employee_id, status='completed') >= 3, 'onboarding tasks completed')
        self.check(scenario, self.count(Contract, employee_id=employee_id) == 1, 'contract exists')
        self.check(scenario, self.count(TrainingRecord, employee_id=employee_id) >= 2, 'training records exist')
        self.check(scenario, self.count(EmployeeRequest, employee_id=employee_id, status='approved') >= 1, 'approved request exists')
        self.check(scenario, self.count(SalaryProfile, employee_id=employee_id) == 1, 'salary profile exists')
        self.check(scenario, self.count(PayrollRecord, employee_id=employee_id, payroll_month='2026-05') == 1, 'payroll exists')
        self.check(scenario, self.count(PerformanceReview, employee_id=employee_id) == 1, 'performance review exists')
        self.check(scenario, self.count(Probation, employee_id=employee_id, status='approved') == 1, 'probation approved')
        self.check(scenario, self.count(EmployeeChange, employee_id=employee_id, status='approved') == 1, 'salary change approved')
        self.check(scenario, self.count(Resignation, employee_id=employee_id, status='approved') == 1, 'resignation approved')
        self.check(scenario, self.count(ApprovalInstance, business_id='demo-resignation-wuminghua', status='approved') == 1, 'resignation approval exists')

        answer = self.post('/api/hrm/assistant/query', {
            'question': '吴明华从简历录入到入职、培训、发薪和离职的完整链路有哪些记录？',
        })
        self.check(scenario, len(answer.get('entities') or []) >= 12, 'assistant returns lifecycle entities')
        self.check(scenario, '吴明华' in (answer.get('summary') or ''), 'assistant summary mentions subject')

        lifecycle = self.get(f'/api/hrm/employees/{employee_id}/lifecycle')
        expected_counts = {
            'resumes': 1,
            'candidates': 1,
            'interviews': 1,
            'offers': 1,
            'onboardingTasks': 3,
            'contracts': 1,
            'attendanceRecords': 1,
            'employeeRequests': 1,
            'salaryProfiles': 1,
            'payrollRecords': 1,
            'performanceReviews': 1,
            'trainingRecords': 2,
            'probations': 1,
            'employeeChanges': 1,
            'resignations': 1,
            'approvals': 1,
            'operationLogs': 1,
        }
        for key, min_count in expected_counts.items():
            self.check(scenario, lifecycle['moduleCounts'].get(key, 0) >= min_count, f'lifecycle includes {key}')
        self.check(scenario, all(item.get('ok') for item in lifecycle.get('connectivity') or []), 'lifecycle connectivity checks pass')
        self.check(scenario, len(lifecycle.get('timeline') or []) >= 15, 'lifecycle timeline spans modules')

    def validate_recruit_to_onboard(self, scenario: Scenario) -> None:
        payload = self.post('/api/hrm/offers/demo-offer-sunye/convert-to-employee')
        self.check(scenario, payload['employee']['id'] == 'demo-emp-product-sunye', 'offer maps to employee')
        self.check(scenario, len(payload.get('onboardingTasks') or []) >= 3, 'offer conversion exposes onboarding tasks')
        self.check(scenario, payload.get('salaryProfile') is not None, 'offer conversion exposes salary profile')
        self.check(scenario, payload.get('contract') is not None, 'offer conversion exposes contract')

    def validate_performance_growth_and_compensation(self, scenario: Scenario) -> None:
        before = SalaryProfile.query.filter_by(employee_id='demo-emp-rd-lisi').first()
        before_perf = float(before.performance_salary or 0)
        salary_flow = self.post('/api/hrm/performance-reviews/demo-review-lisi/generate-salary-change', {
            'salaryAdjustment': 800,
            'effectiveDate': '2026-06-01',
        })
        change_id = salary_flow['salaryChange']['id']
        submit = self.post(f'/api/hrm/employee-changes/{change_id}/submit')
        self.post(f'/api/hrm/approvals/{submit["approval"]["id"]}/approve', {'comment': 'full-flow validation'})
        after = SalaryProfile.query.filter_by(employee_id='demo-emp-rd-lisi').first()
        self.check(scenario, float(after.performance_salary or 0) >= before_perf + 800, 'approved change updates salary profile')

        before_training = self.count(TrainingRecord, employee_id='demo-emp-rd-lisi')
        training_flow = self.post('/api/hrm/performance-reviews/demo-review-lisi/generate-training-plan')
        after_training = self.count(TrainingRecord, employee_id='demo-emp-rd-lisi')
        self.check(scenario, after_training >= before_training + 1, 'performance creates training record')
        self.check(scenario, training_flow['trainingRecord']['employeeName'] == '李四', 'training record linked to employee')

    def validate_attendance_to_payroll(self, scenario: Scenario) -> None:
        attendance = self.get('/api/hrm/attendance/monthly?month=2026-05')
        rows = attendance.get('records') or []
        wuminghua = next((row for row in rows if row.get('employeeName') == '吴明华'), None)
        self.check(scenario, attendance['sourceCounts']['attendanceRecords'] >= 8, 'monthly attendance reads records')
        self.check(scenario, attendance['sourceCounts']['approvedRequests'] >= 3, 'monthly attendance reads approved requests')
        self.check(scenario, bool(wuminghua and wuminghua.get('overtime', 0) >= 1), 'monthly attendance includes subject overtime')

        payroll = self.post('/api/hrm/payroll-records/generate-month', {'month': '2026-05'})
        self.check(scenario, payroll['metrics']['attendanceRecords'] >= 5, 'payroll reads attendance')
        self.check(scenario, payroll['metrics']['approvedRequests'] >= 2, 'payroll reads requests')
        self.check(scenario, len(payroll.get('records') or []) >= 4, 'payroll generates records')

    def validate_ai_governance_and_isolation(self, scenario: Scenario) -> None:
        logs = self.get('/api/hrm/assistant/audit-logs?limit=10')
        self.check(scenario, len(logs) >= 4, 'admin can list audit logs')
        detail = self.get(f'/api/hrm/assistant/audit-logs/{logs[0]["id"]}')
        self.check(scenario, bool(detail.get('promptMessages')), 'audit detail includes prompts')
        self.check(scenario, 'responseContent' in detail, 'audit detail includes response')
        summary = self.get('/api/hrm/assistant/audit-summary?days=30')
        self.check(scenario, summary.get('totalCalls', 0) >= 4, 'audit summary aggregates calls')
        self.check(scenario, summary.get('successCount', 0) >= 3, 'audit summary counts successes')
        self.check(scenario, summary.get('timeoutCount', 0) >= 1, 'audit summary counts timeouts')
        self.check(scenario, bool(summary.get('byProfile')), 'audit summary breaks down profiles')

        self.get('/api/hrm/assistant/audit-logs?limit=1', employee=True, expected=403)
        self.get('/api/hrm/assistant/audit-summary', employee=True, expected=403)
        self.get('/api/hrm/assistant/sessions/demo-assistant-session-hr', employee=True, expected=404)
        employee_sessions = self.get('/api/hrm/assistant/sessions', employee=True)
        self.check(scenario, all(row.get('userId') != 'demo-user-hr' for row in employee_sessions), 'employee sessions exclude HR sessions')

    def validate_module_connectivity_matrix(self, scenario: Scenario) -> None:
        meta = self.get('/api/hrm/meta')
        required_resources = {
            'departments', 'positions', 'candidates', 'offers', 'employees', 'onboarding-tasks',
            'probations', 'employee-changes', 'resignations', 'contracts', 'attendance-records',
            'employee-requests', 'performance-cycles', 'performance-templates',
            'performance-reviews', 'salary-profiles', 'payroll-records', 'training-courses',
            'training-plans', 'training-records', 'roles', 'users', 'notifications',
            'operation-logs',
        }
        self.check(scenario, required_resources.issubset(set(meta.get('resources') or [])), 'meta exposes all HRM resources')

        resource_expectations = {
            'departments': ('总部办公室', 'name'),
            'positions': ('后端工程师', 'title'),
            'candidates': ('吴明华', 'name'),
            'offers': ('吴明华-后端工程师 Offer', 'title'),
            'employees': ('吴明华', 'name'),
            'onboarding-tasks': ('收集入职材料', 'name'),
            'probations': ('建议转正', 'result'),
            'employee-changes': ('调薪', 'changeType'),
            'resignations': ('回老家发展，已完成代码、文档和监控交接。', 'reason'),
            'contracts': ('HT-DEMO-2025-0011', 'contractNo'),
            'attendance-records': ('吴明华', 'employeeName'),
            'employee-requests': ('吴明华 离职交接加班', 'title'),
            'performance-cycles': ('2026 Q2 绩效周期', 'name'),
            'performance-templates': ('技术与协作绩效模板', 'name'),
            'performance-reviews': ('吴明华', 'employeeName'),
            'salary-profiles': ('吴明华', 'employeeName'),
            'payroll-records': ('吴明华', 'employeeName'),
            'training-courses': ('质量效率提升训练营', 'name'),
            'training-plans': ('Q2 质量效率提升计划', 'name'),
            'training-records': ('吴明华', 'employeeName'),
            'roles': ('HR管理员', 'name'),
            'users': ('林瑶', 'name'),
            'notifications': ('演示数据已完成全模块联通', 'title'),
            'operation-logs': ('employees', 'module'),
        }
        for resource, (expected_value, field) in resource_expectations.items():
            rows = self.get(f'/api/hrm/{resource}')
            self.check(scenario, isinstance(rows, list) and len(rows) > 0, f'{resource} list has rows')
            self.check(scenario, any(row.get(field) == expected_value for row in rows), f'{resource} exposes linked field {field}')

        dashboard = self.get('/api/hrm/dashboard')
        self.check(scenario, dashboard['cards']['activeEmployees'] >= 5, 'dashboard reads employee module')
        self.check(scenario, dashboard['cards']['requests'] >= 3, 'dashboard reads request module')
        self.check(scenario, dashboard['cards']['attendanceExceptions'] >= 1, 'dashboard reads attendance module')
        self.check(scenario, self.count(PayrollRecord, payroll_month='2026-05') >= 4, 'payroll resource exposes monthly payroll')

        self.check(scenario, self.count(Department, id='demo-dept-rd') == 1, 'department reference exists')
        self.check(scenario, self.count(Position, id='demo-pos-backend') == 1, 'position reference exists')
        self.check(scenario, self.count(Job, id='demo-job-backend') == 1, 'job reference exists')
        self.check(scenario, self.count(User, id='demo-user-hr', employee_id='demo-emp-hr-linyao') == 1, 'user links employee')
        self.check(scenario, self.count(Role, code='hr_admin') == 1, 'role catalog exists')
        self.check(scenario, self.count(Notification, link_url='/hrm/resignations') == 1, 'notification links HRM module')
        self.check(scenario, self.count(OperationLog, target_id='demo-emp-rd-wuminghua') == 1, 'operation log links employee lifecycle')

    def run(self) -> int:
        with self.app.app_context():
            seed_demo_data()
            self.scenario('full_lifecycle_resume_to_resignation', self.validate_full_lifecycle_person)
            self.scenario('recruit_to_onboard', self.validate_recruit_to_onboard)
            self.scenario('performance_to_compensation_and_training', self.validate_performance_growth_and_compensation)
            self.scenario('attendance_to_payroll', self.validate_attendance_to_payroll)
            self.scenario('ai_governance_and_account_isolation', self.validate_ai_governance_and_isolation)
            self.scenario('module_connectivity_matrix', self.validate_module_connectivity_matrix)

        output = {
            'ok': not self.failures,
            'scenarios': [
                {'name': scenario.name, 'checks': len(scenario.checks), 'details': scenario.checks}
                for scenario in self.scenarios
            ],
            'failures': self.failures,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 1 if self.failures else 0


def main() -> None:
    raise SystemExit(Validator().run())


if __name__ == '__main__':
    main()
