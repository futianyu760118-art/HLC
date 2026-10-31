"""Tests for the intelligent read-only SQL fallback skill."""

from __future__ import annotations

from flask import Flask, current_app, g
import pytest

from services.assistant_core.schemas import AssistantContext


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-smart-sql', role=role, session_id='s-smart-sql')


@pytest.fixture()
def model_db(monkeypatch):
    from models import db
    from services.assistant_core.smart_query import reset_readonly_engine_for_tests

    for name in (
        'DB_READONLY_URI',
        'DB_READONLY_HOST',
        'DB_READONLY_PORT',
        'DB_READONLY_USER',
        'DB_READONLY_PASSWORD',
        'DB_READONLY_NAME',
    ):
        monkeypatch.delenv(name, raising=False)
    reset_readonly_engine_for_tests()

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield db
        db.session.remove()
        db.drop_all()
        reset_readonly_engine_for_tests()


class TestSmartDataQuerySkill:
    def test_registered_as_read_only_skill(self) -> None:
        from services.assistant_core import skill_registry

        spec = skill_registry.get('smart_data_query')

        assert spec is not None
        assert spec.side_effect is False
        assert spec.risk_level == 'medium'

    def test_tenant_sql_prompt_matches_enforced_predicate_locations(self, model_db, monkeypatch) -> None:
        import json
        from services.assistant_core import smart_query

        captured = {}

        def fake_json_chat_profile(_profile, messages, **_kwargs):
            captured['prompt'] = json.loads(messages[1]['content'])
            return {
                'sql': 'SELECT j.id FROM jobs j WHERE j.tenant_id = :tenant_id',
                'explanation': 'tenant scoped',
            }

        monkeypatch.setattr(smart_query.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(smart_query.llm_client, 'json_chat_profile', fake_json_chat_profile)
        monkeypatch.setattr(smart_query, 'build_schema_summary', lambda: '- jobs(id; tenant_id)')

        with current_app.test_request_context('/api/assistant/query'):
            g.tenant_id = 'tenant-alpha'
            result = smart_query.generate_sql_from_question('查询岗位清单', role='hr_admin')

        assert result is not None
        rules = captured['prompt']['rules']
        assert any('FROM 主表' in rule and 'WHERE' in rule for rule in rules)
        assert any('每个 JOIN 表' in rule and '自己的 JOIN ON' in rule for rule in rules)

    def test_executes_valid_select_and_returns_table_widget(self, model_db) -> None:
        from models import Job
        from services.assistant_core.skills import skill_smart_data_query

        model_db.session.add(Job(id='j-1', title='电子工程师', status='open', department='研发部'))
        model_db.session.add(Job(id='j-2', title='供应链总监', status='closed', department='供应链'))
        model_db.session.commit()

        result = skill_smart_data_query(
            {
                'question': '统计各状态岗位数量',
                'sql': 'SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status ORDER BY cnt DESC',
                'explanation': '按岗位状态聚合统计',
            },
            _ctx(),
        )

        assert result['rows_count'] == 2
        assert '只读 SQL 查询返回 2 行' in result['summary_hint']
        assert result['facts']['sql'].lower().startswith('select')
        assert result['widgets'][0]['type'] == 'data_table'
        assert {row['status'] for row in result['facts']['rows']} == {'open', 'closed'}

    def test_rejects_write_sql(self, model_db) -> None:
        from services.assistant_core.skills import skill_smart_data_query

        result = skill_smart_data_query(
            {'question': '删掉候选人', 'sql': 'DELETE FROM candidates WHERE status = "new"'},
            _ctx(),
        )

        assert result['rows_count'] == 0
        assert result['facts']['rejected'] is True
        assert '只支持只读 SELECT 查询' in result['summary_hint']

    @pytest.mark.parametrize('sql', [
        'SELECT SLEEP(30)',
        "SELECT GET_LOCK('smart-query-lock', 30)",
        "SELECT LOAD_FILE('/etc/passwd')",
        'SELECT BENCHMARK(1000000, SHA2(\'x\', 256))',
        'SELECT mutate_business_rows()',
        'SELECT id INTO @captured_job_id FROM jobs',
        'SELECT @captured_job_id := id FROM jobs',
        'SELECT * FROM jobs FOR SHARE',
        'SELECT * FROM jobs LOCK IN SHARE MODE',
    ])
    def test_rejects_stateful_or_resource_abusive_selects(self, model_db, sql) -> None:
        from services.assistant_core.skills import skill_smart_data_query

        result = skill_smart_data_query(
            {'question': 'unsafe read', 'sql': sql},
            _ctx(),
        )

        assert result['rows_count'] == 0
        assert result['facts']['rejected'] is True

    def test_tenant_context_requires_and_binds_explicit_scope(self, model_db) -> None:
        from models import Job
        from services.assistant_core.skills import skill_smart_data_query

        model_db.session.add_all([
            Job(id='j-alpha', tenant_id='tenant-alpha', title='Alpha Job', status='open'),
            Job(id='j-beta', tenant_id='tenant-beta', title='Beta Job', status='open'),
        ])
        model_db.session.commit()

        with current_app.test_request_context('/api/assistant/query'):
            g.tenant_id = 'tenant-alpha'
            unscoped = skill_smart_data_query(
                {'question': '查岗位', 'sql': 'SELECT id, title FROM jobs'},
                _ctx(),
            )
            scoped = skill_smart_data_query(
                {
                    'question': '查岗位',
                    'sql': (
                        'SELECT j.id, j.title FROM jobs j '
                        'WHERE j.tenant_id = :tenant_id'
                    ),
                },
                _ctx(),
            )

        assert unscoped['facts']['rejected'] is True
        assert scoped['facts']['ok'] is True
        assert scoped['facts']['rows'] == [{'id': 'j-alpha', 'title': 'Alpha Job'}]

    @pytest.mark.parametrize('sql', [
        (
            'SELECT j.id, j.tenant_id FROM jobs j '
            'WHERE (j.tenant_id = :tenant_id) IS FALSE'
        ),
        (
            'SELECT j.id, j3.tenant_id FROM jobs j '
            'JOIN jobs j2 ON j2.tenant_id = :tenant_id AND j2.id = j.id, jobs j3 '
            'WHERE j.tenant_id = :tenant_id'
        ),
        (
            'SELECT j.id FROM jobs j '
            'LEFT JOIN jobs j2 ON j.tenant_id = :tenant_id '
            'AND j2.tenant_id = :tenant_id AND j2.id = j.id'
        ),
        (
            'SELECT j.id, j2.id AS joined_id FROM jobs j '
            'LEFT JOIN jobs j2 ON j2.status = j.status '
            'LEFT JOIN jobs j3 ON j2.tenant_id = :tenant_id '
            'AND j3.tenant_id = :tenant_id AND j3.id = j.id '
            'WHERE j.tenant_id = :tenant_id'
        ),
    ])
    def test_tenant_context_rejects_scope_predicate_bypasses(self, model_db, sql) -> None:
        from models import Job
        from services.assistant_core.skills import skill_smart_data_query

        model_db.session.add_all([
            Job(id='j-scope-alpha', tenant_id='tenant-alpha', title='Alpha Job', status='open'),
            Job(id='j-scope-beta', tenant_id='tenant-beta', title='Beta Job', status='open'),
        ])
        model_db.session.commit()

        with current_app.test_request_context('/api/assistant/query'):
            g.tenant_id = 'tenant-alpha'
            result = skill_smart_data_query(
                {'question': '绕过企业范围', 'sql': sql},
                _ctx(),
            )

        assert result['rows_count'] == 0
        assert result['facts']['rejected'] is True

    def test_employee_role_gets_sensitive_columns_redacted(self, model_db) -> None:
        from models import Employee
        from services.assistant_core.skills import skill_smart_data_query

        model_db.session.add(Employee(id='e-1', name='张三', phone='13812345678', email='zhang@example.com'))
        model_db.session.commit()

        result = skill_smart_data_query(
            {'question': '查员工联系方式', 'sql': 'SELECT name, phone, email FROM employees'},
            _ctx(role='employee'),
        )

        row = result['facts']['rows'][0]
        assert row['phone'] != '13812345678'
        assert row['email'] != 'zhang@example.com'

    def test_uses_dedicated_readonly_engine_when_configured(self, model_db, monkeypatch) -> None:
        from models import Job
        from services.assistant_core import smart_query
        from services.assistant_core.skills import skill_smart_data_query

        model_db.session.add(Job(id='j-ro', title='只读岗位', status='open'))
        model_db.session.commit()
        readonly_uri = str(model_db.engine.url)
        monkeypatch.setenv('DB_READONLY_URI', readonly_uri)
        smart_query.reset_readonly_engine_for_tests()
        monkeypatch.setattr(smart_query, 'create_engine', lambda *args, **kwargs: model_db.engine)
        monkeypatch.setattr(
            model_db.session,
            'execute',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('smart query must not use write db.session when readonly engine is configured')),
        )

        result = skill_smart_data_query(
            {'question': '查岗位数量', 'sql': 'SELECT COUNT(*) AS cnt FROM jobs'},
            _ctx(),
        )

        assert result['rows_count'] == 1
        assert result['facts']['rows'][0]['cnt'] == 1

    def test_low_performance_attendance_cross_stat_uses_deterministic_template(self, model_db, monkeypatch) -> None:
        from datetime import date
        from models import AttendanceRecord, Employee, PerformanceReview
        from services.assistant_core import smart_query
        from services.assistant_core.skills import skill_smart_data_query

        monkeypatch.setattr(
            smart_query.llm_client,
            'json_chat_profile',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('deterministic smart query should not call SQL planner LLM')),
        )
        monkeypatch.setattr(
            smart_query.llm_client,
            'chat_profile',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('deterministic smart query should not call summary LLM')),
        )
        employee = Employee(id='e-low-att', employee_no='EA100', name='低绩效员工', status='active')
        review = PerformanceReview(id='pr-low-att', employee_id=employee.id, grade='D', final_score=62, status='completed')
        records = [
            AttendanceRecord(id='att-low-1', employee_id=employee.id, attendance_date=date(2026, 6, 1), status='late'),
            AttendanceRecord(id='att-low-2', employee_id=employee.id, attendance_date=date(2026, 6, 2), status='missing_card'),
            AttendanceRecord(id='att-low-3', employee_id=employee.id, attendance_date=date(2026, 6, 3), status='normal'),
        ]
        model_db.session.add(employee)
        model_db.session.add(review)
        model_db.session.add_all(records)
        model_db.session.commit()

        result = skill_smart_data_query({'question': '低绩效和考勤异常交叉统计一下'}, _ctx())

        assert result['rows_count'] == 1
        assert result['facts']['generated'] is True
        assert 'performance_reviews' in result['facts']['sql']
        assert result['facts']['rows'][0]['employee_name'] == '低绩效员工'
        assert result['facts']['rows'][0]['attendance_anomaly_count'] == 2
        assert '低绩效与考勤异常交叉统计返回 1 人' in result['summary_hint']


class TestSmartDataQueryRouting:
    def test_uncertain_system_query_can_fall_back_to_smart_sql(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner
        from services.assistant_core.intent_router.legacy_planner import build_route_decision
        from services.assistant_core.schemas import RouteDecision, ToolCallPlan

        def fake_plan(message, ctx):
            return RouteDecision(
                task_type='data_query',
                route_track='A_DATA_ACTION',
                intent='smart_analytics_query',
                confidence=0.86,
                risk_level='medium',
                tool_plan=[
                    ToolCallPlan(
                        step_id='smart_sql',
                        tool='smart_data_query',
                        purpose='query',
                        input={
                            'question': message,
                            'sql': 'SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status',
                            'explanation': '按状态统计岗位',
                        },
                        required=True,
                        risk_level='medium',
                    ),
                ],
                reason='test_llm_planner_smart_sql',
            )

        monkeypatch.setenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', '1')
        monkeypatch.setattr(llm_skill_planner, 'plan_with_llm', fake_plan)

        decision = build_route_decision('按岗位状态和部门交叉统计一下招聘需求', _ctx())

        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.tool_plan[0].tool == 'smart_data_query'

