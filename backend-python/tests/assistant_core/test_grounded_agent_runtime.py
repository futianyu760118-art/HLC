"""Regression tests for the evidence-grounded HRM agent runtime."""

from __future__ import annotations

from datetime import datetime

import pytest
from flask import Flask

from services.assistant_core.schemas import AssistantContext
from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core.workset_store import WorkSetStore
from services.assistant_core.schemas import GenerationPlan, RouteDecision
from services.assistant_core.executors.generation_executor import GenerationExecutor


def _ctx() -> AssistantContext:
    return AssistantContext(user_id='u-agent', role='hr_admin', session_id='s-agent')


class TestGroundedRouting:
    def test_plural_assessment_requires_latest_workset_evidence(self) -> None:
        decision = build_route_decision('这几个人怎么样，你分别评判一下', _ctx())

        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'candidate_assessment'
        assert 'latest_workset' in decision.required_context

    def test_named_person_assessment_requires_subject_evidence(self) -> None:
        decision = build_route_decision('吴明华这个人怎么样', _ctx())

        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'person_assessment'
        assert decision.required_context == ['named_subject_evidence']

    def test_assessment_verb_before_person_name_requires_subject_evidence(self) -> None:
        decision = build_route_decision('分析一下吴明华的经历和录用风险', _ctx())

        assert decision.route_track == 'B_GENERATION'
        assert decision.required_context == ['named_subject_evidence']

    def test_interview_schedule_is_an_action_plan_instead_of_a_block(self) -> None:
        decision = build_route_decision('给第一个候选人安排明天下午三点复试', _ctx())

        assert decision.task_type == 'action'
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.requires_confirmation is True
        assert decision.tool_plan[0].tool == 'interview_create'
        assert decision.tool_plan[0].purpose == 'side_effect'

    def test_named_person_interview_schedule_uses_fast_confirmation_path(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.setattr(
            llm_skill_planner,
            'plan_with_llm',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('LLM planner should not hijack write action')),
        )

        decision = build_route_decision('帮我给吴继红安排个明天上午8点的面试', _ctx())

        assert decision.task_type == 'action'
        assert decision.intent == 'interview_schedule'
        assert decision.tool_plan[0].tool == 'interview_create'

    def test_named_person_interview_records_are_resolved_as_evidence(self) -> None:
        decision = build_route_decision('吴明华有没有面试记录', _ctx())

        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'person_evidence_answer'
        assert decision.required_context == ['named_subject_evidence']

    def test_pronoun_evidence_followup_reuses_latest_workset(self) -> None:
        decision = build_route_decision('他的简历和面试记录怎么样', _ctx())

        assert decision.route_track == 'B_GENERATION'
        assert decision.required_context == ['latest_workset']

    def test_best_candidate_action_reuses_ranked_workset(self) -> None:
        decision = build_route_decision('给最合适的人安排明天下午三点复试', _ctx())

        assert decision.task_type == 'action'
        assert decision.required_context == ['latest_workset']


class TestDurableWorkSets:
    def test_resolve_mention_can_restore_workset_from_persistent_reader(self) -> None:
        persisted = {
            'id': 'ws-persisted',
            'session_id': 's-agent',
            'entity_type': 'candidate',
            'items': [
                {
                    'entity_type': 'candidate',
                    'entity_id': 'c-1',
                    'title': '吴明华',
                    'rank': 1,
                },
            ],
        }
        store = WorkSetStore(persistent_reader=lambda session_id: [persisted])

        resolved = store.resolve_mention('这个候选人怎么样', 's-agent')

        assert resolved is not None
        assert resolved['workset']['id'] == 'ws-persisted'
        assert resolved['item']['title'] == '吴明华'


