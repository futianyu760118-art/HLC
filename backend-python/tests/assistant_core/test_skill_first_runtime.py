"""Regression tests for the Skill-first Agent Runtime."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

from services.assistant_core.schemas import AssistantContext, ExecutionResult
from services.assistant_core.skill_first import cards, planner, semantic_index
from services.assistant_core.skill_first.skill_retriever import retrieve_skills
from services.assistant_core.skill_first.understanding import UnderstandingResult
from services.assistant_core.skill_first.observability import REQUIRED_TRACE_FIELDS


def _ctx(
    session_id: str = 's-skill-first',
    role: str = 'hr_admin',
    user_id: str = 'u-skill-first',
) -> AssistantContext:
    return AssistantContext(user_id=user_id, role=role, session_id=session_id, request_id='req-skill-first')


def _job_page_ctx(session_id: str = 's-skill-first-page') -> AssistantContext:
    ctx = _ctx(session_id=session_id)
    ctx.client_context = {
        'path': '/job-manage',
        'moduleId': 'job-manage',
        'moduleName': '岗位管理',
        'pageTitle': '岗位管理 - 恒聘通',
    }
    return ctx


def _kernel_node_names(result: ExecutionResult) -> list[str]:
    trace = result.copilot['routeTrace']
    return [node['node'] for node in trace['kernel']['nodes']]


@pytest.fixture()
def model_db(monkeypatch):
    from models import User, db

    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        db.session.add(User(
            id='u-skill-first',
            email='skill-first@example.com',
            password_hash='x',
            name='Skill First HR',
            role='hr_admin',
        ))
        db.session.commit()
        monkeypatch.setattr(
            'services.assistant_core.skills.business_now',
            lambda: datetime(2026, 6, 3, 9, 0, 0),
            raising=False,
        )
        monkeypatch.setattr(
            'services.assistant_core.agent_kernel.confirmations.business_now',
            lambda: datetime(2026, 6, 3, 9, 0, 0),
            raising=False,
        )
        yield db
        db.session.remove()
        db.drop_all()


def _seed_sunyue_recruitment_data(model_db) -> None:
    from datetime import datetime
    from models import Candidate, Job, Resume, db

    electronic_job = Job(
        id='job-sf-electronic',
        title='电子工程师',
        department='研发部',
        status='open',
        requirements='熟悉模拟电路、EMC整改、量产导入和硬件调试。',
        scoring_criteria=['硬件调试', 'EMC整改', '量产导入'],
        created_at=datetime(2026, 5, 20, 9, 0),
    )
    product_job = Job(
        id='job-sf-product',
        title='产品经理',
        department='产品部',
        status='open',
        requirements='负责需求分析、产品规划和跨部门推进。',
        created_at=datetime(2026, 5, 21, 9, 0),
    )
    resume = Resume(
        id='resume-sf-sunyue',
        job_id='job-sf-product',
        candidate_name='孙悦',
        file_url='/uploads/sunyue.pdf',
        ai_analysis={
            'score': 92,
            'matchDegree': 90,
            'skills': ['需求分析', '用户研究', '跨部门协作', '硬件项目协同'],
            'summary': '产品规划能力强，参与过硬件研发协同项目。',
            'strengths': ['业务拆解清晰', '推进能力强'],
            'weaknesses': ['硬件底层设计经验需要复核'],
            'recommendation': '建议重点跟进入职材料及产品培训。',
            'interviewFocus': ['硬件项目协作深度', '需求优先级判断'],
        },
        created_at=datetime(2026, 5, 28, 10, 0),
    )
    candidate = Candidate(
        id='cand-sf-sunyue',
        resume_id='resume-sf-sunyue',
        job_id='job-sf-product',
        name='孙悦',
        status='converted',
        source='简历上传',
        match_records=[{'score': 92, 'matchDegree': 90}],
        ai_summary='产品规划能力强，参与过硬件研发协同项目。',
        ai_recommendation='建议重点跟进入职材料及产品培训。',
        created_at=datetime(2026, 5, 28, 11, 0),
    )
    db.session.add_all([electronic_job, product_job, resume, candidate])
    db.session.commit()


def _seed_electronic_match_matrix_data(model_db) -> None:
    from models import Candidate, Job, Resume, db

    job = Job(
        id='job-sf-matrix-electronic',
        title='电子工程师',
        department='研发部',
        status='open',
        requirements='熟悉硬件调试、EMC、量产导入。',
        scoring_criteria=['硬件调试', 'EMC', '量产导入'],
        created_at=datetime(2026, 5, 20, 9, 0),
    )
    resumes = [
        Resume(
            id='resume-sf-denghao',
            job_id=job.id,
            candidate_name='邓浩',
            file_url='/uploads/denghao.pdf',
            ai_analysis={'score': 91, 'matchDegree': 94, 'skills': ['硬件调试', 'EMC']},
            created_at=datetime(2026, 5, 22, 10, 0),
        ),
        Resume(
            id='resume-sf-yanglin',
            job_id=job.id,
            candidate_name='杨琳',
            file_url='/uploads/yanglin.pdf',
            ai_analysis={'score': 84, 'matchDegree': 88, 'skills': ['量产导入']},
            created_at=datetime(2026, 5, 24, 10, 0),
        ),
    ]
    candidates = [
        Candidate(
            id='cand-sf-denghao',
            resume_id='resume-sf-denghao',
            job_id=job.id,
            name='邓浩',
            status='screening',
            match_records=[{'score': 91, 'matchDegree': 94}],
            created_at=datetime(2026, 5, 22, 11, 0),
        ),
        Candidate(
            id='cand-sf-yanglin',
            resume_id='resume-sf-yanglin',
            job_id=job.id,
            name='杨琳',
            status='screening',
            match_records=[{'score': 84, 'matchDegree': 88}],
            created_at=datetime(2026, 5, 24, 11, 0),
        ),
    ]
    db.session.add(job)
    db.session.add_all(resumes + candidates)
    db.session.commit()


def _seed_attendance_reminder_data(model_db) -> None:
    from models import AttendanceRecord, Department, Employee, db

    department = Department(id='d-sf-attendance', name='研发部', status='active')
    employees = [
        Employee(id='e-sf-wmh-att', employee_no='EA001', name='吴明华', status='active', department_id=department.id, job_title='后端工程师'),
        Employee(id='e-sf-linyao-att', employee_no='EA002', name='林瑶', status='active', department_id=department.id, job_title='HRBP'),
        Employee(id='e-sf-lisi-att', employee_no='EA003', name='李四', status='active', department_id=department.id, job_title='测试工程师'),
    ]
    records = [
        AttendanceRecord(id='att-sf-wmh-1', employee_id='e-sf-wmh-att', attendance_date=date(2026, 6, 1), status='late'),
        AttendanceRecord(id='att-sf-wmh-2', employee_id='e-sf-wmh-att', attendance_date=date(2026, 6, 2), status='late'),
        AttendanceRecord(id='att-sf-linyao-1', employee_id='e-sf-linyao-att', attendance_date=date(2026, 6, 1), status='late'),
        AttendanceRecord(id='att-sf-lisi-1', employee_id='e-sf-lisi-att', attendance_date=date(2026, 6, 1), status='normal'),
    ]
    db.session.add(department)
    db.session.add_all(employees + records)
    db.session.commit()


def test_capability_questions_do_not_route_to_employee_evidence_on_job_page(model_db, monkeypatch) -> None:
    from services.assistant_core import copilot_orchestrator

    _seed_sunyue_recruitment_data(model_db)
    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', lambda *args, **kwargs: None)

    for message in ('你能做什么？', '在这个页面你能做什么'):
        payload = copilot_orchestrator.query(
            user_id='u-skill-first',
            message=message,
            session_id='s-skill-first-capability',
            client_context=_job_page_ctx().client_context,
        )

        assert payload['copilot']['routePath'] == 'skill_first_runtime'
        assert payload['meta']['routeDecision']['intent'] == 'system.page_capability'
        assert payload['meta']['usedSkills'] != ['employee_evidence_bundle']
        assert '岗位管理' in payload['summary']
        assert '在招岗位' in payload['summary']


def test_recent_resume_days_slot_preserves_explicit_ten_days(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    seen: dict = {}

    def fake_execute(self, tool, params, ctx):
        seen['tool'] = tool
        seen['params'] = dict(params)
        return {'ok': True, 'tool': tool, 'data': {'summary_hint': '近10天简历 0 份。'}, 'rows_count': 0}

    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)

    result = runtime.try_run('最近10天我们收到了哪些简历', _ctx())

    assert result is not None
    assert result.copilot['routeTrace']['selected_skill'] == 'candidate.recent_resumes'
    assert seen == {'tool': 'resume_analysis', 'params': {'recent_days': 10, 'top_n': 10, 'question': '最近10天我们收到了哪些简历'}}


def test_agent_kernel_nodes_are_recorded_for_ordinary_skill_first_requests(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.ToolExecutor, 'execute', lambda self, tool, params, ctx: {
        'ok': True,
        'tool': tool,
        'data': {'facts': {'items': []}, 'widgets': []},
    })
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('最近10天我们收到了哪些简历', _ctx())

    assert result is not None
    trace = result.copilot['routeTrace']
    assert trace['kernel']['name'] == 'hrm_agent_kernel'
    node_names = _kernel_node_names(result)
    assert node_names[:5] == [
        'confirmed_action',
        'understanding',
        'skill_retrieval',
        'skill_provider',
        'planning',
    ]
    assert 'slot_reference' in node_names
    assert node_names.index('skill_retrieval') < node_names.index('planning')
    assert node_names.index('skill_retrieval') < node_names.index('skill_provider')
    assert node_names.index('skill_provider') < node_names.index('planning')
    assert node_names.index('planning') < node_names.index('slot_reference')
    assert node_names.index('slot_reference') < node_names.index('decision')
    assert 'decision' in node_names
    assert 'skill_playbook' in node_names
    assert 'execution' in node_names
    assert 'answer_synthesis' in node_names
    assert 'output_verification' in node_names
    assert node_names.index('decision') < node_names.index('skill_playbook')
    assert node_names.index('skill_playbook') < node_names.index('permission_gate')
    assert node_names.index('permission_gate') < node_names.index('execution')
    assert node_names.index('execution') < node_names.index('answer_synthesis')
    assert node_names.index('answer_synthesis') < node_names.index('output_verification')
    assert node_names.index('output_verification') < node_names.index('observability')
    assert node_names[-1] == 'observability'
    assert trace['skill_provider']['record_count'] > 0
    assert trace['skill_provider']['candidate_records'][0]['skill_id'] == 'candidate.recent_resumes'
    assert trace['skill_provider']['selected']['skill_id'] == 'candidate.recent_resumes'
    assert trace['skill_provider']['selected']['executor_metadata']['executor_tool'] == 'resume_analysis'
    assert trace['tool_workbench'][0]['provider_contract_checked'] is True
    assert trace['tool_workbench'][0]['provider_skill'] == 'candidate.recent_resumes'
    assert trace['tool_workbench'][0]['provider_tool'] == 'resume_analysis'
    assert trace['skill_playbook']['skill_id'] == 'candidate.recent_resumes'
    assert trace['skill_playbook']['executor_tool'] == 'resume_analysis'
    assert trace['skill_playbook']['mode'] == 'read_only_execution'
    assert 'ground_answer_in_tool_outputs' in trace['skill_playbook']['evidence_plan']
    assert trace['skill_playbook']['diagnostics']['source'] == 'deterministic'
    assert trace['slot_reference_result']['resolution_source'] == 'planner_guarded_slots+schema+workset'
    assert trace['slot_reference_result']['refiner']['status'] in {'skipped_not_needed', 'llm_unavailable'}


def test_product_skill_card_invoke_uses_agent_kernel_provider_workbench(model_db, monkeypatch) -> None:
    from services.assistant_core import copilot_orchestrator
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', lambda self, tool, params, ctx: {
        'ok': True,
        'tool': tool,
        'data': {'summary_hint': '全局搜索完成。', 'entities': [], 'widgets': []},
        'rows_count': 1,
    })

    payload = copilot_orchestrator.invoke_skill(
        skill_id='global_search',
        params={'keyword': '吴明华'},
        user_id='u-skill-first',
        session_id='s-skill-direct',
        request_id='req-skill-direct',
    )

    trace = payload['copilot']['routeTrace']
    assert payload['copilot']['routePath'] == 'skill_first_runtime'
    assert payload['copilot']['agentSkillInvoke'] == 'system.global_search'
    assert trace['selected_skill'] == 'system.global_search'
    assert trace['skill_provider']['schema_mode'] == 'direct_skill'
    assert trace['skill_provider']['selected']['executor_metadata']['executor_tool'] == 'global_search'
    assert trace['tool_workbench'][0]['provider_contract_checked'] is True
    assert payload['meta']['routeDecision']['intent'] == 'system.global_search'


def test_product_skill_card_unknown_skill_uses_kernel_direct_invoke_boundary(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.invoke_registered_skill(
        '__unknown_launcher__',
        {},
        _ctx(session_id='s-direct-unknown'),
        display_name='未知启动卡',
    )

    assert result.error_code == 'unknown_skill'
    trace = result.copilot['routeTrace']
    assert trace['fallback_reason'] == 'direct_skill_unknown_agent_card'
    assert trace['direct_invoke']['source'] == 'agent_kernel.direct_invoke.unknown_skill'
    assert trace['final_executor'] == 'agent_kernel.policy.clarification'
    assert trace['output_verification_result'] == 'ok'


def test_product_skill_card_invoke_does_not_use_legacy_executor_direct_call() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    source = (backend_root / 'services' / 'assistant_core' / 'copilot_orchestrator.py').read_text(encoding='utf-8')

    assert 'executor.execute(' not in source
    assert not re.search(r'^\s*from\s+\.\s+import\s+.*\bexecutor\b', source, re.M)
    assert 'skill_first_runtime.invoke_registered_skill' in source


def test_persist_turn_uses_kernel_context_for_focus_and_pending_action(monkeypatch) -> None:
    from services.assistant_core.schemas import ExecutionResult, RouteDecision
    from services.assistant_core.skill_first import runtime

    captured: dict = {}
    decision = RouteDecision(
        task_type='action',
        route_track='A_DATA_ACTION',
        intent='interview.schedule_confirm_create',
        confidence=0.9,
        risk_level='high',
    )
    result = ExecutionResult(
        summary='待确认面试安排',
        entities=[{'type': 'candidate', 'id': 'c-1', 'title': '孙悦'}],
        session_id='s-persist-kernel-context',
        route_decision=decision,
        requires_confirmation=True,
        copilot={'routeTrace': {'selected_skill': 'interview.schedule_confirm_create'}},
    )
    result._pending_action = {'id': 'act-1', 'tools': [{'tool': 'interview_create', 'input': {}}]}

    def fake_save_turn(**kwargs):
        captured.update(kwargs)
        return kwargs.get('session_id')

    monkeypatch.setattr(runtime.memory, 'save_turn', fake_save_turn)

    runtime.persist_turn('给孙悦安排面试', _ctx(session_id='s-persist-kernel-context'), result)

    meta = captured['metadata']
    assert meta['routePath'] == 'skill_first_runtime'
    assert meta['pendingAction']['id'] == 'act-1'
    assert meta['lastFocus'] == {'entity_type': 'candidate', 'entity_id': 'c-1', 'name': '孙悦'}
    assert captured['worksets'] == []


def test_compat_orchestrator_run_uses_agent_kernel_not_legacy_router(monkeypatch) -> None:
    import services.assistant_core.legacy_orchestrator as legacy_orchestrator
    from services.assistant_core import orchestrator
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(
        legacy_orchestrator,
        'run',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('legacy orchestrator must be explicit only')),
    )
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', lambda self, tool, params, ctx: {
        'ok': True,
        'tool': tool,
        'data': {'summary_hint': '待办审批共有 1 条。', 'entities': [], 'widgets': []},
        'rows_count': 1,
    })
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = orchestrator.run('我这边还有哪些待办审批', _ctx())

    assert result.copilot['routePath'] == 'skill_first_runtime'
    assert result.copilot['routeTrace']['kernel']['name'] == 'hrm_agent_kernel'
    assert result.copilot['routeTrace']['selected_skill'] == 'approval.todo'


def test_compat_orchestrator_module_is_kernel_shim_without_legacy_imports() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    source = (backend_root / 'services' / 'assistant_core' / 'orchestrator.py').read_text(encoding='utf-8')

    assert 'legacy_orchestrator.run' in source
    assert 'skill_first_runtime.try_run' in source
    assert not re.search(r'^\s*from\s+\.\s*intent_router\b', source, re.M)
    assert 'build_route_decision' not in source
    assert 'executor.execute(' not in source


def test_compat_router_route_uses_skill_first_planner_not_legacy_router(monkeypatch) -> None:
    from services.assistant_core import legacy_router, router

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setattr(
        legacy_router,
        'route',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('public router.route must not call legacy_router.route')),
    )

    result = router.route('现在在招聘的岗位有哪些', _ctx())

    assert result.route_path == 'skill_first_router_shim'
    assert result.intent == 'recruitment.open_jobs'
    assert result.top_k
    assert result.rule_matched is False


def test_compat_intent_router_planner_uses_skill_first_not_legacy_planner(monkeypatch) -> None:
    from services.assistant_core.intent_router import legacy_planner, planner

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setattr(
        legacy_planner,
        'build_route_decision',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('public intent_router.planner must not call legacy_planner')),
    )

    decision = planner.build_route_decision('现在在招聘的岗位有哪些', _ctx())

    assert decision.intent == 'recruitment.open_jobs'
    assert decision.reason.endswith('intent_router_planner_shim')
    assert decision.tool_plan


def test_compat_intent_router_pipeline_uses_skill_first_not_legacy_pipeline(monkeypatch) -> None:
    from services.assistant_core.intent_router import legacy_pipeline, pipeline

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setattr(
        legacy_pipeline,
        'route',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('public intent_router.pipeline must not call legacy_pipeline')),
    )

    result = pipeline.route('现在在招聘的岗位有哪些', _ctx())

    assert result.route_path == 'skill_first_pipeline_shim'
    assert result.intent == 'recruitment.open_jobs'
    assert result.top_k
    assert result.rule_matched is False
    assert result.entity_resolved['source'] == 'skill_first_pipeline_shim'


def test_compat_intent_router_routing_uses_skill_first_not_legacy_dispatcher(monkeypatch) -> None:
    from services.assistant_core.intent_router import legacy_adapter, legacy_pipeline, legacy_routing, routing

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setattr(
        legacy_pipeline,
        'route',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('public intent_router.routing must not call legacy_pipeline')),
    )
    monkeypatch.setattr(
        legacy_routing,
        'route',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('public intent_router.routing must not call legacy_routing')),
    )
    monkeypatch.setattr(
        legacy_adapter,
        'legacy_route',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('public intent_router.routing must not call legacy_adapter')),
    )

    result = routing.route('现在在招聘的岗位有哪些', _ctx())

    assert result.route_path == 'skill_first_pipeline_shim'
    assert result.intent == 'recruitment.open_jobs'
    assert result.top_k


def test_public_intent_router_pipeline_and_routing_are_skill_first_shims_without_legacy_imports() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    paths = [
        backend_root / 'services' / 'assistant_core' / 'intent_router' / 'pipeline.py',
        backend_root / 'services' / 'assistant_core' / 'intent_router' / 'routing.py',
    ]
    forbidden = [
        r'\blegacy_pipeline\b',
        r'\blegacy_routing\b',
        r'\blegacy_adapter\b',
        r'\bfeature_flag\b',
        r'\blegacy_router\b',
        r'\bfastpath\b',
        r'\bretriever\b',
        r'\breranker\b',
        r'\bconfidence_gate\b',
        r'\bpermission_gate\b',
    ]

    for path in paths:
        source = path.read_text(encoding='utf-8')
        for token in forbidden:
            assert not re.search(token, source), f'{path} must not reference retired router token {token!r}'
        assert 'skill_first' in source or 'Skill-first' in source


def test_public_run_query_compat_entry_uses_agent_kernel_not_legacy_orchestrator(monkeypatch) -> None:
    import services.assistant_core as assistant_core
    from services.assistant_core import orchestrator
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(orchestrator, 'run', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('legacy orchestrator must not be called')))
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', lambda self, tool, params, ctx: {
        'ok': True,
        'tool': tool,
        'data': {'facts': {'items': []}, 'widgets': []},
    })
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = assistant_core.run_query('最近10天我们收到了哪些简历', _ctx())

    assert result is not None
    assert result.copilot['routePath'] == 'skill_first_runtime'
    assert result.copilot['routeTrace']['kernel']['name'] == 'hrm_agent_kernel'
    assert result.copilot['routeTrace']['selected_skill'] == 'candidate.recent_resumes'


def test_answer_synthesis_runs_as_independent_kernel_node(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.skill_first import answer_synthesizer
    captured_messages: list = []

    def fake_json_chat_profile(*args, **kwargs):
        use_case = kwargs.get('use_case')
        if use_case == 'skill_first_understanding':
            return {
                'normalized_query': '最近10天收到的简历',
                'intent_summary': '查询最近收到的简历',
                'domain_hints': ['candidate', 'recruitment'],
                'entity_mentions': [],
                'reference_hints': {},
                'slot_hints': {'recent_days': 10, 'top_n': 10},
                'candidate_skill_hints': ['candidate.recent_resumes'],
                'missing_information': [],
                'confidence': 0.86,
            }
        if use_case == 'skill_first_planner':
            return {
                'normalized_query': '最近10天收到的简历',
                'selected_skill': 'candidate.recent_resumes',
                'confidence': 0.91,
                'slot_values': {'recent_days': 10, 'top_n': 10, 'question': '最近10天我们收到了哪些简历'},
                'missing_slots': [],
                'route_reason': 'llm_selected_recent_resume_query',
                'rejected_skills': [],
            }
        return None

    def fake_execute(self, tool, params, ctx):
        return {
            'ok': True,
            'tool': tool,
            'data': {
                'summary_hint': '近 10 天简历 2 份。',
                'facts': {'items': [{'name': '候选人A'}, {'name': '候选人B'}]},
                'widgets': [],
            },
            'rows_count': 2,
        }

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_SYNTHESIS', '1')
    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_UNDERSTANDING', raising=False)
    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_LLM', raising=False)
    monkeypatch.setattr(runtime.understand_query.__globals__['llm_client'], 'is_available', lambda: True)
    monkeypatch.setattr(runtime.plan_skill.__globals__['llm_client'], 'is_available', lambda: True)
    monkeypatch.setattr(runtime.understand_query.__globals__['llm_client'], 'json_chat_profile', fake_json_chat_profile)
    monkeypatch.setattr(runtime.plan_skill.__globals__['llm_client'], 'json_chat_profile', fake_json_chat_profile)
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(answer_synthesizer.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        answer_synthesizer.llm_client,
        'chat_profile',
        lambda profile, messages, **kwargs: (
            captured_messages.append(messages)
            or {'content': 'LLM 证据化回答：近 10 天简历 2 份。'}
        ),
    )
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('最近10天我们收到了哪些简历', _ctx())

    assert result is not None
    trace = result.copilot['routeTrace']
    node_names = _kernel_node_names(result)
    assert node_names.index('execution') < node_names.index('answer_synthesis')
    assert node_names[-1] == 'observability'
    assert trace['answer_synthesis'] == {
        'source': 'llm',
        'use_case': 'skill_first_grounded_answer',
        'applied': True,
        'playbook_used': True,
    }
    synthesis_payload = json.loads(captured_messages[0][-1]['content'])
    assert synthesis_payload['skill_playbook']['skill_id'] == 'candidate.recent_resumes'
    assert synthesis_payload['skill_playbook']['executor_tool'] == 'resume_analysis'
    assert result.summary == 'LLM 证据化回答：近 10 天简历 2 份。'


def test_skill_playbook_llm_enrichment_cannot_change_executor(monkeypatch) -> None:
    from services.assistant_core.agent_kernel.skill_playbook import build_playbook
    from services.assistant_core.schemas import RouteDecision, ToolCallPlan
    from services.assistant_core.skill_first.cards import get_card

    card = get_card('candidate.recent_resumes')
    assert card is not None
    decision = RouteDecision(
        task_type='data_query',
        route_track='A_DATA_ACTION',
        intent='candidate.recent_resumes',
        confidence=0.9,
        risk_level='medium',
        tool_plan=[ToolCallPlan(
            step_id='candidate_recent_resumes',
            tool='resume_analysis',
            input={'recent_days': 10, 'top_n': 10},
            risk_level='medium',
        )],
    )

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_PLAYBOOK_LLM', '1')
    monkeypatch.setattr('services.assistant_core.agent_kernel.skill_playbook.llm_client.is_available', lambda: True)
    monkeypatch.setattr(
        'services.assistant_core.agent_kernel.skill_playbook.llm_client.json_chat_profile',
        lambda *args, **kwargs: {
            'executor_tool': 'candidate_evidence_bundle',
            'evidence_plan': ['重点看近 10 天新增简历质量'],
            'answer_guidance': ['先说数量再说风险'],
            'followup_prompts': ['继续看第一份简历'],
        },
    )
    monkeypatch.setattr(
        'services.assistant_core.agent_kernel.skill_playbook.llm_client.last_call_meta',
        lambda: {'status': 'success', 'model': 'unit-test'},
    )

    playbook = build_playbook(
        message='最近10天我们收到了哪些简历',
        ctx=_ctx(),
        card=card,
        decision=decision,
        provider_selected={
            'skill_id': 'candidate.recent_resumes',
            'executor_metadata': {'executor_tool': 'resume_analysis'},
            'model_schema': {'executor_tool': 'resume_analysis', 'tool_schema': {'recent_days': 'integer'}},
        },
    )

    payload = playbook.to_dict()
    assert payload['executor_tool'] == 'resume_analysis'
    assert payload['diagnostics']['source'] == 'llm_enriched'
    assert '重点看近 10 天新增简历质量' in payload['evidence_plan']
    assert '先说数量再说风险' in payload['answer_guidance']


def test_agent_kernel_playbook_guide_registry_replaces_legacy_prompt_block() -> None:
    from services.assistant_core.agent_kernel.skill_playbook import (
        build_card_playbook_guide_registry,
        format_available_skill_guides,
    )

    registry = build_card_playbook_guide_registry(['candidate.recent_resumes'])
    guide = registry.get('candidate.recent_resumes')

    assert guide is not None
    assert guide.source == 'agent_skill_card'
    assert 'Execution Contract' in guide.body

    formatted = format_available_skill_guides(registry)
    assert '<agent_kernel_skill_guides>' in formatted
    assert 'candidate.recent_resumes' in formatted
    assert 'available_skill_playbooks' not in formatted


def test_named_candidate_interview_create_uses_candidate_evidence_without_direct_write(model_db, monkeypatch) -> None:
    from models import Interview
    from services.assistant_core.skill_first import runtime

    _seed_sunyue_recruitment_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('孙悦，我想给他安排一个明天早晨八点的面试', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert result.widgets[0]['type'] == 'confirmation_card'
    assert result.copilot['routeTrace']['selected_skill'] == 'interview.schedule_confirm_create'
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'interview_create'
    assert pending_tool['input']['resume_id'] == 'resume-sf-sunyue'
    assert pending_tool['input']['job_id'] == 'job-sf-product'
    assert pending_tool['input']['scheduled_at'].endswith('T08:00:00')
    assert Interview.query.count() == 0


def test_candidate_resume_lookup_persists_focus_for_followup_interview_action(model_db, monkeypatch) -> None:
    from services.assistant_core import copilot_orchestrator

    _seed_sunyue_recruitment_data(model_db)
    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', lambda *args, **kwargs: None)

    first = copilot_orchestrator.query(user_id='u-skill-first', message='孙悦的简历帮我找一下')
    followup = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='帮我给孙悦安排一个明天早晨八点的面试',
        session_id=first['sessionId'],
    )

    assert first['meta']['routeDecision']['intent'] == 'candidate.resume_analysis'
    assert any(entity['title'] == '孙悦' for entity in first['entities'])
    assert followup['copilot']['routePath'] == 'skill_first_runtime'
    assert followup['meta']['routeDecision']['intent'] == 'interview_schedule'
    assert followup['meta']['requiresConfirmation'] is True
    assert followup['meta']['routeDecision']['toolPlan'][0]['tool'] == 'interview_create'
    assert '孙悦' in followup['summary']
    assert '08:00' in followup['summary']


def test_candidate_resume_lookup_persists_focus_for_followup_evaluation(model_db, monkeypatch) -> None:
    from services.assistant_core import copilot_orchestrator

    _seed_sunyue_recruitment_data(model_db)
    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', lambda *args, **kwargs: None)

    first = copilot_orchestrator.query(user_id='u-skill-first', message='孙悦的简历帮我找一下')
    followup = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='分析一下这个人怎么样',
        session_id=first['sessionId'],
    )

    trace = followup['copilot']['routeTrace']
    assert followup['copilot']['routePath'] == 'skill_first_runtime'
    assert followup['meta']['routeDecision']['intent'] == 'candidate.evaluation'
    assert trace['skill_refinement_result']['selected_skill'] == 'candidate.evaluation'
    assert followup['meta']['routeDecision']['toolPlan'][0]['tool'] == 'candidate_evidence_bundle'
    assert followup['meta']['routeDecision']['toolPlan'][0]['input']['candidate_id'] == 'cand-sf-sunyue'
    assert '孙悦' in followup['summary']


def test_open_job_listing_is_not_stolen_by_candidate_match(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('现在在招聘的岗位有哪些', _job_page_ctx())

    assert result is not None
    trace = result.copilot['routeTrace']
    assert trace['selected_skill'] == 'recruitment.open_jobs'
    assert result.route_decision.tool_plan[0].tool == 'recruitment_search'
    assert result.route_decision.tool_plan[0].input['module'] == 'jobs'
    assert result.route_decision.tool_plan[0].input['status'] == 'open'
    assert 'recruitment.job_candidate_match' in trace['top_k_skills']
    assert trace['top_k_skills'].index('recruitment.open_jobs') < trace['top_k_skills'].index('recruitment.job_candidate_match')


def test_unsupported_write_intent_is_blocked_even_when_planner_cannot_select_skill(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', lambda *args, **kwargs: None)

    result = runtime.try_run('把邓浩的面试删除', _ctx())

    assert result is not None
    assert result.error_code == 'write_intent_blocked'
    assert result.route_decision is not None
    assert result.route_decision.task_type == 'forbidden'
    assert result.to_response(include_meta=True)['meta']['errorCode'] == 'write_intent_blocked'
    assert result.copilot['routeTrace']['final_executor'] == 'guardrails.detect_write_intent'
    assert any(node['status'] == 'blocked_write_intent' for node in result.copilot['routeTrace']['kernel']['nodes'])


@pytest.mark.parametrize(
    ('question', 'expected_job_keyword', 'expected_requirement'),
    [
        ('孙悦的个人能力怎么样，符合我们的电子工程师岗位要求吗', '电子工程师', '熟悉模拟电路'),
        ('孙悦的个人能力是否符合我们公司的产品经理岗位要求', '产品经理', '负责需求分析'),
    ],
)
def test_candidate_job_fit_question_uses_target_job_evidence_not_empty_recruitment_search(
    model_db,
    monkeypatch,
    question: str,
    expected_job_keyword: str,
    expected_requirement: str,
) -> None:
    from services.assistant_core.skill_first import runtime

    _seed_sunyue_recruitment_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run(question, _ctx())

    assert result is not None
    assert result.copilot['routeTrace']['selected_skill'] == 'candidate.job_fit'
    assert result.trace[0].skill == 'candidate_evidence_bundle'
    assert result.route_decision.tool_plan[0].input.get('keyword') == '孙悦'
    assert result.route_decision.tool_plan[0].input.get('job_keyword') == expected_job_keyword
    assert '孙悦' in result.summary
    assert f'{expected_job_keyword}要求' in result.summary
    assert expected_requirement in result.summary
    assert any(entity['type'] == 'candidate' and entity['title'] == '孙悦' for entity in result.entities)


def test_candidate_job_fit_does_not_substitute_other_candidate_when_named_person_missing(
    model_db,
    monkeypatch,
) -> None:
    from services.assistant_core.skill_first import runtime

    _seed_electronic_match_matrix_data(model_db)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('孙悦的个人能力怎么样，符合我们的电子工程师岗位要求吗', _ctx())

    assert result is not None
    assert result.copilot['routeTrace']['selected_skill'] == 'candidate.job_fit'
    assert result.route_decision.tool_plan[0].input['keyword'] == '孙悦'
    assert result.route_decision.tool_plan[0].input['job_keyword'] == '电子工程师'
    assert '未找到与“孙悦”关联的候选人或简历' in result.summary
    assert '罗伟' not in result.summary
    assert not any(entity.get('title') == '罗伟' for entity in result.entities)


def test_ui_attendance_employee_evidence_keeps_employee_keyword_and_rich_evidence(
    model_db,
    monkeypatch,
) -> None:
    from services.assistant_core.skill_first import runtime

    _seed_attendance_reminder_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('吴明华最近考勤异常吗？请给证据，并说明相关入口。', _ctx())

    assert result is not None
    assert result.copilot['routeTrace']['selected_skill'] == 'attendance.employee_evidence'
    assert result.route_decision.tool_plan[0].tool == 'employee_attendance_evidence'
    assert result.route_decision.tool_plan[0].input['keyword'] == '吴明华'
    assert result.trace[0].skill == 'employee_attendance_evidence'
    assert any(entity['type'] == 'employee' and entity['title'] == '吴明华' for entity in result.entities)
    assert any(widget.get('type') == 'table' for widget in result.widgets)
    assert any(widget.get('type') == 'source_citations' for widget in result.widgets)
    assert '吴明华' in result.summary


def test_ui_job_candidate_match_uses_job_match_skill_and_records_workset(
    model_db,
    monkeypatch,
) -> None:
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.response_contract import apply_response_contract

    _seed_electronic_match_matrix_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    ctx = _ctx()

    result = runtime.try_run('电子工程师岗位最近候选人谁更合适？给对比矩阵', ctx)
    apply_response_contract(result, ctx, message='电子工程师岗位最近候选人谁更合适？给对比矩阵')

    assert result is not None
    assert result.copilot['routeTrace']['selected_skill'] == 'recruitment.job_candidate_match'
    assert result.route_decision.tool_plan[0].tool == 'recruitment_match_matrix'
    assert result.route_decision.tool_plan[0].input['keyword'] == '电子工程师'
    assert result.trace[0].skill == 'recruitment_match_matrix'
    assert any(entity['title'] == '邓浩' for entity in result.entities)
    assert any(widget.get('type') in {'table', 'comparison_matrix'} for widget in result.widgets)
    assert any(widget.get('type') == 'source_citations' for widget in result.widgets)
    assert result.worksets
    assert any(block.get('kind') == 'workset' for block in result.render_blocks)


def test_workset_second_candidate_followup_refines_to_candidate_evaluation(
    model_db,
    monkeypatch,
) -> None:
    from services.assistant_core.skill_first import runtime

    _seed_electronic_match_matrix_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    ctx = _ctx(session_id='s-skill-first-workset-refine')

    first = runtime.try_run('电子工程师岗位最近候选人谁更合适？给对比矩阵', ctx)
    assert first is not None
    assert first.copilot['routeTrace']['selected_skill'] == 'recruitment.job_candidate_match'
    assert first.worksets

    followup = runtime.try_run('第二个人风险和推进建议', ctx)

    assert followup is not None
    trace = followup.copilot['routeTrace']
    assert trace['selected_skill'] == 'candidate.evaluation'
    assert trace['skill_refinement_result']['selected_skill'] == 'candidate.evaluation'
    assert followup.route_decision.tool_plan[0].tool == 'candidate_evidence_bundle'
    assert followup.route_decision.tool_plan[0].input['candidate_id'] == 'cand-sf-yanglin'
    assert '杨琳' in followup.summary


def test_workset_single_candidate_pronoun_followup_reaches_interview_confirmation(
    model_db,
    monkeypatch,
) -> None:
    from services.assistant_core import copilot_orchestrator

    _seed_electronic_match_matrix_data(model_db)
    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', lambda *args, **kwargs: None)

    first = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='电子工程师岗位最近候选人谁更合适？给对比矩阵',
        session_id='s-pronoun-interview',
    )
    second = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='第二个人风险和推进建议',
        session_id=first['sessionId'],
    )
    third = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='给他安排明天早晨八点面试',
        session_id=second['sessionId'],
    )

    assert third['copilot']['routePath'] == 'skill_first_runtime'
    assert third['copilot']['routeTrace']['selected_skill'] == 'interview.schedule_confirm_create'
    assert third['meta']['requiresConfirmation'] is True
    assert third['meta']['routeDecision']['toolPlan'][0]['tool'] == 'interview_create'
    assert third['meta']['routeDecision']['requiredContext'] == ['latest_workset']
    assert any(block.get('kind') == 'confirmation' for block in third.get('renderBlocks') or [])
    from models import AssistantSession
    session = AssistantSession.query.get(third['sessionId'])
    pending = (session.messages[-1]['meta'] or {})['pendingAction']
    assert pending['tools'][0]['input']['resume_id'] == 'resume-sf-yanglin'
    assert pending['tools'][0]['input']['job_id'] == 'job-sf-matrix-electronic'
    assert pending['tools'][0]['input']['scheduled_at'].endswith('T08:00:00')


def test_workset_reference_resolution_overrides_llm_workset_advisory_kind(monkeypatch) -> None:
    from services.assistant_core.agent_kernel import slot_reference
    from services.assistant_core.agent_kernel.planning import SkillPlan
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.skill_first.cards import get_card

    card = get_card('workset.analysis')
    plan = SkillPlan(
        normalized_query='第二个人风险和推进建议',
        selected_skill='workset.analysis',
        confidence=0.91,
        slot_values={
            'question': '第二个人风险和推进建议',
            'latest_workset_or_item': {'kind': 'workset', 'workset_id': 'ws-advisory'},
        },
        route_reason='llm_selected_workset_analysis',
        planner_source='llm',
    )

    monkeypatch.setattr(runtime.workset_store, 'resolve_mention', lambda message, session_id: {
        'kind': 'item',
        'item': {
            'entity_type': 'candidate',
            'entity_id': 'cand-sf-yanglin',
            'rank': 2,
            'title': '杨琳',
        },
        'workset': {
            'id': 'ws-grounded',
            'entity_type': 'candidate',
        },
    })
    monkeypatch.setattr(slot_reference, 'refine_slots', lambda **kwargs: (
        dict(kwargs.get('current_slots') or {}),
        {'enabled': False, 'status': 'test_disabled', 'source': 'deterministic', 'applied': False},
    ))

    resolution = runtime._resolve_slots_and_references(  # type: ignore[attr-defined]
        '第二个人风险和推进建议',
        _ctx(),
        card,
        plan,
        None,
    )
    refined = runtime._refine_skill_after_reference(  # type: ignore[attr-defined]
        '第二个人风险和推进建议',
        _ctx(),
        card,
        plan,
        resolution,
    )

    assert resolution.slot_values['latest_workset_or_item'] == {
        'kind': 'item',
        'workset_id': 'ws-grounded',
        'entity_type': 'candidate',
        'entity_id': 'cand-sf-yanglin',
    }
    assert refined is not None
    refined_plan, refined_card = refined
    assert refined_card.id == 'candidate.evaluation'
    assert refined_plan.selected_skill == 'candidate.evaluation'
    assert refined_plan.slot_values['candidate_id'] == 'cand-sf-yanglin'


def test_single_candidate_reference_refines_compare_to_evaluation(monkeypatch) -> None:
    from services.assistant_core.agent_kernel import slot_reference
    from services.assistant_core.agent_kernel.planning import SkillPlan
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.skill_first.cards import get_card

    card = get_card('candidate.compare')
    plan = SkillPlan(
        normalized_query='第二个人风险和推进建议',
        selected_skill='candidate.compare',
        confidence=0.88,
        slot_values={'question': '第二个人风险和推进建议'},
        route_reason='llm_selected_candidate_compare',
        planner_source='llm',
    )
    monkeypatch.setattr(runtime.workset_store, 'resolve_mention', lambda message, session_id: {
        'kind': 'item',
        'item': {'entity_type': 'candidate', 'entity_id': 'cand-sf-yanglin', 'rank': 2, 'title': '杨琳'},
        'workset': {'id': 'ws-grounded', 'entity_type': 'candidate'},
    })
    monkeypatch.setattr(slot_reference, 'refine_slots', lambda **kwargs: (
        dict(kwargs.get('current_slots') or {}),
        {'enabled': False, 'status': 'test_disabled', 'source': 'deterministic', 'applied': False},
    ))

    resolution = runtime._resolve_slots_and_references('第二个人风险和推进建议', _ctx(), card, plan, None)  # type: ignore[attr-defined]
    refined = runtime._refine_skill_after_reference('第二个人风险和推进建议', _ctx(), card, plan, resolution)  # type: ignore[attr-defined]

    assert refined is not None
    refined_plan, refined_card = refined
    assert refined_card.id == 'candidate.evaluation'
    assert refined_plan.selected_skill == 'candidate.evaluation'
    assert refined_plan.slot_values['candidate_id'] == 'cand-sf-yanglin'
    assert refined_plan.rejected_skills[-1] == {
        'skill_id': 'candidate.compare',
        'reason': 'resolved_single_candidate_followup_requires_candidate_evaluation',
    }


def test_ui_attendance_notification_confirmation_is_pending_and_does_not_write(
    model_db,
    monkeypatch,
) -> None:
    from models import Notification
    from services.assistant_core.skill_first import runtime

    _seed_attendance_reminder_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('帮我给本月迟到最多的5个人生成提醒', _ctx(role='hr_admin'))

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'attendance.reminder_confirm'
    assert result.copilot['routeTrace']['output_verification_result'] == 'ok'
    assert result.route_decision.tool_plan[0].tool == 'notification_create'
    assert result.trace[0].skill == 'attendance_analysis'
    assert any(
        widget.get('type') == 'table'
        and (widget.get('table') or {}).get('title') == '待发送提醒草稿'
        for widget in result.widgets
    )
    assert any(widget.get('type') == 'confirmation_card' for widget in result.widgets)
    pending = getattr(result, '_pending_action')
    assert pending['label'] == '发送考勤迟到提醒'
    assert pending['tools']
    assert all(tool['tool'] == 'notification_create' for tool in pending['tools'])
    assert Notification.query.count() == 0


def test_agent_skill_cards_have_required_schema_and_first_phase_count() -> None:
    all_cards = cards.all_cards()

    assert len(all_cards) >= 30
    required_fields = {
        'id', 'name', 'domain', 'description', 'when_to_use', 'anti_examples',
        'colloquial_examples', 'required_slots', 'optional_slots',
        'slot_extraction_hints', 'risk_level', 'side_effect', 'allowed_roles',
        'executor', 'confirmation_policy', 'desensitization_policy',
        'verification_rules', 'fallback_policy',
    }
    for card in all_cards:
        payload = card.to_dict()
        assert required_fields <= payload.keys()
        assert card.id
        assert card.description
        assert card.when_to_use
        assert card.colloquial_examples
        assert card.executor.get('tool')


def test_first_phase_skill_cards_cover_required_hrm_intents() -> None:
    all_cards = {card.id: card for card in cards.all_cards()}
    required_skill_ids = {
        'recruitment.overview',
        'recruitment.open_jobs',
        'recruitment.job_progress',
        'recruitment.funnel',
        'recruitment.job_candidate_match',
        'candidate.search',
        'candidate.recent_resumes',
        'candidate.resume_analysis',
        'candidate.evaluation',
        'candidate.compare',
        'candidate.match_matrix',
        'interview.suggestion',
        'interview.records',
        'interview.schedule_draft',
        'interview.schedule_confirm_create',
        'offer.onboarding_progress',
        'employee.search',
        'employee.profile',
        'organization.overview',
        'employee.lifecycle_chain',
        'employee.attrition_risk',
        'employee.change_impact',
        'employee.org_health',
        'attendance.overview',
        'attendance.anomaly',
        'attendance.employee_evidence',
        'attendance.reminder_draft',
        'attendance.reminder_confirm',
        'attendance.trend',
        'performance.distribution',
        'performance.anomaly',
        'performance.employee_link',
        'payroll.summary',
        'payroll.anomaly',
        'payroll.employee_self_service',
        'payroll.performance_link',
        'approval.todo',
        'approval.mine',
        'approval.history',
        'approval.confirm_action',
        'feedback.summary',
        'feedback.bug_todo',
        'notification.create_confirm',
        'system.unsupported_write_intent',
        'report.operations',
        'workset.analysis',
        'smart.data_query',
    }

    assert required_skill_ids <= set(all_cards)
    for skill_id in required_skill_ids:
        card = all_cards[skill_id]
        assert card.when_to_use, skill_id
        assert len(card.anti_examples) >= 2, skill_id
        assert len(card.colloquial_examples) >= 3, skill_id
        assert card.slot_extraction_hints, skill_id
        assert card.verification_rules, skill_id
        assert card.fallback_policy, skill_id

    side_effect_skills = {
        'interview.schedule_confirm_create',
        'attendance.reminder_confirm',
        'approval.confirm_action',
        'notification.create_confirm',
    }
    for skill_id in side_effect_skills:
        card = all_cards[skill_id]
        assert card.side_effect is True
        assert 'pending' in card.confirmation_policy.lower()

    sensitive_skills = {
        'payroll.summary',
        'payroll.anomaly',
        'payroll.employee_self_service',
        'payroll.performance_link',
    }
    for skill_id in sensitive_skills:
        policy = all_cards[skill_id].desensitization_policy.lower()
        assert 'payroll' in policy or 'salary' in policy or 'self-service' in policy

    assert all_cards['smart.data_query'].side_effect is False
    assert 'read_only' in all_cards['smart.data_query'].confirmation_policy
    assert any('SQL' in rule or 'read-only' in rule for rule in all_cards['smart.data_query'].verification_rules)


@pytest.mark.parametrize(
    ('question', 'expected_skill'),
    [
        ('工资这块有没有啥异常', 'payroll.anomaly'),
        ('钱这块有没有不对劲', 'payroll.anomaly'),
        ('这个月谁打卡不太正常', 'attendance.anomaly'),
        ('最近招聘咋样', 'recruitment.overview'),
        ('电子工程师这个岗位进展到哪了', 'recruitment.job_progress'),
        ('这个人靠不靠谱', 'candidate.evaluation'),
        ('公司组织现在什么情况', 'organization.overview'),
        ('这个月考勤总体怎么样', 'attendance.overview'),
        ('绩效哪里不正常', 'performance.anomaly'),
        ('我这边还有哪些待办审批', 'approval.todo'),
        ('离职风险高的人有哪些', 'employee.attrition_risk'),
        ('帮我看下员工这块整体有没有问题', 'employee.org_health'),
        ('上面那批里谁最合适', 'workset.analysis'),
        ('给第二个安排面试', 'interview.schedule_confirm_create'),
    ],
)
def test_colloquial_semantic_recall_hits_expected_skill(question: str, expected_skill: str) -> None:
    recalled = semantic_index.recall_skills(question, top_k=5)

    assert recalled, question
    assert recalled[0].skill_id == expected_skill
    assert recalled[0].score > 0
    assert recalled[0].matched_text
    assert recalled[0].match_reason


@pytest.mark.parametrize(
    'question',
    [
        '新增一个岗位：AI 工程师',
        '删除电子工程师这个岗位',
        '把邓浩的面试时间改成明天早晨9点',
        '上传一份孙悦的新简历',
        '清除操作日志',
    ],
)
def test_unsupported_write_intent_is_a_formal_skill_card_candidate(question: str) -> None:
    recalled = semantic_index.recall_skills(question, top_k=5)

    assert recalled
    assert recalled[0].skill_id == 'system.unsupported_write_intent'
    assert 'candidate_signal:structural_intent:system.unsupported_write_intent' in recalled[0].match_reason


@pytest.mark.parametrize(
    ('question', 'expected_skill'),
    [
        ('我自己的薪资明细在哪儿', 'payroll.employee_self_service'),
        ('这个月工资总额大概多少', 'payroll.summary'),
        ('全公司发薪这块哪里不正常', 'payroll.anomaly'),
        ('最近新来的简历质量咋样', 'candidate.recent_resumes'),
        ('候选人面试记录查一下', 'interview.records'),
        ('先出一版约面文案，不要直接创建', 'interview.schedule_draft'),
        ('给第二位约一轮复试', 'interview.schedule_confirm_create'),
        ('我的申请现在走到哪了', 'approval.mine'),
        ('之前处理过的审批给我看下', 'approval.history'),
        ('同意第一条请假申请', 'approval.confirm_action'),
        ('用户最近主要在吐槽什么', 'feedback.summary'),
        ('还有什么系统 bug 没修', 'feedback.bug_todo'),
        ('给全员推一条 HR 通知', 'notification.create_confirm'),
        ('把吴明华调到研发部，先分析影响并准备确认', 'employee.change_submit_confirm'),
        ('给吴明华调薪 1800 元，先分析影响并准备确认', 'employee.salary_adjustment_submit_confirm'),
        ('这个员工最近状态如何', 'employee.profile'),
        ('低绩效这批人的工资和考勤有没有共同问题', 'payroll.performance_link'),
    ],
)
def test_colloquial_near_miss_semantic_boundaries(question: str, expected_skill: str) -> None:
    recalled = semantic_index.recall_skills(question, top_k=8)

    assert recalled, question
    ids = [item.skill_id for item in recalled]
    assert expected_skill in ids
    if expected_skill != 'interview.records':
        assert recalled[0].skill_id == expected_skill


def test_employee_change_pure_impact_stays_read_only_skill() -> None:
    recalled = semantic_index.recall_skills('如果把吴明华调到研发部，会影响哪些岗位、薪资、通知和审批？', top_k=8)

    assert recalled
    assert recalled[0].skill_id == 'employee.change_impact'


def test_anti_examples_demote_read_only_interview_question() -> None:
    recalled = semantic_index.recall_skills('刚才那批里先约谁比较稳，别浪费面试官时间', top_k=12)
    ids = [item.skill_id for item in recalled]

    assert 'workset.analysis' in ids
    assert 'interview.schedule_confirm_create' in ids
    assert ids.index('workset.analysis') < ids.index('interview.schedule_confirm_create')


def test_planner_cannot_select_skill_outside_top_k(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('工资这块有没有啥异常', top_k=3)
    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_LLM', raising=False)
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: {
            'normalized_query': '查询薪资异常',
            'selected_skill': 'interview.schedule_confirm_create',
            'confidence': 0.99,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'malicious_outside_candidate',
            'rejected_skills': [],
        },
    )

    plan = planner.plan_skill('工资这块有没有啥异常', _ctx(), candidates)

    assert plan.selected_skill is None
    assert plan.planner_source == 'llm'
    assert plan.fallback_reason == 'llm_selected_skill_outside_top_k'
    assert plan.route_reason == 'llm_candidate_boundary_rejected'


def test_llm_planner_can_choose_non_top_candidate_inside_top_k(monkeypatch) -> None:
    candidates = [
        semantic_index.RecallResult(
            skill_id='candidate.search',
            score=28.0,
            matched_text='semantic_candidate_search_signal',
            match_reason='card_semantic_overlap',
        ),
        semantic_index.RecallResult(
            skill_id='candidate.evaluation',
            score=18.0,
            matched_text='llm_hint:候选人评估',
            match_reason='candidate_signal:llm_skill_hint',
        ),
    ]
    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_LLM', raising=False)
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: {
            'normalized_query': '评估候选人吴明华并说明依据',
            'selected_skill': 'candidate.evaluation',
            'confidence': 0.91,
            'slot_values': {'keyword': '吴明华'},
            'missing_slots': [],
            'route_reason': 'llm_read_schema_and_chose_assessment_not_search',
            'rejected_skills': [{'skill_id': 'candidate.search', 'reason': '用户要评价和依据，不是候选人列表'}],
        },
    )

    plan = planner.plan_skill('分析一下候选人吴明华怎么样，并说明依据', _ctx(), candidates)

    assert plan.selected_skill == 'candidate.evaluation'
    assert plan.planner_source == 'llm'
    assert plan.route_reason == 'llm_read_schema_and_chose_assessment_not_search'


def test_llm_planner_is_default_when_model_is_available(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('分析一下候选人吴明华怎么样，并说明依据', top_k=8)
    assert any(item.skill_id == 'candidate.evaluation' for item in candidates)
    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_LLM', raising=False)
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    seen: dict = {}

    def fake_json_chat_profile(*args, **kwargs):
        seen['called'] = True
        seen['messages'] = args[1] if len(args) > 1 else kwargs.get('messages')
        return {
            'normalized_query': '评估候选人吴明华并说明依据',
            'selected_skill': 'candidate.evaluation',
            'confidence': 0.88,
            'slot_values': {'keyword': '吴明华'},
            'missing_slots': [],
            'route_reason': 'llm_rerank_candidate_assessment',
            'rejected_skills': [{'skill_id': 'candidate.search', 'reason': '用户要评估依据，不是列表检索'}],
        }

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill('分析一下候选人吴明华怎么样，并说明依据', _ctx(), candidates)

    assert seen['called'] is True
    assert plan.selected_skill == 'candidate.evaluation'
    assert plan.planner_source == 'llm'
    assert plan.slot_values['keyword'] == '吴明华'
    serialized_messages = json.dumps(seen['messages'], ensure_ascii=False)
    planner_payload = json.loads(seen['messages'][-1]['content'])
    assert any('anti' in item for item in planner_payload['top_k_skill_cards'])
    assert 'matched_examples' in serialized_messages
    assert 'current_page_context' in serialized_messages
    assert 'candidate_boundary' in serialized_messages
    assert 'available_skill_playbooks' not in serialized_messages


def test_skill_provider_exposes_model_visible_schema_without_forbidden_hidden_params() -> None:
    from services.assistant_core.agent_kernel.skill_provider import records_from_recall
    from services.assistant_core.skill_first.semantic_index import RecallResult

    records = records_from_recall([
        RecallResult(
            skill_id='smart.data_query',
            score=42.0,
            matched_text='低绩效和考勤异常交叉统计',
            match_reason='semantic_user_text',
            matched_examples=['低绩效和考勤异常交叉统计一下'],
        )
    ])

    assert len(records) == 1
    record = records[0]
    schema = record.to_model_schema()
    metadata = record.executor_metadata

    assert schema['id'] == 'smart.data_query'
    assert schema['executor_tool'] == 'smart_data_query'
    assert schema['tool_schema']
    assert 'question' in schema['tool_schema']
    assert 'sql' not in schema['tool_schema']
    assert 'raw_sql' not in schema['tool_schema']
    assert metadata['executor_tool'] == 'smart_data_query'
    assert metadata['confirmation_policy'] == 'read_only_sql_only_never_side_effect'
    assert record.recall_evidence['match_reason'] == 'semantic_user_text'


def test_agent_kernel_planner_slots_guard_schema_and_side_effect_ids() -> None:
    from services.assistant_core.agent_kernel import planner_slots

    smart_card = cards.get_card('smart.data_query')
    guarded_smart = planner_slots.guard_slot_values(
        '帮我交叉统计一下低绩效和考勤异常',
        _ctx(),
        smart_card,  # type: ignore[arg-type]
        {
            'question': '模型改写的问题',
            'sql': 'DELETE FROM employees',
            'raw_sql': 'DROP TABLE candidates',
            'explanation': 'malicious planner sql',
            'limit': 5000,
        },
        'llm',
        fill_slots=lambda message, ctx, card: {'question': message, 'limit': 20},
        looks_like_workset_reference=lambda value: False,
        extract_candidate_name=lambda value: None,
        extract_employee_name_for_query=lambda value: None,
        extract_employee_name_for_action=lambda value: None,
    )

    assert guarded_smart == {
        'question': '帮我交叉统计一下低绩效和考勤异常',
        'limit': 20,
    }
    assert planner_slots.sanitize_slot_values({
        '_private': 'hidden',
        'sql': 'SELECT * FROM users',
        'keyword': ' 孙悦 ',
        'nested': {'_hidden': 'x', 'name': 'ok'},
    }) == {'keyword': '孙悦', 'nested': {'name': 'ok'}}

    interview_card = cards.get_card('interview.schedule_confirm_create')
    guarded_interview = planner_slots.guard_slot_values(
        '给第二个安排面试',
        _ctx(),
        interview_card,  # type: ignore[arg-type]
        {
            'target_candidate': 'fabricated-candidate',
            'candidate_id': 'cand-from-model',
            'resume_id': 'resume-from-model',
            'job_id': 'job-from-model',
            'scheduled_at': '2026-06-04 10:00',
        },
        'llm',
        fill_slots=lambda message, ctx, card: {'question': message},
        looks_like_workset_reference=lambda value: '第二' in value or 'fabricated' in value,
        extract_candidate_name=lambda value: None,
        extract_employee_name_for_query=lambda value: None,
        extract_employee_name_for_action=lambda value: None,
    )

    assert guarded_interview == {
        'question': '给第二个安排面试',
        'scheduled_at': '2026-06-04 10:00',
    }
    assert 'candidate_id' not in guarded_interview
    assert 'resume_id' not in guarded_interview
    assert 'job_id' not in guarded_interview
    assert 'target_candidate' not in guarded_interview


def test_agent_kernel_planner_slots_ground_explicit_entities_over_stale_ids() -> None:
    from services.assistant_core.agent_kernel import planner_slots

    candidate_card = cards.get_card('candidate.evaluation')
    grounded_candidate = planner_slots.ground_explicit_entity_slots(
        '候选人孙悦靠不靠谱',
        candidate_card,  # type: ignore[arg-type]
        {
            'question': '候选人孙悦靠不靠谱',
            'keyword': '刚才那个候选人',
            'candidate_id': 'candidate-from-history',
            'resumeId': 'resume-from-history',
        },
        extract_candidate_name=lambda value: '孙悦' if '孙悦' in value else None,
        extract_employee_name_for_query=lambda value: None,
        extract_employee_name_for_action=lambda value: None,
    )

    assert grounded_candidate['keyword'] == '孙悦'
    assert 'candidate_id' not in grounded_candidate
    assert 'resumeId' not in grounded_candidate

    employee_card = cards.get_card('employee.profile')
    grounded_employee = planner_slots.ground_explicit_entity_slots(
        '吴明华最近状态如何',
        employee_card,  # type: ignore[arg-type]
        {
            'question': '吴明华最近状态如何',
            'keyword': '上一个员工',
            'employee_id': 'employee-from-focus',
        },
        extract_candidate_name=lambda value: None,
        extract_employee_name_for_query=lambda value: '吴明华' if '吴明华' in value else None,
        extract_employee_name_for_action=lambda value: None,
    )

    assert grounded_employee['keyword'] == '吴明华'
    assert 'employee_id' not in grounded_employee


def test_agent_kernel_planner_slot_extraction_owns_explicit_entity_names() -> None:
    from services.assistant_core.agent_kernel import planner_slot_extraction

    assert planner_slot_extraction.extract_candidate_name('候选人孙悦靠不靠谱') == '孙悦'
    assert planner_slot_extraction.extract_candidate_name('给孙悦安排明天面试') == '孙悦'
    assert planner_slot_extraction.extract_candidate_name('给第二个安排明天面试') is None
    assert planner_slot_extraction.extract_resume_subject('看一下赵敏的简历') == '赵敏'
    assert planner_slot_extraction.extract_resume_subject('看一下刚才那个的简历') is None

    assert planner_slot_extraction.extract_employee_name_for_query('查一下吴明华最近考勤') == '吴明华'
    assert planner_slot_extraction.extract_employee_name_for_query('这个员工最近考勤怎么样') is None
    assert planner_slot_extraction.extract_employee_name_for_action('把吴明华调到销售部') == '吴明华'
    assert planner_slot_extraction.extract_employee_name_for_action('把这个员工调到销售部') is None

    evaluation_card = cards.get_card('candidate.evaluation')
    evaluation_slots = planner.fill_slots('候选人孙悦靠不靠谱', _ctx(), evaluation_card)
    assert evaluation_slots['keyword'] == '孙悦'

    employee_card = cards.get_card('employee.profile')
    employee_slots = planner.fill_slots('查一下吴明华最近考勤', _ctx(), employee_card)
    assert employee_slots['keyword'] == '吴明华'

    interview_card = cards.get_card('interview.schedule_confirm_create')
    interview_slots = planner.fill_slots('给孙悦安排明天面试', _ctx(), interview_card)
    assert interview_slots['target_candidate'] == '孙悦'
    assert interview_slots['keyword'] == '孙悦'


def test_agent_kernel_planner_slot_extraction_owns_job_keywords() -> None:
    from services.assistant_core.agent_kernel import planner_slot_extraction

    assert planner_slot_extraction.extract_job_keyword(
        '孙悦的个人能力怎么样，符合我们的电子工程师岗位要求吗'
    ) == '电子工程师'
    assert planner_slot_extraction.extract_job_context_keyword(
        '电子工程师岗位最近候选人谁更合适？给对比矩阵'
    ) == '电子工程师'
    assert planner_slot_extraction.clean_job_keyword('我们当前在招的电子工程师岗位') == '电子工程师'
    assert planner_slot_extraction.longest_job_phrase('看看电子工程师岗位和HR专员岗位') == '电子工程师'

    job_fit_card = cards.get_card('candidate.job_fit')
    job_fit_slots = planner.fill_slots(
        '孙悦的个人能力怎么样，符合我们的电子工程师岗位要求吗',
        _ctx(),
        job_fit_card,
    )

    assert job_fit_slots['keyword'] == '孙悦'
    assert job_fit_slots['job_keyword'] == '电子工程师'

    match_card = cards.get_card('recruitment.job_candidate_match')
    match_slots = planner.fill_slots('电子工程师岗位最近候选人谁更合适？给对比矩阵', _ctx(), match_card)

    assert match_slots['keyword'] == '电子工程师'


def test_agent_kernel_planner_slot_extraction_owns_action_slot_hints() -> None:
    from services.assistant_core.agent_kernel import planner_slot_extraction

    text = '把吴明华调到研发部，目标岗位：研发工程师，先分析影响并准备确认'
    assert planner_slot_extraction.extract_target_department(text) == '研发部'
    assert planner_slot_extraction.extract_target_position(text) == '研发工程师'
    assert planner_slot_extraction.extract_schedule_hint('给孙悦安排明天上午十点面试') == 'tomorrow'
    assert planner_slot_extraction.extract_schedule_hint('给孙悦安排2026-06-04面试') == '2026-06-04'
    assert planner_slot_extraction.extract_schedule_hint('给孙悦安排上午十点面试') == 'time_mentioned'

    change_card = cards.get_card('employee.change_submit_confirm')
    change_slots = planner.fill_slots(text, _ctx(), change_card)

    assert change_slots['keyword'] == '吴明华'
    assert change_slots['target_department'] == '研发部'
    assert change_slots['target_position'] == '研发工程师'

    interview_card = cards.get_card('interview.schedule_confirm_create')
    interview_slots = planner.fill_slots('给孙悦安排明天上午十点面试', _ctx(), interview_card)

    assert interview_slots['target_candidate'] == '孙悦'
    assert interview_slots['scheduled_at'] == 'tomorrow'


def test_agent_kernel_planner_slot_extraction_owns_notification_and_attendance_slots() -> None:
    from services.assistant_core.agent_kernel import planner_slot_extraction

    notification = planner_slot_extraction.notification_slots('给全员推一条 HR 通知：明天下午三点全员培训')

    assert notification == {
        'title': '明天下午三点全员培训',
        'content': '明天下午三点全员培训',
        'notice_type': 'hr',
        'link_url': '/notifications',
    }

    attendance = planner_slot_extraction.attendance_reminder_confirm_slots('生成迟到最多前两名的提醒')

    assert attendance['title'] == '发送考勤迟到提醒'
    assert attendance['notice_type'] == 'attendance'
    assert attendance['rank_status'] == 'late'
    assert attendance['limit'] == 2
    assert planner_slot_extraction.is_attendance_reminder_confirm_question('生成迟到最多前两名的提醒') is True
    assert planner_slot_extraction.is_attendance_reminder_confirm_question('只写迟到提醒草稿') is False

    notification_card = cards.get_card('notification.create_confirm')
    notification_slots = planner.fill_slots('给全员推一条 HR 通知：明天下午三点全员培训', _ctx(), notification_card)

    assert notification_slots['title'] == '明天下午三点全员培训'
    assert notification_slots['content'] == '明天下午三点全员培训'
    assert notification_slots['notice_type'] == 'hr'

    attendance_card = cards.get_card('attendance.reminder_confirm')
    attendance_slots = planner.fill_slots('生成迟到最多前两名的提醒', _ctx(), attendance_card)

    assert attendance_slots['rank_status'] == 'late'
    assert attendance_slots['limit'] == 2


def test_agent_kernel_planner_catalog_owns_page_and_workflow_slots() -> None:
    from services.assistant_core.agent_kernel import planner_catalog

    page_ctx = _job_page_ctx()
    assert planner_catalog.page_capability_slots(page_ctx) == {
        'module': 'module_catalog',
        'view': 'module',
        'module_id': 'jobs',
        'limit': 12,
    }
    assert planner_catalog.workflow_help_slots('招聘到入职怎么走', _ctx()) == {
        'module': 'module_catalog',
        'view': 'flow',
        'flow_id': 'recruit_to_onboard',
        'limit': 12,
    }
    assert planner_catalog.workflow_help_slots('审批通知怎么配', _ctx()) == {
        'module': 'module_catalog',
        'view': 'flow',
        'flow_id': 'workflow_governance',
        'limit': 12,
    }

    page_card = cards.get_card('system.page_capability')
    page_slots = planner.fill_slots('在这个页面你能做什么', page_ctx, page_card)
    assert page_slots['module_id'] == 'jobs'

    workflow_card = cards.get_card('system.workflow_help')
    workflow_slots = planner.fill_slots('招聘到入职怎么走', _ctx(), workflow_card)
    assert workflow_slots['view'] == 'flow'
    assert workflow_slots['flow_id'] == 'recruit_to_onboard'


def test_agent_kernel_planner_followup_owns_task_slots_with_workset_reference() -> None:
    from services.assistant_core.agent_kernel import planner_followup
    from services.assistant_core.workset_store import default_store

    default_store.clear()
    ctx = _ctx(session_id='s-followup-task-slot')
    default_store.create_workset_from_entities(
        ctx.session_id,
        ctx.user_id,
        '候选人列表',
        [
            {'type': 'candidate', 'id': 'cand-followup-1', 'title': '孙悦'},
            {'type': 'candidate', 'id': 'cand-followup-2', 'title': '杨琳'},
        ],
    )

    slots = planner_followup.followup_task_slots('给第二个创建跟进任务：明天联系候选人', ctx)

    assert slots['title'] == '明天联系候选人'
    assert slots['content'] == '给第二个创建跟进任务：明天联系候选人'
    assert slots['due_at'] == 'tomorrow'
    assert slots['target_reference'] == '杨琳'

    card = cards.get_card('task.followup_create_confirm')
    planner_slots = planner.fill_slots('给第二个创建跟进任务：明天联系候选人', ctx, card)

    assert planner_slots['title'] == '明天联系候选人'
    assert planner_slots['due_at'] == 'tomorrow'
    assert planner_slots['target_reference'] == '杨琳'


def test_agent_kernel_planner_slot_extraction_owns_common_deterministic_slots() -> None:
    from services.assistant_core.agent_kernel import planner_slot_extraction

    assert planner_slot_extraction.extract_month('看一下2026年6月工资异常') == '2026-06'
    assert planner_slot_extraction.extract_month('本月迟到最多的人') == 'current_month'
    assert planner_slot_extraction.extract_recent_days('最近15天收到的简历') == 15
    assert planner_slot_extraction.extract_recent_days('最近招聘咋样') == 30
    assert planner_slot_extraction.extract_limit('考勤异常前两名') == 2
    assert planner_slot_extraction.extract_limit('top 88 迟到员工') == 50

    assert planner_slot_extraction.extract_approval_action('把第二条审批驳回') == 'reject'
    assert planner_slot_extraction.extract_approval_action('同意审批编号 ap-2026-001') == 'approve'
    assert planner_slot_extraction.extract_approval_id('审批ID：approval-abc_123') == 'approval-abc_123'
    assert planner_slot_extraction.extract_approval_rank('处理第 12 条审批') == 12
    assert planner_slot_extraction.extract_approval_comment('驳回这条审批，理由：材料缺失') == '材料缺失'

    assert planner_slot_extraction.extract_salary_adjustment_amount('给吴明华涨薪1,200元') == 1200
    assert planner_slot_extraction.extract_salary_adjustment_amount('给吴明华降薪500元') == -500
    assert planner_slot_extraction.format_number(1200.50) == '1200.5'
    assert planner_slot_extraction.extract_effective_date_hint('明天生效') == '明天'
    assert planner_slot_extraction.extract_action_reason('原因：岗位职责扩大') == '岗位职责扩大'

    salary_card = cards.get_card('employee.salary_adjustment_submit_confirm')
    salary_slots = planner.fill_slots('给吴明华涨薪1,200元，明天生效，原因：岗位职责扩大', _ctx(), salary_card)

    assert salary_slots['keyword'] == '吴明华'
    assert salary_slots['salary_adjustment'] == '1200'
    assert salary_slots['effective_date'] == '明天'
    assert salary_slots['reason'] == '岗位职责扩大'

    approval_card = cards.get_card('approval.confirm_action')
    approval_slots = planner.fill_slots('驳回审批ID：ap-2026-001，理由：材料缺失', _ctx(), approval_card)

    assert approval_slots['action'] == 'reject'
    assert approval_slots['approval_id'] == 'ap-2026-001'
    assert approval_slots['comment'] == '材料缺失'


def test_agent_kernel_planner_guard_owns_missing_slots_and_bulk_write_policy() -> None:
    from services.assistant_core.agent_kernel import planner_guard

    workset_card = cards.get_card('workset.analysis')
    payroll_card = cards.get_card('payroll.employee_self_service')
    approval_card = cards.get_card('approval.confirm_action')

    assert planner_guard.missing_required_slots(workset_card, {'question': '上面那批里谁最合适'}, _ctx()) == [
        'latest_workset_or_item'
    ]
    assert planner_guard.missing_required_slots(
        payroll_card,
        {'question': '我自己的薪资明细在哪儿'},
        _ctx(),
    ) == ['employee_scope']
    assert planner_guard.missing_required_slots(
        payroll_card,
        {'question': '我自己的薪资明细在哪儿', 'employee_scope': 'self'},
        _ctx(),
    ) == ['employee_scope']

    ctx = _ctx()
    ctx.user_employee_id = 'emp-self'
    assert planner_guard.missing_required_slots(
        payroll_card,
        {'question': '我自己的薪资明细在哪儿', 'employee_scope': 'self'},
        ctx,
    ) == []
    assert planner_guard.unsupported_bulk_or_unsafe_side_effect_intent(
        '把所有审批都通过',
        approval_card,  # type: ignore[arg-type]
    ) == '审批操作必须指定单条审批并进入确认流程，AI 助手不会批量通过或驳回审批。'


def test_agent_kernel_decision_builds_tool_plan_with_schema_boundary() -> None:
    from services.assistant_core.agent_kernel import decision as kernel_decision
    from services.assistant_core.agent_kernel.planning import SkillPlan

    smart_card = cards.get_card('smart.data_query')
    smart_plan = SkillPlan(
        normalized_query='低绩效和考勤异常交叉统计',
        selected_skill='smart.data_query',
        confidence=0.91,
        slot_values={
            'question': '低绩效和考勤异常交叉统计',
            'limit': 30,
            'sql': 'DELETE FROM employees',
            '_slot_guard_changes': [{'field': 'keyword'}],
        },
        route_reason='test_decision_boundary',
        planner_source='llm',
    )

    smart_decision = kernel_decision.build_route_decision(smart_card, smart_plan)  # type: ignore[arg-type]

    assert smart_decision.intent == 'smart.data_query'
    assert smart_decision.tool_plan[0].tool == 'smart_data_query'
    assert smart_decision.tool_plan[0].input == {
        'question': '低绩效和考勤异常交叉统计',
        'limit': 30,
    }
    assert smart_decision.requires_confirmation is False

    interview_card = cards.get_card('interview.schedule_confirm_create')
    interview_plan = SkillPlan(
        normalized_query='给孙悦安排明天上午十点面试',
        selected_skill='interview.schedule_confirm_create',
        confidence=0.88,
        slot_values={
            'target_candidate': '孙悦',
            'scheduled_at': '明天上午十点',
        },
        route_reason='test_named_subject_decision',
        planner_source='llm',
    )

    interview_decision = kernel_decision.build_route_decision(interview_card, interview_plan)  # type: ignore[arg-type]

    assert interview_decision.task_type == 'action'
    assert interview_decision.requires_confirmation is True
    assert interview_decision.tool_plan[0].input == {}
    assert interview_decision.required_context == ['named_subject_evidence']


def test_agent_kernel_skill_plan_contract_is_kernel_owned_and_compat_exported() -> None:
    from services.assistant_core.agent_kernel.planning import SkillPlan as KernelSkillPlan
    from services.assistant_core.skill_first.planner import SkillPlan as CompatSkillPlan

    plan = KernelSkillPlan(
        normalized_query='最近招聘咋样',
        selected_skill='recruitment.overview',
        confidence=0.87654,
        slot_values={'question': '最近招聘咋样'},
        planner_source='llm',
    )

    assert CompatSkillPlan is KernelSkillPlan
    assert plan.to_dict()['confidence'] == 0.8765
    assert plan.to_dict()['slot_values'] == {'question': '最近招聘咋样'}


def test_agent_kernel_planning_builds_deterministic_candidate_fallback() -> None:
    from services.assistant_core.agent_kernel import planning as kernel_planning

    candidates = [
        semantic_index.RecallResult(
            skill_id='notification.create_confirm',
            score=8.2,
            matched_text='给全员推一条 HR 通知',
            match_reason='candidate_signal:structural_intent:notification.create_confirm',
        ),
        semantic_index.RecallResult(
            skill_id='system.workflow_help',
            score=3.0,
            matched_text='通知怎么发',
            match_reason='semantic_user_text',
        ),
    ]

    plan = kernel_planning.deterministic_candidate_plan(
        '给全员推一条 HR 通知',
        _ctx(),
        candidates,
        normalize_query=semantic_index.normalize_query,
        get_card=cards.get_card,
        fill_slots=lambda message, ctx, card: {'question': message},
        missing_required_slots=lambda card, slots, ctx: ['content'],
        min_confidence=planner.MIN_CONFIDENCE,
    )

    assert plan.selected_skill == 'notification.create_confirm'
    assert plan.confidence == 0.62
    assert plan.fallback_reason == 'missing_required_side_effect_slots'
    assert plan.route_reason.startswith('candidate_order_fallback:')
    assert plan.rejected_skills == [{
        'skill_id': 'system.workflow_help',
        'reason': 'lower_semantic_score_or_anti_example_penalty',
        'score': 3.0,
    }]
    assert plan.diagnostics['planner_mode'] == 'deterministic_candidate_order'
    assert kernel_planning.candidate_order_confidence(1.0) < planner.MIN_CONFIDENCE


def test_agent_kernel_planner_output_parses_llm_json_with_schema_safety() -> None:
    from services.assistant_core.agent_kernel import planner_output

    candidates = [
        semantic_index.RecallResult(
            skill_id='smart.data_query',
            score=12.34567,
            matched_text='低绩效和考勤异常交叉统计',
            match_reason='semantic_user_text',
        ),
        semantic_index.RecallResult(
            skill_id='payroll.anomaly',
            score=7.1,
            matched_text='工资异常',
            match_reason='semantic_user_text',
        ),
    ]

    plan = planner_output.normalize_llm_plan(
        {
            'selectedSkill': 'smart.data_query',
            'confidence': '1.8',
            'slotValues': {
                'question': '低绩效和考勤异常交叉统计',
                'sql': 'DELETE FROM employees',
                '_private': 'hidden',
                'limit': 30,
            },
            'missingSlots': ['month'],
        },
        '低绩效和考勤异常交叉统计',
        candidates,
        normalize_query=semantic_index.normalize_query,
    )

    assert plan is not None
    assert plan.selected_skill == 'smart.data_query'
    assert plan.confidence == 1.0
    assert plan.slot_values == {
        'question': '低绩效和考勤异常交叉统计',
        'limit': 30,
    }
    assert plan.missing_slots == ['month']
    assert plan.rejected_skills == [{
        'skill_id': 'payroll.anomaly',
        'reason': 'not_selected_by_llm_reranker',
        'score': 7.1,
    }]
    assert planner_output.normalize_llm_plan(
        {'selected_skill': 'fabricated.skill', 'confidence': 0.9},
        '随便查一下',
        candidates,
        normalize_query=semantic_index.normalize_query,
    ) is None
    assert planner_output.diagnostic_status_from_llm_meta({'status': 'timeout'}) == 'llm_timeout'
    assert planner_output.diagnostic_status_from_llm_meta({'json_status': 'parse_failed'}) == 'llm_json_parse_failed'


def test_tool_workbench_rejects_provider_tool_mismatch(monkeypatch) -> None:
    from services.assistant_core import skill_registry
    from services.assistant_core.agent_kernel.tool_workbench import ToolWorkbench

    class _Skill:
        id = 'resume_analysis'
        input_schema = {'recent_days': {'type': 'integer', 'default': 30}}
        allowed_roles = ['hr_admin']
        action_type = 'READ_HR'

    monkeypatch.setattr(skill_registry, 'get', lambda tool: _Skill())

    out = ToolWorkbench().call(
        'resume_analysis',
        {'recent_days': 10},
        _ctx(role='hr_admin'),
        provider_metadata={
            'skill_id': 'candidate.recent_resumes',
            'executor_tool': 'candidate_evidence_bundle',
        },
    )

    assert out['ok'] is False
    assert out['error'] == 'provider_tool_mismatch'
    assert out['error_details']['provider_skill'] == 'candidate.recent_resumes'
    assert out['error_details']['provider_tool'] == 'candidate_evidence_bundle'


def test_llm_understanding_and_planner_prompts_stay_compact() -> None:
    from services.assistant_core.skill_first import understanding

    ctx = _job_page_ctx()
    message = '在这个页面你能做什么'
    understanding_messages = understanding._messages(message, ctx)
    candidates = retrieve_skills(message, normalized_query=message, understanding=None, top_k=16)
    planner_messages = planner._planner_messages(message, ctx, candidates, understanding=None)

    understanding_chars = sum(len(item['content']) for item in understanding_messages)
    planner_chars = sum(len(item['content']) for item in planner_messages)
    serialized_planner = json.dumps(planner_messages, ensure_ascii=False)

    assert understanding_chars < 5000
    assert planner_chars < 9000
    assert 'known_domains' in json.dumps(understanding_messages, ensure_ascii=False)
    assert 'skill_signatures' not in json.dumps(understanding_messages, ensure_ascii=False)
    assert 'candidate_boundary' in serialized_planner
    assert 'tool_schema' in serialized_planner
    assert 'available_skill_playbooks' not in serialized_planner


def test_llm_planner_prompt_calibrates_missing_slots_as_selection_not_null() -> None:
    message = '给全员推一条 HR 通知：明天下午三点全员培训'
    ctx = _ctx()
    candidates = retrieve_skills(message, normalized_query=message, understanding=None, top_k=16)
    planner_messages = planner._planner_messages(message, ctx, candidates, understanding=None)
    payload = json.loads(planner_messages[-1]['content'])
    contract = payload['strict_contract']

    assert contract['planner_mode'] == 'skill_decision_lite'
    assert 'confidence_calibration' in contract
    assert 'Missing slots' in contract['low_confidence_policy']
    assert 'side-effect confirmation' in contract['low_confidence_policy']
    assert any(item['id'] == 'notification.create_confirm' and item['side_effect'] for item in payload['top_k_skill_cards'])
    assert all('rank' in item for item in payload['top_k_skill_cards'])
    notification_schema = next(item for item in payload['top_k_skill_cards'] if item['id'] == 'notification.create_confirm')
    assert 'tool_schema' in notification_schema
    assert notification_schema['confirmation_policy'] == 'always_pending_confirmation_and_never_direct_execute'


def test_agent_kernel_planner_prompt_contract_is_kernel_owned() -> None:
    from services.assistant_core.agent_kernel import planner_prompt

    message = '给全员推一条 HR 通知：明天下午三点全员培训'
    ctx = _ctx()
    ctx.history = [{
        'question': '刚才那批候选人怎么样',
        'answer': '已生成候选人列表。',
        'worksets': [{'id': 'ws-candidates', 'entityType': 'candidate', 'count': 3}],
        'copilot': {'routeTrace': {'selected_skill': 'candidate.recent_resumes'}},
    }]
    candidates = retrieve_skills(message, normalized_query=message, understanding=None, top_k=16)
    messages = planner_prompt.planner_messages(
        message,
        ctx,
        candidates,
        normalize_query=semantic_index.normalize_query,
    )
    payload = json.loads(messages[-1]['content'])
    contract = planner_prompt.planner_strict_contract()
    retry_contract = planner_prompt.planner_retry_strict_contract()

    assert planner_prompt.compact_history(ctx.history)[0]['selected_skill'] == 'candidate.recent_resumes'
    assert planner_prompt.compact_history(ctx.history)[0]['worksets'][0]['id'] == 'ws-candidates'
    assert planner.LLM_PLANNER_CANDIDATE_LIMIT == planner_prompt.PLANNER_CANDIDATE_LIMIT
    assert planner.LLM_PLANNER_PROMPT_MODE == planner_prompt.PLANNER_PROMPT_MODE
    assert planner.LLM_PLANNER_RETRY_CANDIDATE_LIMIT == planner_prompt.PLANNER_RETRY_CANDIDATE_LIMIT
    assert planner.LLM_PLANNER_RETRY_PROMPT_MODE == planner_prompt.PLANNER_RETRY_PROMPT_MODE
    assert payload['strict_contract'] == contract
    assert payload['recent_history'][0]['selected_skill'] == 'candidate.recent_resumes'
    assert payload['candidate_boundary'] == [item.skill_id for item in candidates[:planner_prompt.PLANNER_CANDIDATE_LIMIT]]
    assert all(item['id'] in payload['candidate_boundary'] for item in payload['top_k_skill_cards'])
    assert contract['selected_skill'] == 'one id from candidate_boundary or null'
    assert contract['do_not_create_skill_or_tool'] is True
    assert contract['do_not_write_sql_or_execute_db'] is True
    assert 'pending confirmation' in contract['side_effect_policy']
    assert retry_contract['planner_mode'] == planner_prompt.PLANNER_RETRY_PROMPT_MODE
    assert 'permissions' in retry_contract['null_policy']
    assert 'ToolExecutor schema' in retry_contract['safety_boundary']


def test_understanding_diagnostics_explain_disabled_llm(monkeypatch) -> None:
    from services.assistant_core.skill_first import understanding

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_UNDERSTANDING', '0')
    monkeypatch.setattr(understanding.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        understanding.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('understanding LLM should be disabled')),
    )

    result = understanding.understand_query('工资这块有没有啥异常', _ctx())

    assert result.source == 'deterministic'
    assert result.diagnostics['stage'] == 'understanding'
    assert result.diagnostics['llm_enabled'] is False
    assert result.diagnostics['attempted'] is False
    assert result.diagnostics['status'] == 'disabled_by_env'


def test_planner_degraded_recovery_uses_strong_skill_card_recall_after_model_exception(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('工资这块有没有啥异常', top_k=3)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def boom(*args, **kwargs):
        raise TimeoutError('planner timed out')

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', boom)

    plan = planner.plan_skill('工资这块有没有啥异常', _ctx(), candidates)

    assert plan.selected_skill == 'payroll.anomaly'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.route_reason.startswith('llm_unusable_schema_guarded_recovery:')
    assert plan.diagnostics['attempted'] is True
    assert plan.diagnostics['status'] == 'exception'
    assert plan.diagnostics['error_type'] == 'TimeoutError'
    assert plan.diagnostics['deterministic_fallback_used'] is False
    assert plan.diagnostics['deterministic_fallback_blocked'] is True
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'payroll.anomaly'


def test_planner_diagnostics_still_clarify_weak_recall_after_model_exception(monkeypatch) -> None:
    candidates = [
        semantic_index.RecallResult(
            skill_id='approval.mine',
            score=2.2,
            matched_text='weak_generic_help_signal',
            match_reason='card_semantic_overlap',
        ),
        semantic_index.RecallResult(
            skill_id='candidate.search',
            score=2.1,
            matched_text='weak_generic_search_signal',
            match_reason='card_semantic_overlap',
        ),
    ]
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def boom(*args, **kwargs):
        raise TimeoutError('planner timed out')

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', boom)

    plan = planner.plan_skill('查一下', _ctx(), candidates)

    assert plan.selected_skill is None
    assert plan.planner_source == 'llm'
    assert plan.fallback_reason == 'llm_planner_unusable'
    assert plan.route_reason == 'llm_planner_failed_without_bounded_decision'
    assert plan.diagnostics['attempted'] is True
    assert plan.diagnostics['status'] == 'exception'
    assert plan.diagnostics['error_type'] == 'TimeoutError'
    assert plan.diagnostics['deterministic_fallback_used'] is False
    assert plan.diagnostics['deterministic_fallback_blocked'] is True
    assert plan.diagnostics['degraded_recovery_used'] is False


def test_planner_diagnostics_distinguish_llm_timeout_from_invalid_json(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('工资这块有没有啥异常', top_k=3)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        planner.llm_client._set_last_call_meta({  # type: ignore[attr-defined]
            'status': 'timeout',
            'attempt': 0,
            'model': 'fake-model',
            'provider': 'siliconflow',
            'latency_ms': 8000,
        })
        return None

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill('工资这块有没有啥异常', _ctx(), candidates)

    assert plan.selected_skill == 'payroll.anomaly'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.diagnostics['status'] == 'llm_timeout'
    assert plan.diagnostics['llm_call']['status'] == 'timeout'
    assert plan.diagnostics['deterministic_fallback_used'] is False
    assert plan.diagnostics['deterministic_fallback_blocked'] is True
    assert plan.diagnostics['degraded_recovery_used'] is True


def test_planner_corrects_generic_performance_anomaly_to_employee_profile_link(monkeypatch) -> None:
    message = '低绩效员工画像看看'
    candidates = retrieve_skills(message, normalized_query=message, top_k=8)
    assert candidates[0].skill_id == 'performance.employee_link'
    assert any(item.skill_id == 'performance.anomaly' for item in candidates)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        return {
            'normalized_query': message,
            'selected_skill': 'performance.anomaly',
            'confidence': 0.78,
            'slot_values': {'question': message},
            'missing_slots': [],
            'route_reason': 'llm_selected_generic_performance_anomaly',
            'rejected_skills': [],
        }

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill(message, _ctx(), candidates)

    assert plan.selected_skill == 'performance.employee_link'
    assert plan.confidence >= planner.HIGH_CONFIDENCE
    assert plan.diagnostics['skill_card_contract_correction']['from'] == 'performance.anomaly'
    assert plan.diagnostics['skill_card_contract_correction']['to'] == 'performance.employee_link'
    assert 'performance_employee_profile_link_request' in plan.route_reason


def test_planner_recovers_performance_employee_link_low_confidence_when_schema_slots_are_clear(monkeypatch) -> None:
    message = '低绩效员工画像看看'
    candidates = retrieve_skills(message, normalized_query=message, top_k=8)
    assert candidates[0].skill_id == 'performance.employee_link'
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        return {
            'normalized_query': message,
            'selected_skill': None,
            'confidence': 0.1,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'llm_under_confident_profile_link',
            'rejected_skills': [],
        }

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill(message, _ctx(), candidates)

    assert plan.selected_skill == 'performance.employee_link'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.slot_values['profile_segment'] == 'low_performance'
    assert plan.slot_values['link_focus'] == 'performance_profile'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'performance.employee_link'
    assert plan.diagnostics['degraded_recovery_assessment']['reason'] in {
        'schema_slots_support_top_candidate_despite_soft_anti_overlap',
        'explicit_object_read_schema_slots',
    }


def test_planner_recovers_smart_data_query_after_llm_timeout(monkeypatch) -> None:
    message = '低绩效和考勤异常交叉统计一下'
    candidates = retrieve_skills(message, normalized_query=message, top_k=16)
    assert candidates[0].skill_id == 'smart.data_query'
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        planner.llm_client._set_last_call_meta({  # type: ignore[attr-defined]
            'status': 'timeout',
            'attempt': 0,
            'model': 'fake-model',
            'provider': 'unit-test',
            'latency_ms': 8000,
        })
        return None

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill(message, _ctx(), candidates)

    assert plan.selected_skill == 'smart.data_query'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.slot_values['question'] == message
    assert plan.diagnostics['status'] == 'llm_timeout'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'smart.data_query'


def test_llm_health_circuit_skips_planner_after_failure(monkeypatch) -> None:
    from services.assistant_core.skill_first import llm_health

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM_HEALTH_FAILURE_THRESHOLD', '1')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM_HEALTH_COOLDOWN_SECONDS', '60')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    llm_health.reset()

    llm_health.record_failure('skill_first_planner', {'status': 'timeout', 'latency_ms': 5000})
    candidates = semantic_index.recall_skills('工资这块有没有啥异常', top_k=3)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('planner should be skipped while circuit is open')),
    )

    plan = planner.plan_skill('工资这块有没有啥异常', _ctx(role='finance'), candidates)

    assert plan.selected_skill == 'payroll.anomaly'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.diagnostics['status'] == 'llm_health_circuit_open'
    assert plan.diagnostics['attempted'] is False
    assert plan.diagnostics['llm_health']['state'] == 'open'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['llm_health']['use_case'] == 'skill_first_planner'


def test_llm_health_circuit_isolated_between_understanding_and_planner(monkeypatch) -> None:
    from services.assistant_core.skill_first import llm_health

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM_HEALTH_FAILURE_THRESHOLD', '1')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM_HEALTH_COOLDOWN_SECONDS', '60')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    llm_health.reset()

    llm_health.record_failure('skill_first_understanding', {'status': 'timeout', 'latency_ms': 5000})

    understanding_allowed, understanding_reason, understanding_health = llm_health.availability('skill_first_understanding')
    planner_allowed, planner_reason, planner_health = llm_health.availability('skill_first_planner')

    assert understanding_allowed is False
    assert understanding_reason == 'llm_health_circuit_open'
    assert understanding_health['state'] == 'open'
    assert planner_allowed is True
    assert planner_reason == 'available'
    assert planner_health['state'] == 'closed'
    assert llm_health.snapshot()['by_use_case']['skill_first_understanding']['state'] == 'open'


def test_understanding_circuit_does_not_block_planner_or_hard_guess_weak_recall(monkeypatch) -> None:
    from services.assistant_core.skill_first import llm_health

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM_HEALTH_FAILURE_THRESHOLD', '1')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM_HEALTH_COOLDOWN_SECONDS', '60')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    llm_health.reset()
    seen = {'planner': 0}

    def fake_json_chat_profile(*args, **kwargs):
        seen['planner'] += 1
        planner.llm_client._set_last_call_meta({  # type: ignore[attr-defined]
            'status': 'success',
            'attempt': 0,
            'model': 'fake-model',
            'provider': 'unit-test',
            'latency_ms': 12,
        })
        return {
            'normalized_query': '查一下',
            'selected_skill': None,
            'confidence': 0.18,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'user_request_too_ambiguous',
            'rejected_skills': [],
        }

    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        fake_json_chat_profile,
    )
    llm_health.record_failure('skill_first_understanding', {'status': 'timeout', 'latency_ms': 5000})
    candidates = [
        semantic_index.RecallResult(
            skill_id='approval.mine',
            score=2.2,
            matched_text='weak_generic_help_signal',
            match_reason='card_semantic_overlap',
        ),
        semantic_index.RecallResult(
            skill_id='candidate.search',
            score=2.1,
            matched_text='weak_generic_search_signal',
            match_reason='card_semantic_overlap',
        ),
    ]

    plan = planner.plan_skill('查一下', _ctx(), candidates)

    assert plan.selected_skill is None
    assert plan.planner_source == 'llm'
    assert plan.fallback_reason == 'llm_planner_unusable'
    assert seen['planner'] == 1
    assert plan.diagnostics['status'] == 'llm_returned_null_skill'
    assert plan.diagnostics['attempted'] is True
    assert plan.diagnostics['deterministic_fallback_blocked'] is True
    assert plan.diagnostics['degraded_recovery_used'] is False
    assert plan.diagnostics['llm_health']['state'] == 'closed'
    assert plan.diagnostics['llm_health']['use_case'] == 'skill_first_planner'


def test_planner_recovers_when_llm_returns_null_skill_but_recall_is_structurally_clear(monkeypatch) -> None:
    candidates = retrieve_skills('现在在招聘的岗位有哪些', top_k=8)
    assert candidates[0].skill_id == 'recruitment.open_jobs'
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        return {
            'normalized_query': '查询当前在招岗位',
            'selected_skill': None,
            'confidence': 0.0,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'llm_no_decision',
            'rejected_skills': [],
        }

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill('现在在招聘的岗位有哪些', _job_page_ctx(), candidates)

    assert plan.selected_skill == 'recruitment.open_jobs'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.diagnostics['status'] == 'llm_returned_null_skill'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'recruitment.open_jobs'
    assert plan.diagnostics['retry_decision']['attempted'] is True
    assert plan.diagnostics['retry_decision']['accepted'] is False


def test_planner_recovers_candidate_search_null_skill_when_schema_slots_are_clear(monkeypatch) -> None:
    message = '候选人里找一下孙悦'
    candidates = retrieve_skills(message, normalized_query=message, top_k=16)
    assert candidates[0].skill_id == 'candidate.search'
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        return {
            'normalized_query': message,
            'selected_skill': None,
            'confidence': 0.0,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'llm_no_decision',
            'rejected_skills': [],
        }

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill(message, _ctx(), candidates)

    assert plan.selected_skill == 'candidate.search'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.slot_values['keyword'] == '孙悦'
    assert plan.diagnostics['status'] == 'llm_returned_null_skill'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'candidate.search'
    assert plan.diagnostics['degraded_recovery_assessment']['reason'] == (
        'schema_slots_support_top_candidate_despite_soft_anti_overlap'
    )


def test_kernel_planner_recovery_assesses_explicit_object_read_slots() -> None:
    from services.assistant_core.agent_kernel import planner_recovery
    from services.assistant_core.skill_first.cards import get_card
    from services.assistant_core.skill_first.planner import fill_slots
    from services.assistant_core.guardrails import detect_write_intent

    message = '候选人里找一下孙悦'
    candidates = retrieve_skills(message, normalized_query=message, top_k=16)
    assessment = planner_recovery.assess_llm_recovery(
        message,
        _ctx(),
        candidates,
        get_card=get_card,
        fill_slots=fill_slots,
        detect_write_intent=detect_write_intent,
    )

    assert assessment['allowed'] is True
    assert assessment['reason'] in {
        'schema_slots_support_top_candidate_despite_soft_anti_overlap',
        'explicit_object_read_schema_slots',
        'anti_examples_clear',
    }
    assert 'keyword' in assessment['slot_keys']


def test_kernel_planner_recovery_retry_gate_accepts_structural_recall() -> None:
    from types import SimpleNamespace
    from services.assistant_core.agent_kernel import planner_recovery

    candidates = [
        SimpleNamespace(score=5.2, anti_score=0.9, match_reason='candidate_signal:structural_intent:recruitment.open_jobs'),
        SimpleNamespace(score=5.1, anti_score=0.0, match_reason='semantic_user_text'),
    ]

    assert planner_recovery.should_retry_planner_decision(candidates) is True


def test_kernel_planner_recovery_builds_guarded_degraded_plan() -> None:
    from services.assistant_core.agent_kernel import planner_recovery
    from services.assistant_core.guardrails import detect_write_intent
    from services.assistant_core.skill_first.cards import get_card
    from services.assistant_core.skill_first.planner import fill_slots

    message = '候选人里找一下孙悦'
    candidates = retrieve_skills(message, normalized_query=message, top_k=16)
    guard_seen: dict[str, object] = {}

    def guard_plan(message, ctx, candidates, plan):
        guard_seen['called'] = True
        guard_seen['selected_skill'] = plan.selected_skill
        return plan

    plan = planner_recovery.llm_unusable_recovery_plan(
        message,
        _ctx(),
        candidates,
        {'status': 'llm_timeout', 'attempted': True},
        normalize_query=semantic_index.normalize_query,
        get_card=get_card,
        fill_slots=fill_slots,
        missing_required_slots=planner._missing_required_slots,  # type: ignore[attr-defined]
        detect_write_intent=detect_write_intent,
        min_confidence=planner.MIN_CONFIDENCE,
        guard_plan=guard_plan,
    )

    assert guard_seen == {'called': True, 'selected_skill': 'candidate.search'}
    assert plan.selected_skill == 'candidate.search'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.slot_values['keyword'] == '孙悦'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'candidate.search'


def test_planner_recovers_candidate_search_timeout_when_schema_slots_are_clear(monkeypatch) -> None:
    message = '候选人里找一下孙悦'
    candidates = retrieve_skills(message, normalized_query=message, top_k=16)
    assert candidates[0].skill_id == 'candidate.search'
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        planner.llm_client._set_last_call_meta({  # type: ignore[attr-defined]
            'status': 'timeout',
            'attempt': 0,
            'model': 'fake-model',
            'provider': 'unit-test',
            'latency_ms': 8000,
        })
        return None

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill(message, _ctx(), candidates)

    assert plan.selected_skill == 'candidate.search'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.slot_values['keyword'] == '孙悦'
    assert plan.diagnostics['status'] == 'llm_timeout'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'candidate.search'
    assert plan.diagnostics['degraded_recovery_assessment']['reason'] in {
        'schema_slots_support_top_candidate_despite_soft_anti_overlap',
        'explicit_object_read_schema_slots',
    }


def test_planner_recovers_candidate_search_low_confidence_when_schema_slots_are_clear(monkeypatch) -> None:
    message = '候选人里找一下孙悦'
    candidates = retrieve_skills(message, normalized_query=message, top_k=16)
    assert candidates[0].skill_id == 'candidate.search'
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        return {
            'normalized_query': message,
            'selected_skill': 'candidate.evaluation',
            'confidence': 0.12,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'llm_under_confident_candidate_query',
            'rejected_skills': [],
        }

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill(message, _ctx(), candidates)

    assert plan.selected_skill == 'candidate.search'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.slot_values['keyword'] == '孙悦'
    assert plan.diagnostics['status'] == 'llm_low_confidence'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_requires_schema_grounding'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'candidate.search'


def test_planner_retry_turns_conservative_null_into_llm_decision(monkeypatch) -> None:
    message = '给全员推一条 HR 通知：明天下午三点全员培训'
    candidates = retrieve_skills(message, normalized_query=message, top_k=8)
    assert any(item.skill_id == 'notification.create_confirm' for item in candidates[:3])
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    calls: list[str] = []

    def fake_json_chat_profile(*args, **kwargs):
        messages = args[1] if len(args) > 1 else kwargs.get('messages')
        payload = json.loads(messages[-1]['content'])
        mode = payload['strict_contract']['planner_mode']
        calls.append(mode)
        if mode == 'skill_decision_lite':
            return {
                'normalized_query': '创建全员 HR 通知',
                'selected_skill': None,
                'confidence': 0.2,
                'slot_values': {},
                'missing_slots': ['title'],
                'route_reason': 'first_pass_too_conservative',
                'rejected_skills': [],
            }
        return {
            'normalized_query': '创建全员 HR 通知',
            'selected_skill': 'notification.create_confirm',
            'confidence': 0.82,
            'slot_values': {'title': '明天下午三点全员培训'},
            'missing_slots': [],
            'route_reason': 'retry_selected_side_effect_skill_pending_confirmation',
            'rejected_skills': [],
        }

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill(message, _ctx(), candidates)

    assert calls == ['skill_decision_lite', 'skill_decision_retry']
    assert plan.selected_skill == 'notification.create_confirm'
    assert plan.planner_source == 'llm'
    assert plan.diagnostics['accepted'] is True
    assert plan.diagnostics['retry_decision']['accepted'] is True
    assert plan.diagnostics['retry_decision']['prompt_mode'] == 'skill_decision_retry'


def test_kernel_planner_recovery_retry_decision_runs_bounded_llm_loop() -> None:
    from services.assistant_core.agent_kernel import planner_recovery
    from services.assistant_core.agent_kernel.planning import SkillPlan

    message = '给全员推一条 HR 通知：明天下午三点全员培训'
    candidates = retrieve_skills(message, normalized_query=message, top_k=8)
    diagnostics = {'status': 'llm_returned_null_skill', 'attempted': True}
    calls: dict[str, object] = {}

    def retry_messages(msg, ctx, top_candidates, understanding, first_pass_status):
        calls['candidate_count'] = len(top_candidates)
        calls['first_pass_status'] = first_pass_status
        return [{'role': 'user', 'content': 'retry'}]

    def fake_llm_json_chat_profile(*args, **kwargs):
        calls['use_case'] = kwargs['use_case']
        calls['timeout'] = kwargs['timeout']
        return {
            'selected_skill': 'notification.create_confirm',
            'confidence': 0.83,
            'slot_values': {'title': '明天下午三点全员培训'},
            'route_reason': 'retry_selected',
        }

    plan = planner_recovery.retry_planner_decision(
        message,
        _ctx(),
        candidates,
        None,
        diagnostics,
        first_pass_status='llm_returned_null_skill',
        retry_candidate_limit=3,
        retry_prompt_mode='skill_decision_retry',
        min_confidence=planner.MIN_CONFIDENCE,
        planner_timeout=lambda: 20,
        planner_retry_messages=retry_messages,
        normalize_llm_plan=lambda raw, msg, top: SkillPlan(
            normalized_query=msg,
            selected_skill=raw['selected_skill'],
            confidence=raw['confidence'],
            slot_values=raw['slot_values'],
            route_reason=raw['route_reason'],
            planner_source='llm',
        ),
        diagnostic_status_from_llm_meta=lambda meta: str(meta.get('status') or 'invalid_response'),
        llm_json_chat_profile=fake_llm_json_chat_profile,
        llm_last_call_meta=lambda: {'status': 'success', 'latency_ms': 12},
        record_call_result=lambda use_case, meta: {'use_case': use_case, 'state': 'closed', 'status': meta['status']},
        record_failure=lambda use_case, meta: {'use_case': use_case, 'state': 'open'},
    )

    assert plan is not None
    assert calls == {
        'candidate_count': 3,
        'first_pass_status': 'llm_returned_null_skill',
        'use_case': 'skill_first_planner',
        'timeout': 10,
    }
    assert plan.selected_skill == 'notification.create_confirm'
    assert plan.planner_source == 'llm'
    assert plan.diagnostics['accepted'] is True
    assert plan.diagnostics['retry_decision']['accepted'] is True
    assert plan.diagnostics['retry_decision']['prompt_mode'] == 'skill_decision_retry'
    assert plan.diagnostics['llm_health']['use_case'] == 'skill_first_planner'


def test_planner_recovers_open_jobs_after_llm_timeout_with_normalized_query_noise(monkeypatch) -> None:
    candidates = retrieve_skills(
        '现在在招聘的岗位有哪些',
        normalized_query='现在在招聘的岗位有哪些 岗位 候选人 简历 面试 offer 招人',
        top_k=8,
    )
    assert candidates[0].skill_id == 'recruitment.open_jobs'
    assert candidates[0].anti_score == 0
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)

    def fake_json_chat_profile(*args, **kwargs):
        planner.llm_client._set_last_call_meta({  # type: ignore[attr-defined]
            'status': 'timeout',
            'attempt': 0,
            'model': 'fake-model',
            'provider': 'siliconflow',
            'latency_ms': 6079,
        })
        return None

    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)

    plan = planner.plan_skill('现在在招聘的岗位有哪些', _job_page_ctx(), candidates)

    assert plan.selected_skill == 'recruitment.open_jobs'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.diagnostics['status'] == 'llm_timeout'
    assert plan.diagnostics['degraded_recovery_used'] is True
    assert plan.diagnostics['degraded_recovery_skill'] == 'recruitment.open_jobs'


def test_planner_recovers_when_llm_is_too_conservative_but_top_candidate_is_clear(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('工资这块有没有啥异常', top_k=3)
    assert candidates[0].skill_id == 'payroll.anomaly'
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: {
            'normalized_query': '查询薪资异常',
            'selected_skill': 'payroll.anomaly',
            'confidence': 0.32,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'llm_too_conservative_despite_clear_schema',
            'rejected_skills': [],
        },
    )

    plan = planner.plan_skill('工资这块有没有啥异常', _ctx(), candidates)

    assert plan.selected_skill == 'payroll.anomaly'
    assert plan.planner_source == 'llm_degraded_recovery'
    assert plan.fallback_reason is None
    assert plan.diagnostics['status'] == 'low_confidence'
    assert plan.diagnostics['low_confidence_recovery_attempted'] is True
    assert plan.diagnostics['degraded_recovery_used'] is True


def test_planner_diagnostics_explain_low_confidence_llm(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('工资这块有没有啥异常', top_k=3)
    assert any(item.skill_id == 'payroll.anomaly' for item in candidates)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: {
            'normalized_query': '查询薪资异常',
            'selected_skill': 'payroll.anomaly',
            'confidence': 0.19,
            'slot_values': {},
            'missing_slots': [],
            'route_reason': 'llm_unsure_between_payroll_cards',
            'rejected_skills': [],
        },
    )

    plan = planner.plan_skill('工资这块有没有啥异常', _ctx(), candidates)

    assert plan.selected_skill is None
    assert plan.planner_source == 'llm'
    assert plan.fallback_reason == 'llm_low_confidence'
    assert plan.diagnostics['attempted'] is True
    assert plan.diagnostics['status'] == 'low_confidence'
    assert plan.diagnostics['accepted'] is False
    assert plan.diagnostics['raw_selected_skill'] == 'payroll.anomaly'


def test_bigtool_style_skill_retriever_merges_llm_hints_into_candidates() -> None:
    understanding = UnderstandingResult(
        normalized_query='评估候选人吴明华并说明依据',
        intent_summary='用户要评估候选人，不是搜索候选人列表',
        domain_hints=['candidate'],
        candidate_skill_hints=['candidate.evaluation'],
        confidence=0.9,
        source='llm',
    )

    candidates = retrieve_skills('分析一下候选人吴明华怎么样，并说明依据', understanding=understanding, top_k=8)
    ids = [item.skill_id for item in candidates]

    assert 'candidate.evaluation' in ids
    evaluation = next(item for item in candidates if item.skill_id == 'candidate.evaluation')
    assert 'candidate_signal:llm_skill_hint' in evaluation.match_reason
    assert evaluation.score < 40


def test_runtime_records_understanding_and_dynamic_retrieval_trace(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(
        runtime,
        'understand_query',
        lambda message, ctx: UnderstandingResult(
            normalized_query='查询薪酬异常',
            intent_summary='薪酬异常分析',
            domain_hints=['payroll'],
            candidate_skill_hints=['payroll.anomaly'],
            confidence=0.88,
            source='llm',
        ),
    )
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', lambda *args, **kwargs: None)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')

    result = runtime.try_run('钱这块有没有不对劲', _ctx())

    assert result is not None
    trace = result.copilot['routeTrace']
    assert trace['understanding_result']['source'] == 'llm'
    assert trace['understanding_result']['candidate_skill_hints'] == ['payroll.anomaly']
    assert trace['skill_retrieval_trace']['sources']
    assert trace['selected_skill'] == 'payroll.anomaly'


def test_runtime_trace_records_llm_attempt_diagnostics(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.skill_first import understanding

    seen: dict = {}

    def fake_json_chat_profile(*args, **kwargs):
        use_case = kwargs.get('use_case')
        seen[use_case] = seen.get(use_case, 0) + 1
        if use_case == 'skill_first_understanding':
            return {
                'normalized_query': '查询薪酬异常',
                'intent_summary': '用户想看薪酬异常',
                'domain_hints': ['payroll'],
                'entity_mentions': {},
                'slot_hints': {},
                'reference_hints': {},
                'candidate_skill_hints': ['payroll.anomaly'],
                'confidence': 0.86,
            }
        if use_case == 'skill_first_planner':
            return {
                'normalized_query': '查询薪酬异常',
                'selected_skill': 'payroll.anomaly',
                'confidence': 0.89,
                'slot_values': {'question': '钱这块有没有不对劲'},
                'missing_slots': [],
                'route_reason': 'llm_read_skill_schema_and_selected_payroll_anomaly',
                'rejected_skills': [],
            }
        return None

    def fake_execute(self, tool, params, ctx):
        return {
            'ok': True,
            'tool': tool,
            'data': {'summary_hint': '薪酬异常检查完成。', 'entities': [], 'widgets': []},
            'rows_count': 1,
        }

    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_UNDERSTANDING', raising=False)
    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_LLM', raising=False)
    monkeypatch.setattr(understanding.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(understanding.llm_client, 'json_chat_profile', fake_json_chat_profile)
    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', fake_json_chat_profile)
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('钱这块有没有不对劲', _ctx(role='finance'))

    assert result is not None
    trace = result.copilot['routeTrace']
    assert seen['skill_first_understanding'] == 1
    assert seen['skill_first_planner'] == 1
    assert trace['understanding_diagnostics']['status'] == 'accepted'
    assert trace['understanding_diagnostics']['attempted'] is True
    assert trace['planner_diagnostics']['status'] == 'accepted'
    assert trace['planner_diagnostics']['accepted'] is True
    assert trace['planner_source'] == 'llm'
    planning_node = next(node for node in trace['kernel']['nodes'] if node['node'] == 'planning')
    assert planning_node['detail']['llm_status'] == 'accepted'
    assert planning_node['detail']['llm_attempted'] is True


def test_skill_first_llm_nodes_use_configurable_timeouts(monkeypatch) -> None:
    from services.assistant_core.skill_first import understanding

    seen: dict = {}

    def fake_json_chat_profile(*args, **kwargs):
        use_case = kwargs.get('use_case')
        seen[use_case] = kwargs.get('timeout')
        if use_case == 'skill_first_understanding':
            return {
                'normalized_query': '查询薪酬异常',
                'intent_summary': '用户想看薪酬异常',
                'domain_hints': ['payroll'],
                'entity_mentions': {},
                'slot_hints': {},
                'reference_hints': {},
                'candidate_skill_hints': ['payroll.anomaly'],
                'confidence': 0.86,
            }
        if use_case == 'skill_first_planner':
            return {
                'normalized_query': '查询薪酬异常',
                'selected_skill': 'payroll.anomaly',
                'confidence': 0.89,
                'slot_values': {'question': '钱这块有没有不对劲'},
                'missing_slots': [],
                'route_reason': 'llm_read_skill_schema_and_selected_payroll_anomaly',
                'rejected_skills': [],
            }
        return None

    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_UNDERSTANDING', raising=False)
    monkeypatch.delenv('ASSISTANT_SKILL_FIRST_LLM', raising=False)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_UNDERSTANDING_TIMEOUT', '21')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_PLANNER_TIMEOUT', '22')
    monkeypatch.setattr(understanding.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(understanding.llm_client, 'json_chat_profile', fake_json_chat_profile)

    understood = understanding.understand_query('钱这块有没有不对劲', _ctx(role='finance'))
    candidates = semantic_index.recall_skills('钱这块有没有不对劲', top_k=8)
    plan = planner.plan_skill('钱这块有没有不对劲', _ctx(role='finance'), candidates, understanding=understood)

    assert seen['skill_first_understanding'] == 21
    assert seen['skill_first_planner'] == 22
    assert understood.diagnostics['timeout_seconds'] == 21
    assert plan.diagnostics['timeout_seconds'] == 22
    assert plan.planner_source == 'llm'


def test_llm_planner_can_be_explicitly_disabled(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('工资这块有没有啥异常', top_k=3)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('LLM planner should be disabled')),
    )

    plan = planner.plan_skill('工资这块有没有啥异常', _ctx(), candidates)

    assert plan.planner_source == 'deterministic'
    assert plan.selected_skill == 'payroll.anomaly'


def test_llm_planner_cannot_inject_sql_into_smart_data_query(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('帮我交叉统计一下低绩效和考勤异常', top_k=8)
    assert any(item.skill_id == 'smart.data_query' for item in candidates)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: {
            'normalized_query': '低绩效和考勤异常交叉统计',
            'selected_skill': 'smart.data_query',
            'confidence': 0.91,
            'slot_values': {
                'question': '低绩效和考勤异常交叉统计',
                'sql': 'DELETE FROM employees',
                'explanation': 'malicious planner sql',
                'limit': 5000,
            },
            'missing_slots': [],
            'route_reason': 'llm_selected_smart_query',
            'rejected_skills': [],
        },
    )

    plan = planner.plan_skill('帮我交叉统计一下低绩效和考勤异常', _ctx(), candidates)
    card = cards.get_card('smart.data_query')
    decision = planner.build_route_decision(card, plan)  # type: ignore[arg-type]

    assert plan.selected_skill == 'smart.data_query'
    assert plan.planner_source == 'llm'
    assert plan.slot_values['question'] == '帮我交叉统计一下低绩效和考勤异常'
    assert 'sql' not in plan.slot_values
    assert 'explanation' not in plan.slot_values
    assert decision.tool_plan[0].input['question'] == '帮我交叉统计一下低绩效和考勤异常'
    assert 'sql' not in decision.tool_plan[0].input


def test_explicit_candidate_name_overrides_stale_reference_id(monkeypatch) -> None:
    message = '孙悦的个人能力怎么样，符合我们的电子工程师岗位要求吗'
    candidates = semantic_index.recall_skills(message, top_k=8)
    assert any(item.skill_id == 'candidate.job_fit' for item in candidates)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(
        planner.workset_store,
        'resolve_mention',
        lambda *args, **kwargs: {
            'item': {'entity_type': 'candidate', 'entity_id': 'demo-cand-luowei', 'title': '罗伟'},
            'workset': {'id': 'ws-candidates', 'entity_type': 'candidate'},
        },
    )
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: {
            'normalized_query': message,
            'selected_skill': 'candidate.job_fit',
            'confidence': 0.91,
            'slot_values': {
                'keyword': '孙悦',
                'candidate_id': 'demo-cand-luowei',
                'job_keyword': '电子工程师',
            },
            'missing_slots': [],
            'route_reason': 'llm_selected_candidate_job_fit',
            'rejected_skills': [],
        },
    )

    plan = planner.plan_skill(message, _ctx(), candidates)
    card = cards.get_card('candidate.job_fit')
    decision = planner.build_route_decision(card, plan)  # type: ignore[arg-type]

    assert plan.selected_skill == 'candidate.job_fit'
    assert plan.slot_values['keyword'] == '孙悦'
    assert plan.slot_values['job_keyword'] == '电子工程师'
    assert 'candidate_id' not in plan.slot_values
    assert 'resume_id' not in plan.slot_values
    assert decision.tool_plan[0].input['keyword'] == '孙悦'
    assert 'candidate_id' not in decision.tool_plan[0].input


def test_llm_planner_cannot_fabricate_side_effect_slots(monkeypatch) -> None:
    candidates = semantic_index.recall_skills('给第二个安排面试', top_k=8)
    assert any(item.skill_id == 'interview.schedule_confirm_create' for item in candidates)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(planner.workset_store, 'resolve_mention', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        planner.llm_client,
        'json_chat_profile',
        lambda *args, **kwargs: {
            'normalized_query': '给第二个安排面试',
            'selected_skill': 'interview.schedule_confirm_create',
            'confidence': 0.94,
            'slot_values': {
                'target_candidate': 'fabricated-candidate',
                'resume_id': 'resume-from-llm',
                'job_id': 'job-from-llm',
                'scheduled_at': '2026-06-04 10:00',
            },
            'missing_slots': [],
            'route_reason': 'llm_fabricated_side_effect_slots',
            'rejected_skills': [],
        },
    )

    plan = planner.plan_skill('给第二个安排面试', _ctx(), candidates)

    assert plan.selected_skill == 'interview.schedule_confirm_create'
    assert plan.fallback_reason == 'missing_required_side_effect_slots'
    assert 'target_candidate' in plan.missing_slots
    assert 'resume_id' not in plan.slot_values
    assert 'job_id' not in plan.slot_values


def test_slot_reference_node_uses_llm_refiner_for_readonly_schema_slots(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.skill_first import slot_reference_refiner

    seen: dict = {}

    def fake_json_chat_profile(*args, **kwargs):
        if kwargs.get('use_case') == 'skill_first_slot_reference':
            seen['slot_refiner_called'] = True
            return {
                'slot_values': {'recent_days': 14, 'top_n': 6, 'question': '最近两周挑六份简历看看'},
                'missing_slots': [],
                'confidence': 0.86,
                'reason': 'LLM extracted colloquial recent window and count from user text',
            }
        return None

    def fake_execute(self, tool, params, ctx):
        seen['tool'] = tool
        seen['params'] = dict(params)
        return {'ok': True, 'tool': tool, 'data': {'summary_hint': '近两周简历 0 份。'}, 'rows_count': 0}

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_SLOT_LLM', '1')
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'json_chat_profile', fake_json_chat_profile)
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'chat_profile', lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('最近两周挑六份简历看看', _ctx())

    assert result is not None
    trace = result.copilot['routeTrace']
    assert trace['selected_skill'] == 'candidate.recent_resumes'
    assert seen['slot_refiner_called'] is True
    assert seen['params']['recent_days'] == 14
    assert seen['params']['top_n'] == 6
    assert trace['slot_reference_result']['refiner']['source'] == 'llm'
    assert trace['slot_reference_result']['refiner']['applied'] is True
    assert trace['slot_reference_result']['refiner']['timeout_seconds'] == 8


def test_slot_reference_refiner_uses_configurable_timeout(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.skill_first import slot_reference_refiner

    seen: dict = {}

    def fake_json_chat_profile(*args, **kwargs):
        if kwargs.get('use_case') == 'skill_first_slot_reference':
            seen['timeout'] = kwargs.get('timeout')
            return {
                'slot_values': {'recent_days': 10, 'top_n': 3, 'question': '最近十天挑三份简历看看'},
                'missing_slots': [],
                'confidence': 0.84,
                'reason': 'LLM extracted recent-days and top-n slots',
            }
        return None

    def fake_execute(self, tool, params, ctx):
        seen['params'] = dict(params)
        return {'ok': True, 'tool': tool, 'data': {'summary_hint': '近十天简历 0 份。'}, 'rows_count': 0}

    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '0')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_SLOT_LLM', '1')
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_SLOT_TIMEOUT', '17')
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'json_chat_profile', fake_json_chat_profile)
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'chat_profile', lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('最近十天挑三份简历看看', _ctx())

    assert result is not None
    trace = result.copilot['routeTrace']
    assert seen['timeout'] == 17
    assert seen['params']['recent_days'] == 10
    assert seen['params']['top_n'] == 3
    assert trace['slot_reference_result']['refiner']['timeout_seconds'] == 17


def test_slot_reference_refiner_cannot_fabricate_side_effect_ids(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.skill_first import slot_reference_refiner

    def fake_plan_skill(message, ctx, candidates, understanding=None):
        return planner.SkillPlan(
            normalized_query='同意这个审批',
            selected_skill='approval.confirm_action',
            confidence=0.91,
            slot_values={'action': 'approve', 'question': message},
            missing_slots=['approval_id'],
            route_reason='test_fixed_approval_action',
            planner_source='deterministic',
        )

    def fake_json_chat_profile(*args, **kwargs):
        if kwargs.get('use_case') == 'skill_first_slot_reference':
            return {
                'slot_values': {
                    'approval_id': 'approval-from-llm',
                    'action': 'approve',
                    'comment': '同意',
                },
                'missing_slots': [],
                'confidence': 0.9,
                'reason': 'malicious fabricated approval id',
            }
        return None

    monkeypatch.setattr(runtime, 'plan_skill', fake_plan_skill)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_SLOT_LLM', '1')
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'json_chat_profile', fake_json_chat_profile)
    monkeypatch.setattr(slot_reference_refiner.llm_client, 'chat_profile', lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('同意这个审批', _ctx())

    assert result is not None
    trace = result.copilot['routeTrace']
    assert trace['selected_skill'] == 'approval.confirm_action'
    assert trace['fallback_reason'] in {'missing_required_side_effect_slots', 'low_confidence'}
    assert 'approval_id' not in trace['slot_reference_result']['slot_values']
    assert {
        'field': 'approval_id',
        'reason': 'side_effect_id_not_trusted_from_llm',
    } in trace['slot_reference_result']['refiner']['rejected_fields']
    assert _kernel_node_names(result)[-1] == 'observability'
    assert 'risk_gate' in _kernel_node_names(result)


def test_agent_kernel_slot_normalizer_cleans_colloquial_employee_entity_before_tool(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    seen: dict = {}

    def fake_plan_skill(message, ctx, candidates, understanding=None):
        return planner.SkillPlan(
            normalized_query='查看吴明华员工画像',
            selected_skill='employee.profile',
            confidence=0.89,
            slot_values={'keyword': '吴明华这个', 'question': message},
            missing_slots=[],
            route_reason='test_llm_returned_colloquial_employee_suffix',
            planner_source='llm',
            diagnostics={'attempted': True, 'accepted': True, 'status': 'accepted'},
        )

    def fake_execute(self, tool, params, ctx):
        seen['tool'] = tool
        seen['params'] = dict(params)
        return {
            'ok': True,
            'tool': tool,
            'data': {'summary_hint': f'员工画像：{params.get("keyword")}', 'entities': [], 'widgets': []},
            'rows_count': 1,
        }

    monkeypatch.setattr(runtime, 'plan_skill', fake_plan_skill)
    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('吴明华这个员工最近状态如何', _ctx())

    assert result is not None
    assert seen['tool'] == 'employee_evidence_bundle'
    assert seen['params']['keyword'] == '吴明华'
    trace = result.copilot['routeTrace']
    assert trace['selected_skill'] == 'employee.profile'
    normalizer = trace['slot_reference_result']['refiner']['normalizer']
    assert normalizer['applied'] is True
    assert {
        'field': 'keyword',
        'before': '吴明华这个',
        'after': '吴明华',
        'reason': 'trimmed_colloquial_entity_wrapper',
    } in normalizer['changes']
    assert trace['slot_reference_result']['slot_values']['keyword'] == '吴明华'
    assert '+normalizer' in trace['slot_reference_result']['resolution_source']


def test_side_effect_skill_builds_pending_confirmation_not_direct_execution(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    calls: list[str] = []

    def fake_prepare(message, ctx, decision):
        calls.append(decision.tool_plan[0].tool)
        result = ExecutionResult(
            summary='安排面试：第二位；时间：待确认。确认后将在系统中创建记录。',
            widgets=[{'type': 'confirmation_card', 'actions': [{'label': '确认'}]}],
            session_id=ctx.session_id,
            route_decision=decision,
            requires_confirmation=True,
            actions=[{'label': '确认'}],
            answer={'content': '待确认', 'format': 'text'},
        )
        result._pending_action = {
            'id': 'act-test',
            'label': '安排复试',
            'tools': [{'tool': 'interview_create', 'input': {}}],
        }
        return result

    monkeypatch.setattr(runtime, '_prepare_action_confirmation', fake_prepare)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr(planner.workset_store, 'resolve_mention', lambda *args, **kwargs: {
        'kind': 'item',
        'item': {'entity_id': 'c-2', 'title': '第二位候选人'},
        'workset': {'id': 'ws-1', 'entity_type': 'candidate'},
    })

    result = runtime.try_run('给第二个安排面试', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert getattr(result, '_pending_action')['tools'][0]['tool'] == 'interview_create'
    assert calls == ['interview_create']
    assert result.copilot['routeTrace']['selected_skill'] == 'interview.schedule_confirm_create'
    assert result.copilot['routeTrace']['output_verification_result'] == 'ok'


def test_approval_todo_creates_approval_workset_and_confirm_action_uses_first_item(model_db, monkeypatch) -> None:
    from models import ApprovalInstance, ApprovalRecord, db
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.workset_store import default_store

    default_store.clear()
    now = datetime.utcnow()
    db.session.add_all([
        ApprovalInstance(
            id='ap-newer',
            business_type='employee_request',
            business_id='leave-newer',
            title='吴明华请假申请',
            applicant_id='u-other',
            approver_id='u-skill-first',
            status='pending',
            created_at=now,
        ),
        ApprovalInstance(
            id='ap-older',
            business_type='employee_request',
            business_id='leave-older',
            title='李雷加班申请',
            applicant_id='u-other',
            approver_id='u-skill-first',
            status='pending',
            created_at=now - timedelta(days=1),
        ),
    ])
    db.session.commit()
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    todo = runtime.try_run('我这边还有哪些待办审批', _ctx())

    assert todo is not None
    assert todo.copilot['routeTrace']['selected_skill'] == 'approval.todo'
    assert todo.worksets
    assert todo.worksets[0]['entity_type'] == 'approval'
    assert todo.worksets[0]['items'][0]['entity_id'] == 'ap-newer'

    confirm = runtime.try_run('同意第一条请假申请，意见：同意请假', _ctx())

    assert confirm is not None
    assert confirm.requires_confirmation is True
    assert confirm.copilot['routeTrace']['selected_skill'] == 'approval.confirm_action'
    assert confirm.copilot['routeTrace']['slot_fill_result']['slot_values']['approval_id'] == 'ap-newer'
    assert confirm.copilot['routeTrace']['slot_reference_result']['reference_detected'] is True
    assert confirm.copilot['routeTrace']['slot_reference_result']['workset_reference_detected'] is True
    assert getattr(confirm, '_pending_action')['tools'][0]['tool'] == 'approval_decision'
    assert getattr(confirm, '_pending_action')['tools'][0]['input'] == {
        'approval_id': 'ap-newer',
        'action': 'approve',
        'comment': '同意请假',
    }
    assert ApprovalInstance.query.get('ap-newer').status == 'pending'
    assert ApprovalRecord.query.filter_by(approval_id='ap-newer').count() == 0


def test_approval_confirm_action_can_ground_ranked_pending_approval_without_workset(model_db, monkeypatch) -> None:
    from models import ApprovalInstance, ApprovalRecord, db
    from services.assistant_core.skill_first import runtime
    from services.assistant_core.workset_store import default_store

    default_store.clear()
    now = datetime.utcnow()
    db.session.add_all([
        ApprovalInstance(
            id='ap-ground-leave-newer',
            business_type='employee_request',
            business_id='leave-ground-newer',
            title='吴明华请假申请',
            applicant_id='u-other',
            approver_id='u-skill-first',
            status='pending',
            created_at=now,
        ),
        ApprovalInstance(
            id='ap-ground-expense-older',
            business_type='expense',
            business_id='expense-ground-older',
            title='李雷报销申请',
            applicant_id='u-other',
            approver_id='u-skill-first',
            status='pending',
            created_at=now - timedelta(days=1),
        ),
    ])
    db.session.commit()
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('同意第一条请假申请', _ctx(session_id='s-approval-grounding'))

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'approval.confirm_action'
    assert result.copilot['routeTrace']['slot_reference_result']['refiner']['grounding']['applied'] is True
    assert result.copilot['routeTrace']['slot_fill_result']['missing_slots'] == []
    assert getattr(result, '_pending_action')['tools'][0]['input']['approval_id'] == 'ap-ground-leave-newer'
    assert getattr(result, '_pending_action')['tools'][0]['input']['action'] == 'approve'
    assert ApprovalInstance.query.get('ap-ground-leave-newer').status == 'pending'
    assert ApprovalRecord.query.filter_by(approval_id='ap-ground-leave-newer').count() == 0


def test_notification_create_confirm_generates_pending_action_without_write(model_db, monkeypatch) -> None:
    from models import Notification
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('给全员推一条 HR 通知：明天下午三点全员培训', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'notification.create_confirm'
    assert result.copilot['routeTrace']['output_verification_result'] == 'ok'
    pending = getattr(result, '_pending_action')
    assert pending['tools'] == [{
        'tool': 'notification_create',
        'input': {
            'title': '明天下午三点全员培训',
            'content': '明天下午三点全员培训',
            'notice_type': 'hr',
            'link_url': '/notifications',
        },
    }]
    assert Notification.query.count() == 0


def _seed_employee_change_data(model_db, *, with_salary: bool = False) -> None:
    from models import Department, Employee, Position, SalaryProfile, db

    db.session.add_all([
        Department(id='d-sf-source', name='运营部', status='active'),
        Department(id='d-sf-target', name='研发部', status='active'),
        Position(id='p-sf-source', title='运营专员', department_id='d-sf-source', status='active'),
        Position(id='p-sf-target', title='研发工程师', department_id='d-sf-target', status='active'),
        Employee(
            id='e-sf-wmh',
            employee_no='ESF001',
            name='吴明华',
            status='active',
            department_id='d-sf-source',
            position_id='p-sf-source',
            job_title='运营专员',
        ),
    ])
    if with_salary:
        db.session.add(SalaryProfile(
            id='sp-sf-wmh',
            employee_id='e-sf-wmh',
            base_salary=12000,
            position_salary=8000,
            performance_salary=4000,
            allowance=1000,
            status='active',
        ))
    db.session.commit()


def test_employee_change_submit_confirm_generates_pending_action_without_write(model_db, monkeypatch) -> None:
    from models import ApprovalInstance, Employee, EmployeeChange, OperationLog
    from services.assistant_core.skill_first import runtime

    _seed_employee_change_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('把吴明华调到研发部，目标岗位：研发工程师，先分析影响并准备确认', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'employee.change_submit_confirm'
    assert result.copilot['routeTrace']['output_verification_result'] == 'ok'
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['employee_id'] == 'e-sf-wmh'
    assert pending_tool['input']['target_department_id'] == 'd-sf-target'
    assert pending_tool['input']['target_position'] == '研发工程师'
    assert EmployeeChange.query.count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0
    assert Employee.query.get('e-sf-wmh').department_id == 'd-sf-source'


def test_employee_change_submit_confirm_recovers_when_llm_planner_is_unusable(model_db, monkeypatch) -> None:
    from models import ApprovalInstance, EmployeeChange, OperationLog
    from services.assistant_core.skill_first import runtime

    _seed_employee_change_data(model_db)
    monkeypatch.setenv('ASSISTANT_SKILL_FIRST_LLM', '1')
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr(planner.llm_client, 'is_available', lambda: True)
    monkeypatch.setattr(planner.llm_client, 'json_chat_profile', lambda *args, **kwargs: None)

    result = runtime.try_run('把吴明华调到研发部准备提交审批', _ctx())

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'employee.change_submit_confirm'
    assert result.copilot['routeTrace']['planner_source'] == 'llm_degraded_recovery'
    assert result.copilot['routeTrace']['planner_diagnostics']['degraded_recovery_assessment']['reason'] == (
        'side_effect_candidate_recovered_for_pending_confirmation'
    )
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['employee_id'] == 'e-sf-wmh'
    assert pending_tool['input']['target_department_id'] == 'd-sf-target'
    assert EmployeeChange.query.count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0


def test_employee_change_impact_followup_submit_reuses_grounded_slots_from_history(
    model_db,
    monkeypatch,
) -> None:
    from services.assistant_core import copilot_orchestrator
    from services.assistant_core.workset_store import default_store

    _seed_employee_change_data(model_db)
    default_store.clear()
    monkeypatch.setattr('services.assistant_core.llm_client.chat_profile', lambda *args, **kwargs: None)

    first = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='员工里找一下吴明华',
        session_id='s-employee-change-followup',
    )
    profile = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='这个人最近状态如何',
        session_id=first['sessionId'],
    )
    impact = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='如果把他调到研发部会影响什么',
        session_id=profile['sessionId'],
    )
    confirm = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='那就准备提交这个调岗审批',
        session_id=impact['sessionId'],
    )

    assert first['meta']['routeDecision']['toolPlan'][0]['input']['keyword'] == '吴明华'
    assert profile['meta']['routeDecision']['toolPlan'][0]['input']['employee_id'] == 'e-sf-wmh'
    assert impact['meta']['routeDecision']['toolPlan'][0]['input']['employee_id'] == 'e-sf-wmh'
    assert impact['meta']['routeDecision']['toolPlan'][0]['input']['keyword'] == '吴明华'
    assert impact['meta']['routeDecision']['toolPlan'][0]['input']['target_department'] == '研发部'
    assert '吴明华' in impact['summary']
    assert '如果把他' not in impact['summary']
    assert confirm['copilot']['routeTrace']['selected_skill'] == 'employee.change_submit_confirm'
    assert confirm['meta']['requiresConfirmation'] is True
    assert any(block.get('kind') == 'confirmation' for block in confirm.get('renderBlocks') or [])
    from models import AssistantSession
    session = AssistantSession.query.get(confirm['sessionId'])
    pending_input = (session.messages[-1]['meta'] or {})['pendingAction']['tools'][0]['input']
    assert pending_input['employee_id'] == 'e-sf-wmh'
    assert pending_input['target_department_id'] == 'd-sf-target'
    assert pending_input['target_department'] == '研发部'


def test_salary_adjustment_submit_confirm_generates_pending_action_without_salary_write(model_db, monkeypatch) -> None:
    from models import ApprovalInstance, EmployeeChange, OperationLog, SalaryProfile
    from services.assistant_core.skill_first import runtime

    _seed_employee_change_data(model_db, with_salary=True)
    before_salary = SalaryProfile.query.get('sp-sf-wmh').to_dict()
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('给吴明华调薪 1800 元，先分析影响并准备确认', _ctx(role='hr_admin'))

    assert result is not None
    assert result.requires_confirmation is True
    assert result.copilot['routeTrace']['selected_skill'] == 'employee.salary_adjustment_submit_confirm'
    assert result.copilot['routeTrace']['output_verification_result'] == 'ok'
    pending_tool = getattr(result, '_pending_action')['tools'][0]
    assert pending_tool['tool'] == 'employee_change_submit'
    assert pending_tool['input']['employee_id'] == 'e-sf-wmh'
    assert pending_tool['input']['salary_adjustment'] == '1800'
    assert EmployeeChange.query.count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0
    assert SalaryProfile.query.get('sp-sf-wmh').to_dict() == before_salary


@pytest.mark.parametrize('role', ['employee', 'viewer', 'recruiter', 'finance'])
def test_employee_change_submit_confirm_forbids_unauthorized_roles_before_pending_action(
    model_db,
    monkeypatch,
    role: str,
) -> None:
    from models import ApprovalInstance, EmployeeChange, OperationLog
    from services.assistant_core.skill_first import runtime

    _seed_employee_change_data(model_db)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('把吴明华调到研发部，先分析影响并准备确认', _ctx(role=role))

    assert result is not None
    assert result.error_code == 'permission_denied'
    assert not hasattr(result, '_pending_action')
    assert result.copilot['routeTrace']['selected_skill'] == 'employee.change_submit_confirm'
    assert result.copilot['routeTrace']['permission_result'] != 'allowed'
    assert _kernel_node_names(result)[-1] == 'observability'
    assert 'permission_gate' in _kernel_node_names(result)
    assert EmployeeChange.query.count() == 0
    assert ApprovalInstance.query.filter_by(business_type='employee_change').count() == 0
    assert OperationLog.query.filter_by(module='employee_changes', action='ai_confirm_submit').count() == 0


def test_runtime_trace_contains_required_observability_fields(monkeypatch) -> None:
    from services.assistant_core.skill_first import runtime

    def fake_execute(self, tool, params, ctx):
        return {
            'ok': True,
            'tool': tool,
            'data': {'summary_hint': '薪资异常检查完成。', 'entities': [], 'widgets': []},
            'rows_count': 1,
        }

    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))

    result = runtime.try_run('工资这块有没有啥异常', _ctx(role='finance'))

    assert result is not None
    trace = result.copilot['routeTrace']
    assert set(REQUIRED_TRACE_FIELDS) <= trace.keys()
    assert trace['selected_skill'] == 'payroll.anomaly'
    assert trace['final_executor'].startswith('ToolExecutor')
    assert trace['permission_result'] == 'allowed'
    assert trace['output_verification_result'] == 'ok'


def test_write_guard_blocked_crud_request_is_captured_as_failure_sample(monkeypatch) -> None:
    from services.assistant_core.agent_kernel import observability as kernel_observability
    from services.assistant_core.skill_first import runtime

    calls: list[str] = []
    captured: list[dict] = []
    traces: list[dict] = []

    def fake_execute(self, tool, params, ctx):
        calls.append(tool)
        raise AssertionError('blocked write intent must not execute business tools')

    monkeypatch.setattr(runtime.ToolExecutor, 'execute', fake_execute)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr(kernel_observability, 'append_route_trace', lambda trace: traces.append(trace))
    monkeypatch.setattr(
        kernel_observability,
        'append_failure_sample',
        lambda kind, trace, extra=None: captured.append({'kind': kind, 'trace': trace, 'extra': extra}),
    )

    result = runtime.try_run('上传一份孙悦的新简历', _ctx())

    assert result is not None
    assert result.error_code == 'write_intent_blocked'
    assert calls == []
    trace = result.copilot['routeTrace']
    assert trace['selected_skill'] == 'system.unsupported_write_intent'
    assert trace['candidate_scores']
    assert trace['fallback_reason'] == 'unsupported_write_intent'
    assert trace['risk_result'] == 'blocked_write_intent'
    assert trace['confirmation_policy'] == 'blocked_before_execution_unless_a_registered_side_effect_skill_exists'
    assert trace['final_executor'] == 'guardrails.detect_write_intent'
    assert trace['output_verification_result'] == 'ok'
    assert result.route_decision.intent == 'system.unsupported_write_intent'
    assert _kernel_node_names(result)[-1] == 'observability'
    assert 'risk_gate' in _kernel_node_names(result)
    assert traces and traces[0]['request_id'] == trace['request_id']
    assert captured
    assert captured[0]['kind'] == 'unsupported_write_intent'
    assert captured[0]['trace']['candidate_scores']


def test_workflow_help_readonly_boundary_does_not_capture_failure_sample(monkeypatch) -> None:
    from services.assistant_core.agent_kernel import observability as kernel_observability
    from services.assistant_core.skill_first import runtime

    captured: list[dict] = []

    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr(kernel_observability, 'append_route_trace', lambda trace: trace)
    monkeypatch.setattr(
        kernel_observability,
        'append_failure_sample',
        lambda kind, trace, extra=None: captured.append({'kind': kind, 'trace': trace, 'extra': extra}),
    )

    result = runtime.try_run('简历上传流程说明', _ctx())

    assert result is not None
    assert result.error_code is None
    assert result.copilot['routeTrace']['selected_skill'] == 'system.workflow_help'
    assert result.copilot['routeTrace']['fallback_reason'] is None
    assert result.copilot['routeTrace']['output_verification_result'] == 'ok'
    assert captured == []


def test_copilot_query_uses_skill_first_before_legacy(model_db, monkeypatch) -> None:
    from services.assistant_core import agentic_runtime
    from services.assistant_core import copilot_orchestrator
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(
        runtime.ToolExecutor,
        'execute',
        lambda self, tool, params, ctx: {
            'ok': True,
            'tool': tool,
            'data': {'summary_hint': '待办审批共有 1 条。', 'entities': [], 'widgets': []},
            'rows_count': 1,
        },
    )
    monkeypatch.setattr(
        agentic_runtime,
        'try_run',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('legacy agentic should not run first')),
    )

    payload = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='我这边还有哪些待办审批',
        request_id='req-main-entry',
    )

    assert payload['copilot']['routePath'] == 'skill_first_runtime'
    assert payload['copilot']['routeTrace']['selected_skill'] == 'approval.todo'


def test_copilot_query_does_not_fallback_to_legacy_when_skill_first_is_uncertain(model_db, monkeypatch) -> None:
    from services.assistant_core import agentic_runtime
    from services.assistant_core import copilot_orchestrator
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(runtime, 'try_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agentic_runtime,
        'try_run',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('legacy agentic must not handle ordinary traffic')),
    )

    payload = copilot_orchestrator.query(
        user_id='u-skill-first',
        message='这句话暂时不确定该用哪个技能',
        request_id='req-no-legacy-fallback',
    )

    assert payload['copilot']['routePath'] == 'skill_first_runtime'
    assert payload['copilot']['routeTrace']['fallback_reason'] == 'skill_first_unhandled'
    assert payload['copilot']['routeTrace']['final_executor'] == 'agent_kernel.policy.clarification'
    assert payload['meta']['taskType'] == 'clarification'


def test_public_assistant_query_uses_skill_first_runtime_not_legacy(model_db, monkeypatch) -> None:
    from services import assistant
    from services.assistant_core import agentic_runtime
    from services.assistant_core.skill_first import runtime

    monkeypatch.setattr(
        runtime.ToolExecutor,
        'execute',
        lambda self, tool, params, ctx: {
            'ok': True,
            'tool': tool,
            'data': {'summary_hint': '待办审批共有 1 条。', 'entities': [], 'widgets': []},
            'rows_count': 1,
        },
    )
    monkeypatch.setattr(
        agentic_runtime,
        'try_run',
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('public assistant_query must not call legacy agentic runtime')),
    )

    payload = assistant.assistant_query(
        '我这边还有哪些待办审批',
        user_id='u-skill-first',
        request_id='req-public-entry-skill-first',
    )

    assert payload['copilot']['routePath'] == 'skill_first_runtime'
    assert payload['copilot']['routeTrace']['selected_skill'] == 'approval.todo'


def test_product_entrypoints_do_not_import_legacy_routing_modules() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    entrypoints = [
        backend_root / 'services' / 'assistant.py',
        backend_root / 'services' / 'assistant_core' / '__init__.py',
        backend_root / 'services' / 'assistant_core' / 'copilot_orchestrator.py',
    ]
    forbidden_imports = [
        re.compile(r'^\s*from\s+\.?\s*assistant_core\s+import\s+.*\bagentic_runtime\b', re.M),
        re.compile(r'^\s*from\s+\.?\s*assistant_core\s+import\s+.*\borchestrator\b', re.M),
        re.compile(r'^\s*from\s+\.\s*import\s+.*\bagentic_runtime\b', re.M),
        re.compile(r'^\s*from\s+\.\s*import\s+.*\borchestrator\b', re.M),
        re.compile(r'^\s*from\s+\.\s*intent_router\b', re.M),
        re.compile(r'^\s*import\s+.*\bagentic_runtime\b', re.M),
        re.compile(r'^\s*import\s+.*\bintent_router\b', re.M),
    ]

    for entrypoint in entrypoints:
        source = entrypoint.read_text(encoding='utf-8')
        for pattern in forbidden_imports:
            assert not pattern.search(source), f'{entrypoint} must not import legacy routing through {pattern.pattern}'


def test_agent_kernel_mainline_does_not_import_legacy_routing_modules() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    paths = [
        backend_root / 'services' / 'assistant_core' / 'skill_first' / 'runtime.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'kernel.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'services.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'context.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'decision.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'execution.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planning.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'policy.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'confirmations.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'slot_reference.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'result_augmentation.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'answer_synthesis.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'observability.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'direct_invoke.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planning.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_catalog.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_followup.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_guard.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_output.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_prompt.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_recovery.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slots.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'tool_workbench.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'action_runtime.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'skill_playbook.py',
    ]
    forbidden_imports = [
        re.compile(r'^\s*from\s+\.\.orchestrator\b', re.M),
        re.compile(r'^\s*from\s+\.\.agentic_runtime\b', re.M),
        re.compile(r'^\s*from\s+\.\.intent_router\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.orchestrator\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.agentic_runtime\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.intent_router\b', re.M),
    ]

    for path in paths:
        source = path.read_text(encoding='utf-8')
        for pattern in forbidden_imports:
            assert not pattern.search(source), f'{path} must not import legacy routing through {pattern.pattern}'


def test_runtime_policy_context_and_execution_helpers_are_kernel_owned() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    runtime_source = (backend_root / 'services' / 'assistant_core' / 'skill_first' / 'runtime.py').read_text(encoding='utf-8')
    planner_source = (backend_root / 'services' / 'assistant_core' / 'skill_first' / 'planner.py').read_text(encoding='utf-8')
    kernel_modules = [
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'policy.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'context.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'decision.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'execution.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'confirmations.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'slot_reference.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'result_augmentation.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'input_guards.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'answer_synthesis.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'observability.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'direct_invoke.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_catalog.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_followup.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_guard.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_output.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_prompt.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_recovery.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slots.py',
    ]

    moved_helpers = [
        '_llm_recovery_assessment',
        '_direct_skill_message',
        '_synthesize_answer_node',
        '_execute_skill_node',
        '_unsupported_write_intent',
        '_permission_result',
        '_verify_output',
        '_write_guard_result',
        '_skill_first_clarification_result',
        '_permission_denied_result',
        '_learning_events',
        '_first_learning_event_kind',
        '_last_focus_from_result',
        '_record_result_workset_if_needed',
        '_record_tool_workbench_trace',
        '_selected_provider_executor_metadata',
        '_attach_kernel_tool_outputs',
        '_execute_workset_analysis',
        '_prepare_approval_confirmation',
        '_prepare_notification_confirmation',
        '_prepare_attendance_reminder_confirmation',
        '_prepare_employee_change_confirmation',
        '_prepare_salary_adjustment_confirmation',
        '_normalize_skill_month',
        '_clamp_int',
        '_execution_trace',
        '_confirmation_actions',
        '_resolve_slots_and_references',
        '_recompute_missing_slots',
        '_apply_resolved_item_slots',
        '_ground_employee_change_slots_from_history',
        '_ground_approval_confirmation_slots',
        '_normalize_approval_action',
        '_approval_target_index',
        '_approval_business_terms',
        '_approval_matches_terms',
        '_should_run_slot_refiner',
        '_refine_skill_after_reference',
        '_looks_like_candidate_evaluation_followup',
        '_has_reference_signal',
        '_looks_like_workset_reference_text',
        '_augment_skill_specific_result',
        '_augment_page_capability_result',
        '_augment_workflow_help_result',
        '_capability_label',
        '_augment_candidate_job_fit_result',
        '_extract_job_label_from_text',
        '_augment_candidate_evidence_widgets',
        '_append_entity_once',
        '_apply_skill_specific_input_guards',
        '_looks_like_generic_recent_resume_question',
        '_base_trace',
        '_trace_from_plan',
        '_attach_trace',
        '_record_trace_and_failure',
    ]
    for helper in moved_helpers:
        assert not re.search(rf'^def\s+{re.escape(helper)}\b', runtime_source, re.M)

    assert 'from ..agent_kernel import answer_synthesis as kernel_answer_synthesis' in runtime_source
    assert 'from ..agent_kernel import context as kernel_context' in runtime_source
    assert 'from ..agent_kernel import execution as kernel_execution' in runtime_source
    assert 'from ..agent_kernel import input_guards as kernel_input_guards' in runtime_source
    assert 'from ..agent_kernel import observability as kernel_observability' in runtime_source
    assert 'from ..agent_kernel import direct_invoke as kernel_direct_invoke' in runtime_source
    assert 'from ..agent_kernel import policy as kernel_policy' in runtime_source
    assert 'from ..agent_kernel import result_augmentation as kernel_result_augmentation' in runtime_source
    assert 'from ..agent_kernel import slot_reference as kernel_slot_reference' in runtime_source
    assert 'kernel_policy.unhandled_result' in runtime_source
    assert 'kernel_context.persist_turn' in runtime_source
    assert 'skill_first_runtime.unhandled' not in runtime_source
    assert 'from ..agent_kernel import decision as kernel_decision' in planner_source
    assert 'from ..agent_kernel import planning as kernel_planning' in planner_source
    assert 'from ..agent_kernel import planner_catalog as kernel_planner_catalog' in planner_source
    assert 'from ..agent_kernel import planner_followup as kernel_planner_followup' in planner_source
    assert 'from ..agent_kernel import planner_guard as kernel_planner_guard' in planner_source
    assert 'from ..agent_kernel import planner_output as kernel_planner_output' in planner_source
    assert 'from ..agent_kernel import planner_prompt as kernel_planner_prompt' in planner_source
    assert 'from ..agent_kernel import planner_recovery as kernel_planner_recovery' in planner_source
    assert 'from ..agent_kernel import planner_slot_extraction as kernel_planner_slot_extraction' in planner_source
    assert 'from ..agent_kernel import planner_slots as kernel_planner_slots' in planner_source
    assert 'from ..agent_kernel.planning import SkillPlan' in planner_source
    assert 'from ..guardrails import check_skill_permission' not in planner_source
    assert 'from .skill_provider import model_schemas_from_recall' not in planner_source
    for path in kernel_modules:
        source = path.read_text(encoding='utf-8')
        assert 'skill_first.planner import SkillPlan' not in source
        assert 'from ..skill_first.planner import SkillPlan' not in source
    assert 'kernel_decision.build_route_decision' in planner_source
    assert 'kernel_planning.deterministic_candidate_plan' in planner_source
    assert 'kernel_planner_catalog.page_capability_slots' in planner_source
    assert 'kernel_planner_catalog.workflow_help_slots' in planner_source
    assert 'kernel_planner_followup.followup_task_slots' in planner_source
    assert 'kernel_planner_guard.guard_plan' in planner_source
    assert 'kernel_planner_guard.apply_skill_card_contract_corrections' in planner_source
    assert 'kernel_planner_guard.missing_required_slots' in planner_source
    assert 'kernel_planner_guard.unsupported_bulk_or_unsafe_side_effect_intent' in planner_source
    assert 'kernel_planner_output.normalize_llm_plan' in planner_source
    assert 'kernel_planner_output.diagnostic_status_from_llm_meta' in planner_source
    assert 'kernel_planner_prompt.planner_messages' in planner_source
    assert 'kernel_planner_prompt.planner_retry_messages' in planner_source
    assert 'kernel_planner_recovery.llm_unusable_recovery_plan' in planner_source
    assert 'kernel_planner_recovery.retry_planner_decision' in planner_source
    assert 'kernel_planner_slot_extraction.extract_month' in planner_source
    assert 'kernel_planner_slot_extraction.extract_recent_days' in planner_source
    assert 'kernel_planner_slot_extraction.extract_limit' in planner_source
    assert 'kernel_planner_slot_extraction.extract_approval_action' in planner_source
    assert 'kernel_planner_slot_extraction.extract_salary_adjustment_amount' in planner_source
    assert 'kernel_planner_slot_extraction.extract_candidate_name' in planner_source
    assert 'kernel_planner_slot_extraction.extract_employee_name_for_query' in planner_source
    assert 'kernel_planner_slot_extraction.extract_employee_name_for_action' in planner_source
    assert 'kernel_planner_slot_extraction.extract_job_keyword' in planner_source
    assert 'kernel_planner_slot_extraction.extract_job_context_keyword' in planner_source
    assert 'kernel_planner_slot_extraction.extract_target_department' in planner_source
    assert 'kernel_planner_slot_extraction.extract_target_position' in planner_source
    assert 'kernel_planner_slot_extraction.extract_schedule_hint' in planner_source
    assert 'kernel_planner_slot_extraction.notification_slots' in planner_source
    assert 'kernel_planner_slot_extraction.attendance_reminder_confirm_slots' in planner_source
    assert re.search(r'^def\s+retry_planner_decision\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_recovery.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+page_capability_slots\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_catalog.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+workflow_help_slots\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_catalog.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+followup_task_slots\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_followup.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_candidate_name\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_employee_name_for_query\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_employee_name_for_action\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_job_keyword\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_job_context_keyword\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_target_department\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_target_position\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_schedule_hint\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+notification_slots\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+attendance_reminder_confirm_slots\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_month\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_approval_id\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+extract_salary_adjustment_amount\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slot_extraction.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+compact_history\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_prompt.py'
    ).read_text(encoding='utf-8'), re.M)
    assert re.search(r'^def\s+compact_understanding\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_prompt.py'
    ).read_text(encoding='utf-8'), re.M)
    assert 'kernel_planner_slots.guard_slot_values' in planner_source
    assert re.search(r'^def\s+ground_explicit_entity_slots\b', (
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'planner_slots.py'
    ).read_text(encoding='utf-8'), re.M)
    assert 'kernel_planner_slots.sanitize_slot_values' in planner_source
    assert not re.search(r'^def\s+_llm_recovery_assessment\b', planner_source, re.M)
    assert not re.search(r'^def\s+_llm_unusable_recovery_plan\b', planner_source, re.M)
    assert not re.search(r'^def\s+_deterministic_plan\b', planner_source, re.M)
    assert not re.search(r'^def\s+_normalize_llm_plan\b', planner_source, re.M)
    assert not re.search(r'^def\s+_default_rejected_skills\b', planner_source, re.M)
    assert not re.search(r'^def\s+_diagnostic_status_from_llm_meta\b', planner_source, re.M)
    assert not re.search(r'^def\s+_has_explicit_object_read_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_should_retry_planner_decision\b', planner_source, re.M)
    assert not re.search(r'^def\s+_ground_explicit_candidate_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_ground_explicit_employee_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_ground_explicit_entity_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_clip\b', planner_source, re.M)
    assert not re.search(r'^def\s+_compact_history\b', planner_source, re.M)
    assert not re.search(r'^def\s+_compact_history_worksets\b', planner_source, re.M)
    assert not re.search(r'^def\s+_compact_understanding\b', planner_source, re.M)
    assert not re.search(r'^def\s+_page_capability_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_workflow_help_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_flow_id_from_text\b', planner_source, re.M)
    assert not re.search(r'^def\s+_module_id_from_text\b', planner_source, re.M)
    assert not re.search(r'^def\s+_module_id_from_client_context\b', planner_source, re.M)
    assert not re.search(r'^def\s+_followup_task_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_month\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_recent_days\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_limit\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_approval_action\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_approval_id\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_approval_rank\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_approval_comment\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_salary_adjustment_amount\b', planner_source, re.M)
    assert not re.search(r'^def\s+_format_number\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_effective_date_hint\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_action_reason\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_candidate_name\b', planner_source, re.M)
    assert not re.search(r'^def\s+_clean_person_name\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_resume_subject\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_employee_name_for_query\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_employee_name_for_action\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_job_keyword\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_job_context_keyword\b', planner_source, re.M)
    assert not re.search(r'^def\s+_longest_job_phrase\b', planner_source, re.M)
    assert not re.search(r'^def\s+_clean_job_keyword\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_target_department\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_target_position\b', planner_source, re.M)
    assert not re.search(r'^def\s+_extract_schedule_hint\b', planner_source, re.M)
    assert not re.search(r'^def\s+_notification_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_attendance_reminder_confirm_slots\b', planner_source, re.M)
    assert not re.search(r'^def\s+_is_attendance_reminder_confirm_question\b', planner_source, re.M)
    for path in kernel_modules:
        assert path.exists(), f'{path} should own migrated Kernel helper logic'


def test_production_mainline_files_do_not_reference_legacy_routing_modules() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    assistant_core = backend_root / 'services' / 'assistant_core'
    scanned_roots = [
        backend_root / 'services',
        backend_root / 'routes',
    ]
    legacy_owned_paths = {
        assistant_core / 'legacy_agentic_runtime.py',
        assistant_core / 'legacy_orchestrator.py',
        assistant_core / 'legacy_router.py',
    }
    legacy_owned_dirs = {
        assistant_core / 'intent_router',
    }

    def is_under(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    forbidden_imports = [
        re.compile(r'^\s*from\s+services\.assistant_core\s+import\s+.*\bagentic_runtime\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\s+import\s+.*\borchestrator\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\s+import\s+.*\brouter\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.agentic_runtime\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.orchestrator\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.router\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.intent_router\b', re.M),
        re.compile(r'^\s*import\s+services\.assistant_core\.intent_router\b', re.M),
        re.compile(r'^\s*from\s+\.\s*import\s+.*\bagentic_runtime\b', re.M),
        re.compile(r'^\s*from\s+\.\s*import\s+.*\borchestrator\b', re.M),
        re.compile(r'^\s*from\s+\.\s*import\s+.*\brouter\b', re.M),
        re.compile(r'^\s*from\s+\.\s*intent_router\b', re.M),
    ]

    checked: list[Path] = []
    for root in scanned_roots:
        if not root.exists():
            continue
        for path in root.rglob('*.py'):
            if '__pycache__' in path.parts:
                continue
            if path in legacy_owned_paths:
                continue
            if any(is_under(path, legacy_dir) for legacy_dir in legacy_owned_dirs):
                continue
            checked.append(path)
            source = path.read_text(encoding='utf-8')
            for pattern in forbidden_imports:
                assert not pattern.search(source), f'{path} must not reintroduce legacy routing through {pattern.pattern}'

    assert checked, 'production mainline scan should inspect service and route files'


def test_agent_kernel_mainline_does_not_use_legacy_skill_first_playbook_wrapper() -> None:
    import re

    backend_root = Path(__file__).resolve().parents[2]
    paths = [
        backend_root / 'services' / 'assistant_core' / 'skill_first' / 'runtime.py',
        backend_root / 'services' / 'assistant_core' / 'skill_first' / 'planner.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'kernel.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'services.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'skill_provider.py',
        backend_root / 'services' / 'assistant_core' / 'agent_kernel' / 'skill_playbook.py',
    ]
    forbidden_imports = [
        re.compile(r'^\s*from\s+\.\s*skill_playbooks\b', re.M),
        re.compile(r'^\s*from\s+\.\.skill_first\.skill_playbooks\b', re.M),
        re.compile(r'^\s*from\s+services\.assistant_core\.skill_first\.skill_playbooks\b', re.M),
        re.compile(r'^\s*import\s+services\.assistant_core\.skill_first\.skill_playbooks\b', re.M),
    ]

    for path in paths:
        source = path.read_text(encoding='utf-8')
        for pattern in forbidden_imports:
            assert not pattern.search(source), f'{path} must not import legacy playbook wrapper through {pattern.pattern}'


def test_confirmation_cancel_is_captured_as_learning_sample(monkeypatch) -> None:
    from services.assistant_core.schemas import ExecutionResult, RouteDecision
    from services.assistant_core.agent_kernel import observability as kernel_observability
    from services.assistant_core.skill_first import failure_samples, runtime

    captured: list[dict] = []

    def fake_execute_pending(message, ctx, decision):
        result = ExecutionResult(
            summary='已取消：安排复试。',
            session_id=ctx.session_id,
            route_decision=decision,
        )
        result._resolved_action_id = 'act-cancelled'
        return result

    monkeypatch.setattr(runtime, '_execute_pending_action', fake_execute_pending)
    monkeypatch.setattr(runtime.memory, 'save_turn', lambda **kwargs: kwargs.get('session_id'))
    monkeypatch.setattr(kernel_observability, 'append_route_trace', lambda trace: trace)
    monkeypatch.setattr(
        failure_samples,
        '_FAILURE_FILE',
        Path('unused-learning-sample.jsonl'),
        raising=False,
    )
    monkeypatch.setattr(
        kernel_observability,
        'append_failure_sample',
        lambda kind, trace, extra=None: captured.append({'kind': kind, 'trace': trace, 'extra': extra}),
    )

    result = runtime.try_run('取消动作：act-cancelled', _ctx())

    assert result is not None
    assert _kernel_node_names(result) == ['confirmed_action', 'observability']
    assert result.copilot['routeTrace']['learning_events'][0]['kind'] == 'confirmation_cancelled'
    assert captured
    assert captured[0]['kind'] == 'confirmation_cancelled'
    assert captured[0]['trace']['learning_events'][0]['resolved_action_id'] == 'act-cancelled'


def test_learning_events_include_user_correction_and_clarification_selection_change() -> None:
    from services.assistant_core.skill_first import runtime

    correction_ctx = _ctx()
    correction_ctx.history = [{
        'role': 'assistant',
        'copilot': {'routeTrace': {'request_id': 'old-1', 'selected_skill': 'payroll.summary'}},
    }]
    correction_events = runtime._learning_events(
        '不对，我说的是工资异常，不是总额',
        correction_ctx,
        {'request_id': 'new-1', 'selected_skill': 'payroll.anomaly'},
    )

    assert correction_events == [{
        'kind': 'user_correction',
        'previous_selected_skill': 'payroll.summary',
        'current_selected_skill': 'payroll.anomaly',
        'previous_request_id': 'old-1',
    }]

    clarification_ctx = _ctx()
    clarification_ctx.history = [{
        'role': 'assistant',
        'widgets': [{'type': 'clarification'}],
        'copilot': {'routeTrace': {'request_id': 'old-2', 'selected_skill': 'candidate.search'}},
    }]
    clarification_events = runtime._learning_events(
        '我要看第二个候选人的面试安排',
        clarification_ctx,
        {'request_id': 'new-2', 'selected_skill': 'interview.records'},
    )

    assert clarification_events == [{
        'kind': 'clarification_changed_selection',
        'previous_selected_skill': 'candidate.search',
        'current_selected_skill': 'interview.records',
        'previous_request_id': 'old-2',
    }]


def test_failure_sample_keeps_learning_events(tmp_path: Path, monkeypatch) -> None:
    from services.assistant_core.skill_first import failure_samples

    trace = {
        'request_id': 'learn-1',
        'user_text': '不对，我说的是工资异常',
        'top_k_skills': ['payroll.anomaly', 'payroll.summary'],
        'candidate_scores': [{'skill_id': 'payroll.anomaly', 'score': 9.1}],
        'matched_examples': {'payroll.anomaly': ['工资这块有没有啥异常']},
        'selected_skill': 'payroll.anomaly',
        'rejected_skills': [{'skill_id': 'payroll.summary', 'reason': 'corrected_by_user'}],
        'risk_result': {'risk_level': 'high', 'side_effect': False},
        'confirmation_policy': 'not_required_for_read_only',
        'final_executor': 'ToolExecutor(payroll_analysis)',
        'output_verification_result': 'ok',
        'planner_source': 'deterministic',
        'learning_events': [{'kind': 'user_correction'}],
    }

    assert failure_samples.should_capture_failure(trace) is True
    sample_file = tmp_path / 'learning-events-test.jsonl'
    monkeypatch.setattr(failure_samples, '_FAILURE_FILE', sample_file)

    failure_samples.append_failure_sample('user_correction', trace)

    sample = json.loads(sample_file.read_text(encoding='utf-8'))
    assert sample['learning_events'] == [{'kind': 'user_correction'}]
    assert sample['candidate_scores'][0]['skill_id'] == 'payroll.anomaly'
    assert sample['matched_examples']['payroll.anomaly'] == ['工资这块有没有啥异常']
    assert sample['rejected_skills'][0]['skill_id'] == 'payroll.summary'
    assert sample['output_verification_result'] == 'ok'
    assert sample['final_executor'] == 'ToolExecutor(payroll_analysis)'


def test_failure_patch_script_generates_reviewable_candidates(tmp_path: Path) -> None:
    sample_path = tmp_path / 'failure.jsonl'
    output_path = tmp_path / 'patch.json'
    samples = [
        {
            'kind': 'low_confidence',
            'user_text': '钱这块哪儿怪怪的',
            'selected_skill': 'payroll.anomaly',
            'top_k_skills': ['payroll.anomaly'],
            'candidate_scores': [{'skill_id': 'payroll.anomaly', 'score': 7.2, 'anti_score': 0}],
            'matched_examples': {'payroll.anomaly': ['钱这块有没有不对劲']},
            'rejected_skills': [{'skill_id': 'payroll.summary', 'reason': 'anomaly_word'}],
            'fallback_reason': 'low_confidence',
            'permission_result': 'allowed',
            'risk_result': {'risk_level': 'high', 'side_effect': False},
            'confirmation_policy': 'not_required_for_read_only',
            'final_executor': 'ToolExecutor(payroll_analysis)',
            'output_verification_result': 'ok',
            'planner_source': 'deterministic',
            'slot_fill_result': {'slot_values': {'question': '钱这块哪儿怪怪的'}},
        },
        {
            'kind': 'user_correction',
            'request_id': 'new-1',
            'user_text': '不对，我说的是工资异常，不是总额',
            'selected_skill': 'payroll.anomaly',
            'top_k_skills': ['payroll.anomaly', 'payroll.summary'],
            'learning_events': [{
                'kind': 'user_correction',
                'previous_selected_skill': 'payroll.summary',
                'current_selected_skill': 'payroll.anomaly',
                'previous_request_id': 'old-1',
            }],
        },
        {
            'kind': 'confirmation_cancelled',
            'request_id': 'cancel-1',
            'user_text': '取消动作：act-cancelled',
            'selected_skill': 'execute_pending_action',
            'learning_events': [{
                'kind': 'confirmation_cancelled',
                'resolved_action_id': 'act-cancelled',
                'pending_action_label': '安排复试',
                'pending_action_tools': ['interview_create'],
                'summary': '已取消：安排复试。',
            }],
        },
        {
            'kind': 'clarification_changed_selection',
            'request_id': 'clarified-1',
            'user_text': '我要看第二个候选人的面试安排',
            'selected_skill': 'interview.records',
            'top_k_skills': ['interview.records', 'candidate.search'],
            'learning_events': [{
                'kind': 'clarification_changed_selection',
                'previous_selected_skill': 'candidate.search',
                'current_selected_skill': 'interview.records',
                'previous_request_id': 'clarify-old-1',
            }],
        },
    ]
    sample_path.write_text(
        ''.join(json.dumps(sample, ensure_ascii=False) + '\n' for sample in samples),
        encoding='utf-8',
    )

    script = next(
        candidate
        for parent in Path(__file__).resolve().parents
        for candidate in [parent / 'scripts' / 'generate-skill-card-eval-patch.mjs']
        if candidate.exists()
    )
    completed = subprocess.run(
        ['node', str(script), str(sample_path), str(output_path)],
        check=True,
        text=True,
        capture_output=True,
    )

    assert '"ok": true' in completed.stdout
    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert payload['sample_count'] == 4
    assert payload['production_mutation_policy'] == 'never_auto_mutate_skill_cards_or_routing'
    assert {
        item['project']: item['mechanism']
        for item in payload['reference_project_mechanisms']
    }['hermes-agent'] == 'closed_learning_loop'
    assert any(
        item['project'] == 'openclaw'
        and item['mechanism'] == 'canonical_runtime_state_and_explicit_migration'
        for item in payload['reference_project_mechanisms']
    )
    assert any('human review' in item for item in payload['workflow'])
    assert any('Skill Card schema' in item for item in payload['human_review_checklist'])
    assert any(
        command.startswith('npm run verify:assistant-kernel-nl-matrix')
        for command in payload['regression_verification_commands']
    )
    low_confidence_case = next(
        item for item in payload['evaluation_cases']
        if item.get('source') == 'skill_first_failure_sample'
        and item.get('user_text') == '钱这块哪儿怪怪的'
    )
    assert low_confidence_case['review_evidence']['candidate_scores'][0]['skill_id'] == 'payroll.anomaly'
    assert low_confidence_case['review_evidence']['matched_examples']['payroll.anomaly'] == ['钱这块有没有不对劲']
    assert low_confidence_case['review_evidence']['output_verification_result'] == 'ok'
    suggestions = {item['skill_id']: item for item in payload['skill_card_suggestions']}
    assert '钱这块哪儿怪怪的' in suggestions['payroll.anomaly']['suggested_colloquial_examples']
    assert '不对，我说的是工资异常，不是总额' in suggestions['payroll.anomaly']['suggested_colloquial_examples']
    assert '不对，我说的是工资异常，不是总额' in suggestions['payroll.summary']['suggested_anti_examples']
    assert suggestions['interview.schedule_confirm_create']['suggested_review_notes']
    assert 'execute_pending_action' not in suggestions

    correction_cases = [
        item for item in payload['evaluation_cases']
        if item.get('source') == 'skill_first_learning_event'
        and item.get('learning_event_kind') == 'user_correction'
    ]
    assert correction_cases
    assert correction_cases[0]['expected_skill'] == 'payroll.anomaly'
    assert correction_cases[0]['previous_selected_skill'] == 'payroll.summary'
    assert correction_cases[0]['review_required'] is True
    assert correction_cases[0]['review_evidence']['top_k_skills'] == ['payroll.anomaly', 'payroll.summary']
    assert payload['learning_event_suggestions'][0]['review_required'] is True
    assert any(
        item.get('kind') == 'confirmation_cancelled'
        and item.get('selected_skill') == 'interview.schedule_confirm_create'
        and item.get('pending_action_tools') == ['interview_create']
        for item in payload['learning_event_suggestions']
    )
    assert '我要看第二个候选人的面试安排' in suggestions['interview.records']['suggested_colloquial_examples']
    assert '我要看第二个候选人的面试安排' in suggestions['candidate.search']['suggested_anti_examples']