class TestEvidenceAssembly:
    def test_named_subject_context_calls_evidence_bundle_tool(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        calls = []

        def fake_execute(self, tool, params, ctx):
            calls.append((tool, params))
            return {
                'ok': True,
                'tool': tool,
                'data': {
                    'facts': {'name': '吴明华', 'candidate': {'status': 'screening'}},
                    'entities': [{'type': 'candidate', 'id': 'c-1', 'title': '吴明华'}],
                    'rows_count': 1,
                },
                'rows_count': 1,
            }

        monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
        decision = build_route_decision('吴明华这个人怎么样', _ctx())

        context, clarification = orchestrator._context_for_grounded_generation(
            '吴明华这个人怎么样',
            _ctx(),
            decision,
        )

        assert clarification is None
        assert calls == [('candidate_evidence_bundle', {'keyword': '吴明华'})]
        assert context['details'][0]['name'] == '吴明华'

    def test_workset_candidate_loads_full_evidence_bundle(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        store = WorkSetStore()
        ws = store.create_workset_from_entities(
            's-agent',
            'u-agent',
            '电子工程师候选人',
            [{'type': 'candidate', 'id': 'c-1', 'title': '吴明华'}],
        )
        calls = []

        def fake_resolve(message, session_id):
            return {'kind': 'workset', 'workset': ws}

        def fake_execute(self, tool, params, ctx):
            calls.append((tool, params))
            return {'ok': True, 'data': {'facts': {'name': '吴明华'}}, 'rows_count': 1}

        monkeypatch.setattr(orchestrator.workset_store, 'resolve_mention', fake_resolve)
        monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
        decision = RouteDecision(
            task_type='generation',
            route_track='B_GENERATION',
            intent='candidate_assessment',
            confidence=0.9,
            required_context=['latest_workset'],
        )

        context, clarification = orchestrator._context_for_grounded_generation(
            '这几个人怎么样',
            _ctx(),
            decision,
        )

        assert clarification is None
        assert calls == [('candidate_evidence_bundle', {'candidate_id': 'c-1'})]
        assert context['details'][0]['name'] == '吴明华'

    def test_llm_search_plan_keyword_is_normalized_before_execution(self) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator
        from services.assistant_core.schemas import ToolCallPlan

        decision = RouteDecision(
            task_type='data_query',
            route_track='A_DATA_ACTION',
            intent='recent_candidates',
            confidence=0.9,
            tool_plan=[
                ToolCallPlan(
                    step_id='s1',
                    tool='recruitment_search',
                    input={'keyword': '最近来应聘电子工程师的都有哪些人'},
                ),
            ],
        )

        normalized = orchestrator._normalize_tool_plan_inputs('最近来应聘电子工程师的都有哪些人', decision)

        assert normalized.tool_plan[0].input['keyword'] == '电子工程师'
        assert normalized.tool_plan[0].input['module'] == 'candidates'
        assert normalized.tool_plan[0].input['date_range']['recent_days'] == 30

    def test_recent_search_window_is_relaxed_to_business_default(self) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator
        from services.assistant_core.schemas import ToolCallPlan

        decision = RouteDecision(
            task_type='data_query',
            route_track='A_DATA_ACTION',
            intent='recent_candidates',
            confidence=0.9,
            tool_plan=[
                ToolCallPlan(
                    step_id='s1',
                    tool='recruitment_search',
                    input={'keyword': '电子工程师', 'module': 'candidates', 'date_range': {'recent_days': 7}},
                ),
            ],
        )

        normalized = orchestrator._normalize_tool_plan_inputs('最近来应聘电子工程师的都有哪些人', decision)

        assert normalized.tool_plan[0].input['date_range']['recent_days'] == 30

    def test_workset_analyze_direct_answer_short_circuits_generation(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(
            llm_client,
            'chat_profile',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('workset_analysis direct answer should not call LLM')),
        )
        result = GenerationExecutor().execute(
            '其中年龄最小的是谁',
            _ctx(),
            GenerationPlan(template_id='workset_analysis'),
            context={'facts': {'direct_answer': '上轮结果集中没有可比较的“年龄”字段。'}},
        )

        assert '年龄' in result.summary

    def test_flatten_facts_keeps_nested_score_fields(self) -> None:
        from services.assistant_core.skills import _flatten_facts, _metric_value, _infer_metric

        flat = _flatten_facts({'resume': {'score': 85, 'match_degree': 80}})
        score_hit = _metric_value(flat, _infer_metric('其中评分最高的是谁'))
        match_hit = _metric_value(flat, _infer_metric('其中匹配度最高的是谁'))

        assert flat['resume.score'] == 85
        assert score_hit['value'] == 85
        assert match_hit['value'] == 80

    def test_match_metric_does_not_read_numbers_from_job_id(self) -> None:
        from services.assistant_core.skills import _metric_value, _infer_metric

        flat = {'candidate.match_records.0.jobId': 'job-93', 'resume.match_degree': 80}
        hit = _metric_value(flat, _infer_metric('其中匹配度最高的是谁'))

        assert hit['value'] == 80
        assert hit['field'] == 'resume.match_degree'

    def test_workset_reference_should_skip_entity_memory_rewrite(self) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        assert orchestrator._is_workset_reference_message('其中匹配度最高的是谁') is True
        assert orchestrator._is_workset_reference_message('给上面20个人里排名前三的安排明天早晨8点的面试') is True

    def test_named_subject_with_metric_is_not_erased_as_workset_reference(self) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        assert orchestrator._extract_named_subject('吴明华评分怎么样') == '吴明华'

    def test_top_ranked_workset_action_selects_highest_three(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        items = [
            {'entity_type': 'candidate', 'entity_id': 'c-low', 'title': '低分', 'rank': 1},
            {'entity_type': 'candidate', 'entity_id': 'c-top', 'title': '第一', 'rank': 2},
            {'entity_type': 'candidate', 'entity_id': 'c-mid', 'title': '第三', 'rank': 3},
            {'entity_type': 'candidate', 'entity_id': 'c-high', 'title': '第二', 'rank': 4},
        ]
        ws = {'id': 'ws-rank', 'items': items, 'entity_type': 'candidate'}
        facts = {
            'c-low': {'name': '低分', 'resume': {'resume_id': 'r-low', 'score': 60}, 'job': {'job_id': 'j1'}},
            'c-top': {'name': '第一', 'resume': {'resume_id': 'r-top', 'score': 95}, 'job': {'job_id': 'j1'}},
            'c-mid': {'name': '第三', 'resume': {'resume_id': 'r-mid', 'score': 80}, 'job': {'job_id': 'j1'}},
            'c-high': {'name': '第二', 'resume': {'resume_id': 'r-high', 'score': 90}, 'job': {'job_id': 'j1'}},
        }

        monkeypatch.setattr(
            orchestrator.workset_store,
            'resolve_mention',
            lambda message, session_id: {'kind': 'workset', 'workset': ws},
        )

        def fake_execute(self, tool, params, ctx):
            return {'ok': True, 'data': {'facts': facts[params['candidate_id']]}, 'rows_count': 1}

        monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
        decision = build_route_decision('给上面20个人里排名前三的安排明天早晨8点的面试', _ctx())

        result = orchestrator._prepare_action_confirmation(
            '给上面20个人里排名前三的安排明天早晨8点的面试',
            _ctx(),
            decision,
        )

        planned_resume_ids = [tool['input']['resume_id'] for tool in result._pending_action['tools']]
        assert planned_resume_ids == ['r-top', 'r-high', 'r-mid']
        assert '第一、第二、第三' in result.summary

    def test_recent_recruitment_hot_path_uses_tool_plan_without_llm(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.setenv('ASSISTANT_ENABLE_RECENT_RECRUITMENT_HOTPATH_OUTSIDE_APP', '1')
        monkeypatch.setattr(
            llm_skill_planner,
            'plan_with_llm',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('recent recruitment hot path should skip LLM planner')),
        )
        decision = build_route_decision('最近来应聘电子工程师的都有哪些人', _ctx())

        assert decision.tool_plan[0].tool == 'recruitment_search'
        assert decision.tool_plan[0].input['keyword'] == '电子工程师'
        assert decision.tool_plan[0].input['module'] == 'candidates'

    def test_evidence_bundle_tools_are_registered(self) -> None:
        from services.assistant_core import skill_registry

        assert skill_registry.get('candidate_evidence_bundle') is not None
        assert skill_registry.get('employee_evidence_bundle') is not None
        assert skill_registry.get('system_search') is not None
        assert skill_registry.get('workset_analyze') is not None


class TestGroundedAnswers:
    def test_person_assessment_fallback_uses_loaded_evidence(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'chat_profile', lambda *a, **kw: None)
        context = {
            'details': [{
                'name': '吴明华',
                'candidate': {'status': 'screening'},
                'resume': {'score': 94, 'strengths': ['供应链协同', '成本控制']},
                'job': {'title': '供应链总监'},
                'interviews': [{'status': 'completed'}],
            }],
        }
        result = GenerationExecutor().execute(
            '吴明华这个人怎么样',
            _ctx(),
            GenerationPlan(template_id='person_assessment'),
            context=context,
        )

        assert '吴明华' in result.summary
        assert '供应链总监' in result.summary
        assert '94' in result.summary
        assert '供应链协同' in result.summary

    def test_evidence_question_fallback_reports_existing_interview_records(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'chat_profile', lambda *a, **kw: None)
        result = GenerationExecutor().execute(
            '吴明华有没有面试记录',
            _ctx(),
            GenerationPlan(template_id='person_evidence_answer'),
            context={'details': [{'name': '吴明华', 'interviews': [{'status': 'scheduled'}]}]},
        )

        assert '吴明华' in result.summary
        assert '1' in result.summary

    def test_llm_prompt_marks_loaded_system_evidence_as_authoritative(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        captured = {}

        def fake_chat(profile, messages, **kwargs):
            captured['messages'] = messages
            return {'content': '评价结果'}

        monkeypatch.setattr(llm_client, 'chat_profile', fake_chat)
        GenerationExecutor().execute(
            '吴明华怎么样',
            _ctx(),
            GenerationPlan(template_id='person_assessment'),
            context={'details': [{'name': '吴明华'}], 'context_source': 'candidate_evidence_bundle'},
        )

        joined = '\n'.join(m['content'] for m in captured['messages'])
        assert '系统工具已加载的真实证据' in joined
        assert '不得声称无法访问' in joined


class TestConfirmedActions:
    def test_recruiter_can_execute_confirmed_interview_action(self) -> None:
        from services.assistant_core import guardrails, skill_registry

        denial = guardrails.check_skill_permission('recruiter', skill_registry.get('interview_create'))

        assert denial is None

    def test_chinese_morning_hour_is_parsed_without_default_time_shift(self) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        scheduled_at = orchestrator._parse_schedule_time('帮我给吴明华安排一个面试，明天上午八点')

        assert scheduled_at is not None
        assert scheduled_at.endswith('T08:00:00')

    def test_chinese_afternoon_hour_remains_24_hour_time(self) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        scheduled_at = orchestrator._parse_schedule_time('给吴明华安排明天下午三点复试')

        assert scheduled_at is not None
        assert scheduled_at.endswith('T15:00:00')

    def test_zoned_interview_input_normalizes_to_shanghai_business_time(self) -> None:
        from services.business_time import parse_business_datetime

        scheduled_at = parse_business_datetime('2026-05-28T00:00:00Z')

        assert scheduled_at == datetime(2026, 5, 28, 8, 0)

    def test_schedule_interview_returns_chat_confirmation_card(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        ws = {
            'id': 'ws-1',
            'items': [{'entity_type': 'candidate', 'entity_id': 'c-1', 'title': '吴明华', 'rank': 1}],
        }
        monkeypatch.setattr(
            orchestrator.workset_store,
            'resolve_mention',
            lambda message, session_id: {'kind': 'item', 'item': ws['items'][0], 'workset': ws},
        )
        monkeypatch.setattr(
            orchestrator.ToolExecutor,
            'execute',
            lambda self, tool, params, ctx: {
                'ok': True,
                'data': {
                    'facts': {
                        'name': '吴明华',
                        'candidate': {'candidate_id': 'c-1'},
                        'resume': {'resume_id': 'r-1'},
                        'job': {'job_id': 'j-1', 'title': '供应链总监'},
                    },
                },
                'rows_count': 1,
            },
        )
        monkeypatch.setattr(orchestrator.memory, 'save_turn', lambda **kwargs: 's-agent')

        result = orchestrator.run('给第一个候选人安排2026-05-29 15:00复试', _ctx())

        assert result.requires_confirmation is True
        assert result.widgets[0]['type'] == 'confirmation_card'
        assert result.actions[0]['label'] == '确认执行'

    def test_named_candidate_action_loads_evidence_and_returns_confirmation(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        calls = []

        def fake_execute(self, tool, params, ctx):
            calls.append((tool, params))
            return {
                'ok': True,
                'data': {
                    'facts': {
                        'name': '吴明华',
                        'candidate': {'candidate_id': 'c-1'},
                        'resume': {'resume_id': 'r-1'},
                        'job': {'job_id': 'j-1', 'title': '供应链总监'},
                    },
                },
                'rows_count': 1,
            }

        monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
        decision = build_route_decision('给吴明华安排2099-12-29 15:00复试', _ctx())

        result = orchestrator._prepare_action_confirmation(
            '给吴明华安排2099-12-29 15:00复试',
            _ctx(),
            decision,
        )

        assert calls == [('candidate_evidence_bundle', {'keyword': '吴明华'})]
        assert result.widgets[0]['type'] == 'confirmation_card'
        assert '吴明华' in result.summary

    def test_confirm_pending_action_executes_planned_tool(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        pending = {
            'id': 'act-1',
            'label': '安排复试',
            'tools': [{'tool': 'interview_create', 'input': {'resume_id': 'r-1', 'job_id': 'j-1'}}],
        }
        calls = []
        monkeypatch.setattr(
            orchestrator.memory,
            'get_pending_action',
            lambda user_id, session_id, action_id=None: pending,
            raising=False,
        )
        monkeypatch.setattr(orchestrator.memory, 'save_turn', lambda **kwargs: 's-agent')

        def execute(self, tool, params, ctx):
            calls.append((tool, params))
            return {'ok': True, 'data': {'summary_hint': '已创建复试安排。'}, 'rows_count': 1}

        monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', execute)

        result = orchestrator.run('确认执行动作：act-1', _ctx())

        assert calls == [('interview_create', {'resume_id': 'r-1', 'job_id': 'j-1'})]
        assert '已创建复试安排' in result.summary

    def test_schedule_top_three_limits_pending_tools(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        ws = {
            'id': 'ws-many',
            'items': [
                {'entity_type': 'candidate', 'entity_id': f'c-{i}', 'title': f'候选人{i}', 'rank': i}
                for i in range(1, 5)
            ],
        }
        monkeypatch.setattr(
            orchestrator.workset_store,
            'resolve_mention',
            lambda message, session_id: {'kind': 'workset', 'workset': ws},
        )

        def fake_execute(self, tool, params, ctx):
            idx = params['candidate_id'].split('-')[-1]
            return {
                'ok': True,
                'data': {'facts': {
                    'name': f'候选人{idx}',
                    'resume': {'resume_id': f'r-{idx}'},
                    'job': {'job_id': 'j-1'},
                }},
            }

        monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
        decision = build_route_decision('给前三个人安排明天下午三点复试', _ctx())

        result = orchestrator._prepare_action_confirmation(
            '给前三个人安排明天下午三点复试',
            _ctx(),
            decision,
        )

        assert len(result._pending_action['tools']) == 3


@pytest.fixture()
def model_db():
    from models import db

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


class TestDatabaseEvidenceAndActions:
    def test_candidate_bundle_reads_related_recruitment_records(self, model_db) -> None:
        from models import Candidate, Interview, Job, Offer, Resume
        from services.assistant_core.skills import skill_candidate_evidence_bundle

        job = Job(id='j-1', title='供应链总监', requirements='供应链管理', status='open')
        resume = Resume(
            id='r-1',
            job_id='j-1',
            candidate_name='吴明华',
            file_url='/uploads/wu.pdf',
            ai_analysis={'score': 94, 'strengths': ['供应链协同']},
        )
        candidate = Candidate(id='c-1', resume_id='r-1', job_id='j-1', name='吴明华', status='screening')
        interview = Interview(
            id='i-1',
            resume_id='r-1',
            job_id='j-1',
            scheduled_at=datetime(2026, 5, 28, 15, 0),
            status='scheduled',
        )
        offer = Offer(id='o-1', candidate_id='c-1', job_id='j-1', title='吴明华 - 供应链总监', status='draft')
        model_db.session.add_all([job, resume, candidate, interview, offer])
        model_db.session.commit()

        result = skill_candidate_evidence_bundle({'keyword': '吴明华'}, _ctx())

        assert result['facts']['name'] == '吴明华'
        assert result['facts']['resume']['score'] == 94
        assert result['facts']['job']['title'] == '供应链总监'
        assert len(result['facts']['interviews']) == 1
        assert len(result['facts']['offers']) == 1

    def test_recruitment_search_candidates_can_match_job_title(self, model_db) -> None:
        from models import Candidate, Job, Resume
        from services.assistant_core.skills import skill_recruitment_search

        job = Job(id='j-electronic', title='电子工程师', department='研发部', status='open')
        resume = Resume(
            id='r-electronic',
            job_id='j-electronic',
            candidate_name='李博豪',
            file_url='/uploads/li.pdf',
        )
        candidate = Candidate(
            id='c-electronic',
            resume_id='r-electronic',
            job_id='j-electronic',
            name='李博豪',
            status='screening',
        )
        model_db.session.add_all([job, resume, candidate])
        model_db.session.commit()

        result = skill_recruitment_search(
            {'keyword': '电子工程师', 'module': 'candidates', 'limit': 5},
            _ctx(),
        )

        assert result['rows_count'] == 1
        assert result['entities'][0]['title'] == '李博豪'

    def test_confirmed_interview_tool_creates_record_only_once(self, model_db) -> None:
        from models import Interview, Job, Resume
        from services.assistant_core.skills import skill_interview_create

        model_db.session.add(Job(id='j-1', title='电子工程师', status='open'))
        model_db.session.add(Resume(id='r-1', job_id='j-1', candidate_name='李博豪', file_url='/uploads/li.pdf'))
        model_db.session.commit()
        params = {'resume_id': 'r-1', 'job_id': 'j-1', 'scheduled_at': '2026-05-29T15:00:00'}

        created = skill_interview_create(params, _ctx())
        repeated = skill_interview_create(params, _ctx())

        assert created['facts']['created'] is True
        assert repeated['facts']['created'] is False
        assert Interview.query.count() == 1


