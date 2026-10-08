"""Hybrid assistant routing tests.

These tests cover the minimal three-track architecture:
- dialogue/text transforms should not become global_search
- generation should produce a GenerationPlan
- data/action keeps the legacy RouterResult bridge
- composite candidate search + generation is recognized
"""

from __future__ import annotations

from flask import Flask

from services.assistant_core.schemas import (
    AssistantContext,
    ExecutionResult,
    GenerationPlan,
    RouteDecision,
    RouterResult,
    route_decision_to_router_result,
    router_result_to_route_decision,
)
from services.assistant_core.intent_router.classifier import TrackClassifier
from services.assistant_core.intent_router.legacy_planner import build_route_decision
from services.assistant_core import legacy_router


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-hybrid', role=role, session_id='sess-hybrid')


class TestRouteDecisionSchema:
    def test_router_result_round_trips_through_route_decision(self) -> None:
        rr = RouterResult(
            intent='employee_lookup',
            task_template_id='employee_lookup',
            confidence=0.77,
            entities={'keyword': '张三'},
            risk_level='low',
            candidate_skills=['employee_search'],
            route_path='retrieval',
        )

        decision = router_result_to_route_decision(rr)
        restored = route_decision_to_router_result(decision)

        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_type == 'data_query'
        assert restored.intent == rr.intent
        assert restored.task_template_id == rr.task_template_id
        assert restored.entities == rr.entities
        assert restored.candidate_skills == rr.candidate_skills

    def test_permission_denied_router_result_becomes_forbidden_decision(self) -> None:
        rr = RouterResult(
            intent='permission_denied',
            task_template_id='permission_denied_response',
            confidence=0.9,
            risk_level='high',
            reason='permission_gate:role_not_allowed:employee:payroll_month_summary',
        )

        decision = router_result_to_route_decision(rr)

        assert decision.task_type == 'forbidden'
        assert decision.task_template_id == 'permission_denied_response'
        assert 'permission_denied' in decision.safety_flags

    def test_execution_result_response_keeps_legacy_fields_and_adds_v2(self) -> None:
        decision = RouteDecision(
            task_type='generation',
            route_track='B_GENERATION',
            intent='hr_email_draft',
            confidence=0.91,
            generation_plan=GenerationPlan(
                template_id='hr_email_draft',
                prompt_template='',
                model_profile='standard',
            ),
        )
        result = ExecutionResult(
            summary='邮件草稿',
            entities=[{'type': 'candidate', 'id': 'c1'}],
            widgets=[{'type': 'markdown', 'content': '邮件草稿'}],
            session_id='s1',
            route_decision=decision,
            answer={'content': '邮件草稿', 'format': 'markdown'},
            actions=[{'type': 'copy'}],
            worksets=[{'id': 'ws_1'}],
        )

        response = result.to_response(include_meta=True)

        assert response['summary'] == '邮件草稿'
        assert response['entities'] == [{'type': 'candidate', 'id': 'c1'}]
        assert response['widgets'] == [{'type': 'markdown', 'content': '邮件草稿'}]
        assert response['schemaVersion'] == 'assistant.response.v2'
        assert response['answer'] == {'content': '邮件草稿', 'format': 'markdown'}
        assert response['actions'] == [{'type': 'copy'}]
        assert response['worksets'] == [{'id': 'ws_1'}]
        assert response['meta']['routeTrack'] == 'B_GENERATION'
        assert response['meta']['taskType'] == 'generation'
        assert response['meta']['modelProfile'] == 'standard'


class TestTrackClassifier:
    def test_help_goes_dialogue(self) -> None:
        decision = TrackClassifier().classify('你能做什么？', _ctx())
        assert decision.route_track == 'C_DIALOGUE_KNOWLEDGE'
        assert decision.task_type == 'dialogue'

    def test_polish_user_text_goes_dialogue(self) -> None:
        decision = TrackClassifier().classify('帮我润色：请你明天下午三点来公司面试', _ctx())
        assert decision.route_track == 'C_DIALOGUE_KNOWLEDGE'
        assert decision.task_type == 'dialogue'

    def test_generation_goes_generation(self) -> None:
        decision = TrackClassifier().classify('生成 8 道 Java 后端面试题', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.task_type == 'generation'
        assert decision.intent == 'interview_questions'

    def test_data_query_goes_data_action(self) -> None:
        decision = TrackClassifier().classify('查一下最近 5 个 Java 候选人', _ctx())
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_type == 'data_query'

    def test_recent_applicants_without_query_verb_goes_data_action(self) -> None:
        decision = TrackClassifier().classify('最近来应聘电子工程师的都有哪些人', _ctx())
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_type == 'data_query'

    def test_named_resume_lookup_goes_data_action(self) -> None:
        decision = TrackClassifier().classify('吴明华的简历', _ctx())
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_type == 'data_query'

    def test_find_and_generate_goes_composite(self) -> None:
        decision = TrackClassifier().classify('找出最近 5 个 Java 候选人，并帮我设计面试题', _ctx())
        assert decision.route_track == 'COMPOSITE'
        assert decision.task_type == 'composite'

    def test_delete_goes_forbidden(self) -> None:
        decision = TrackClassifier().classify('删除这个候选人', _ctx())
        assert decision.task_type == 'forbidden'
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.requires_confirmation is True


class TestPlanner:
    def test_direct_recruitment_rules_skip_llm_for_clear_job_lookup(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
        monkeypatch.setattr(llm_skill_planner, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(llm_skill_planner.llm_client, 'is_available', lambda: True)
        called = {'value': False}

        def fake_llm(*args, **kwargs):
            called['value'] = True
            return {
                'task_type': 'data_query',
                'route_track': 'A_DATA_ACTION',
                'intent': 'recruitment_jobs_query',
                'confidence': 0.91,
                'risk_level': 'low',
                'tool_plan': [{
                    'tool': 'recruitment_search',
                    'purpose': 'query',
                    'input': {'module': 'jobs', 'status': 'open', 'limit': 20},
                    'required': True,
                    'risk_level': 'low',
                }],
                'reason': '规范化口语请求为在招岗位查询',
            }

        monkeypatch.setattr(
            llm_skill_planner.llm_client,
            'json_chat_profile',
            fake_llm,
        )

        app = Flask(__name__)
        with app.app_context():
            decision = build_route_decision('我们现在有哪些岗位在招人', _ctx())

        assert called['value'] is False
        assert decision.reason == 'direct_recruitment_query_plan'
        assert decision.tool_plan[0].tool == 'recruitment_search'
        assert decision.tool_plan[0].input == {'module': 'jobs', 'limit': 10, 'status': 'open'}

    def test_recruitment_match_matrix_first_turn_skips_llm_planner(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
        monkeypatch.setattr(
            llm_skill_planner,
            'plan_with_llm',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('match matrix should skip LLM planner')),
        )

        decision = build_route_decision('电子工程师岗位最近候选人谁更合适？给对比矩阵', _ctx())

        assert decision.reason == 'direct_recruitment_match_matrix_plan'
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'candidate_compare'
        assert decision.generation_plan is not None
        assert decision.generation_plan.template_id == 'candidate_compare'
        assert decision.required_context == []
        assert decision.tool_plan[0].tool == 'recruitment_match_matrix'
        assert decision.tool_plan[0].purpose == 'load_context'
        assert decision.tool_plan[0].input == {'keyword': '电子工程师', 'limit': 8}

    def test_llm_smart_sql_plan_for_simple_recruitment_query_is_corrected_to_domain_skill(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
        monkeypatch.setattr(llm_skill_planner, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(llm_skill_planner.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(
            llm_skill_planner.llm_client,
            'json_chat_profile',
            lambda *args, **kwargs: {
                'normalized_query': '统计最近30天内应聘电子工程师岗位的候选人数量',
                'task_type': 'data_query',
                'route_track': 'A_DATA_ACTION',
                'intent': '查询特定岗位候选人数',
                'confidence': 0.95,
                'risk_level': 'low',
                'tool_plan': [{
                    'tool': 'smart_data_query',
                    'purpose': 'query',
                    'input': {
                        'question': '最近30天内应聘电子工程师岗位的候选人有多少人？',
                        'sql': "SELECT COUNT(*) AS count FROM candidates c JOIN jobs j ON c.job_id = j.id WHERE j.title LIKE '%电子工程师%' AND c.created_at >= NOW() - INTERVAL '30 days'",
                        'explanation': '模型生成的自由 SQL',
                    },
                    'required': True,
                    'risk_level': 'low',
                }],
                'reason': '模型选择了智能 SQL',
            },
        )

        app = Flask(__name__)
        with app.app_context():
            decision = llm_skill_planner.plan_with_llm('最近来应聘电子工程师的有多少人', _ctx())

        assert decision is not None
        assert decision.reason.startswith('llm_skill_planner:')
        assert decision.tool_plan[0].tool == 'recruitment_search'
        assert decision.tool_plan[0].input == {
            'module': 'candidates',
            'limit': 20,
            'count_only': True,
            'keyword': '电子工程师',
            'date_range': {'recent_days': 30},
        }

    def test_llm_recruitment_search_plan_with_wrong_open_status_is_corrected(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
        monkeypatch.setattr(llm_skill_planner, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(llm_skill_planner.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(
            llm_skill_planner.llm_client,
            'json_chat_profile',
            lambda *args, **kwargs: {
                'normalized_query': '统计当前正在招聘的岗位数量',
                'task_type': 'data_query',
                'route_track': 'A_DATA_ACTION',
                'intent': 'open_job_count',
                'confidence': 0.95,
                'risk_level': 'low',
                'tool_plan': [{
                    'tool': 'recruitment_search',
                    'purpose': 'query',
                    'input': {'module': 'jobs', 'status': 'active', 'limit': 100},
                    'required': True,
                    'risk_level': 'low',
                }],
                'reason': '模型把在招状态写成 active',
            },
        )

        app = Flask(__name__)
        with app.app_context():
            decision = llm_skill_planner.plan_with_llm('我们现在有多少个岗位在招人', _ctx())

        assert decision is not None
        assert decision.reason.startswith('llm_skill_planner:')
        assert 'corrected_to=recruitment_search' in decision.reason
        assert decision.tool_plan[0].tool == 'recruitment_search'
        assert decision.tool_plan[0].input == {
            'module': 'jobs',
            'limit': 10,
            'count_only': True,
            'status': 'open',
        }

    def test_llm_open_job_count_normalized_status_phrase_does_not_become_keyword(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
        monkeypatch.setattr(llm_skill_planner, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(llm_skill_planner.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(
            llm_skill_planner.llm_client,
            'json_chat_profile',
            lambda *args, **kwargs: {
                'normalized_query': '统计当前状态为在招的岗位总数',
                'task_type': 'data_query',
                'route_track': 'A_DATA_ACTION',
                'intent': 'open_job_count',
                'confidence': 0.95,
                'risk_level': 'low',
                'tool_plan': [{
                    'tool': 'smart_data_query',
                    'purpose': 'query',
                    'input': {
                        'question': '统计当前状态为在招的岗位总数',
                        'sql': 'SELECT COUNT(*) FROM jobs WHERE status = "open"',
                        'explanation': '模型生成的自由 SQL',
                    },
                    'required': True,
                    'risk_level': 'low',
                }],
                'reason': '模型把岗位数量规划成自由 SQL',
            },
        )

        app = Flask(__name__)
        with app.app_context():
            decision = llm_skill_planner.plan_with_llm('我们现在有多少个岗位在招人', _ctx())

        assert decision is not None
        assert decision.reason.startswith('llm_skill_planner:')
        assert decision.tool_plan[0].input == {
            'module': 'jobs',
            'limit': 10,
            'count_only': True,
            'status': 'open',
        }

    def test_llm_recruitment_progress_plan_is_corrected_to_multi_domain_queries(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.delenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', raising=False)
        monkeypatch.setattr(llm_skill_planner, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(llm_skill_planner.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(
            llm_skill_planner.llm_client,
            'json_chat_profile',
            lambda *args, **kwargs: {
                'normalized_query': '查询电子工程师招聘进展，包括岗位、候选人、面试等状态',
                'task_type': 'data_query',
                'route_track': 'A_DATA_ACTION',
                'intent': 'recruitment_progress',
                'confidence': 0.94,
                'risk_level': 'low',
                'tool_plan': [{
                    'tool': 'system_search',
                    'purpose': 'query',
                    'input': {'module': 'recruitment', 'keyword': '电子工程师', 'limit': 12},
                    'required': True,
                    'risk_level': 'low',
                }],
                'reason': '模型把招聘进展识别成泛招聘检索',
            },
        )

        app = Flask(__name__)
        with app.app_context():
            decision = llm_skill_planner.plan_with_llm('帮我看一下电子工程师招聘的怎么样了', _ctx())

        assert decision is not None
        assert decision.reason.startswith('llm_skill_planner:')
        assert 'corrected_to=recruitment_progress' in decision.reason
        assert [plan.tool for plan in decision.tool_plan] == ['recruitment_search'] * 4
        assert [plan.input['module'] for plan in decision.tool_plan] == [
            'jobs',
            'candidates',
            'resumes',
            'interviews',
        ]
        assert all(plan.input.get('keyword') == '电子工程师' for plan in decision.tool_plan)
        assert decision.tool_plan[0].input.get('status') == 'open'
        assert all(plan.input.get('count_only') is True for plan in decision.tool_plan[1:])

    def test_llm_skill_planner_can_select_skill_without_template_mapping(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import llm_skill_planner

        monkeypatch.setenv('ASSISTANT_ENABLE_SKILL_PLANNER_OUTSIDE_APP', '1')
        monkeypatch.setattr(llm_skill_planner, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(llm_skill_planner.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(
            llm_skill_planner.llm_client,
            'json_chat_profile',
            lambda *args, **kwargs: {
                'task_type': 'data_query',
                'route_track': 'A_DATA_ACTION',
                'intent': 'recent_resume_analysis',
                'confidence': 0.86,
                'risk_level': 'low',
                'tool_plan': [{
                    'tool': 'resume_analysis',
                    'purpose': 'query',
                    'input': {'recent_days': 7, 'keyword': '电子工程师', 'top_n': 8},
                    'required': True,
                    'risk_level': 'low',
                }],
                'reason': '用户要查询最近电子工程师简历，直接调用简历分析技能',
            },
        )

        decision = build_route_decision('最近来应聘电子工程师的都有哪些人', _ctx())

        assert decision.reason.startswith('llm_skill_planner:')
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_template_id is None
        assert decision.tool_plan[0].tool == 'resume_analysis'
        assert decision.tool_plan[0].input['keyword'] == '电子工程师'

    def test_generation_plan_is_built_for_email(self) -> None:
        decision = build_route_decision('写一封面试邀约邮件', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.generation_plan is not None
        assert decision.generation_plan.template_id == 'hr_email_draft'
        assert decision.generation_plan.output_format == 'markdown'

    def test_workset_mention_requires_candidate_context(self) -> None:
        decision = build_route_decision('帮我基于这几个人生成面试题', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert 'candidate_workset' in decision.required_context

    def test_every_person_mention_requires_latest_workset_context(self) -> None:
        decision = build_route_decision('帮我针对每个人出一份面试题', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'interview_questions'
        assert 'candidate_workset' in decision.required_context

    def test_personal_experience_followup_requires_latest_workset_context(self) -> None:
        decision = build_route_decision('结合他们的个人经历出题', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'interview_questions'
        assert 'latest_workset' in decision.required_context

    def test_plural_analysis_followup_requires_latest_workset_context(self) -> None:
        decision = build_route_decision('分别分析一下这些候选人', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'analysis_report'
        assert 'latest_workset' in decision.required_context

    def test_resume_compare_followup_requires_latest_workset_context(self) -> None:
        decision = build_route_decision('对比一下上面这些简历', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'candidate_compare'
        assert 'latest_workset' in decision.required_context

    def test_ranking_report_followup_requires_latest_workset_context(self) -> None:
        decision = build_route_decision('给我一个排名比对报表', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'candidate_compare'
        assert 'latest_workset' in decision.required_context

    def test_above_twenty_top_three_interview_uses_workset_action(self) -> None:
        decision = build_route_decision('给上面20个人里排名前三的安排明天早晨8点的面试', _ctx())
        assert decision.task_type == 'action'
        assert decision.intent == 'interview_schedule'
        assert decision.required_context == ['latest_workset']
        assert decision.tool_plan[0].tool == 'interview_create'

    def test_comparative_workset_metric_uses_workset_analysis(self) -> None:
        decision = build_route_decision('其中年龄最小的是谁', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'workset_analysis'
        assert 'latest_workset' in decision.required_context
        assert decision.tool_plan[0].tool == 'workset_analyze'

    def test_match_degree_workset_metric_is_not_named_person_assessment(self) -> None:
        decision = build_route_decision('其中匹配度最高的是谁', _ctx())
        assert decision.route_track == 'B_GENERATION'
        assert decision.intent == 'workset_analysis'
        assert decision.tool_plan[0].tool == 'workset_analyze'

    def test_composite_gets_tool_and_generation_plan(self) -> None:
        decision = build_route_decision('找出最近 5 个 Java 候选人，并帮我设计面试题', _ctx())
        assert decision.route_track == 'COMPOSITE'
        assert decision.tool_plan
        assert decision.tool_plan[0].tool == 'recruitment_search'
        assert decision.tool_plan[0].purpose == 'query'
        assert decision.tool_plan[0].input['module'] == 'candidates'
        assert decision.tool_plan[0].input['limit'] == 5
        assert decision.generation_plan is not None
        assert decision.generation_plan.template_id == 'interview_questions'

    def test_recent_applicant_query_routes_to_direct_recruitment_search_in_app(self, monkeypatch) -> None:
        monkeypatch.setenv('ASSISTANT_ENABLE_RECENT_RECRUITMENT_HOTPATH_OUTSIDE_APP', '1')
        decision = build_route_decision('最近来应聘电子工程师的都有哪些人', _ctx())
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_template_id is None
        assert decision.tool_plan[0].tool == 'recruitment_search'
        assert decision.tool_plan[0].input['keyword'] == '电子工程师'
        assert decision.tool_plan[0].input['module'] == 'candidates'
        assert decision.tool_plan[0].input['limit'] == 20

    def test_recent_resume_delivery_query_routes_to_resume_analysis(self) -> None:
        decision = build_route_decision('帮我找一下最近投递简历的几位候选人', _ctx())
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_template_id == 'recent_resume_analysis'
        assert decision.router_result is not None
        assert 'keyword' not in decision.router_result.entities

    def test_named_resume_lookup_keeps_person_keyword(self) -> None:
        decision = build_route_decision('吴明华的简历', _ctx())
        assert decision.route_track == 'A_DATA_ACTION'
        assert decision.task_template_id is None
        assert decision.tool_plan[0].tool == 'recruitment_search'
        assert decision.tool_plan[0].input['module'] == 'resumes'
        assert decision.tool_plan[0].input['keyword'] == '吴明华'

    def test_llm_router_cannot_erase_rule_keyword(self, monkeypatch) -> None:
        def fake_json_chat(*args, **kwargs):
            return {
                'intent': '查询候选人吴明华的简历信息',
                'task_template_id': 'global_search_answer',
                'confidence': 0.8,
                'entities': {'keyword': ''},
                'candidate_skills': ['global_search'],
                'risk_level': 'low',
            }

        monkeypatch.setattr(legacy_router.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(legacy_router.llm_client, 'json_chat_profile', fake_json_chat)

        result = legacy_router.route('吴明华的简历', _ctx())

        assert result.task_template_id == 'global_search_answer'
        assert result.entities.get('keyword') == '吴明华'

    def test_named_resume_lookup_is_high_confidence_rule(self, monkeypatch) -> None:
        def fail_if_called(*args, **kwargs):
            raise AssertionError('LLM router should not be called for named resume lookup')

        monkeypatch.setattr(legacy_router.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(legacy_router.llm_client, 'json_chat_profile', fail_if_called)

        result = legacy_router.route('吴明华的简历', _ctx())

        assert result.task_template_id == 'global_search_answer'
        assert result.confidence >= 0.78
        assert result.entities.get('keyword') == '吴明华'


class TestAgentModelEnhancements:
    def test_prompt_optimizer_uses_agent_kernel_skill_context_with_strong_model(self, monkeypatch) -> None:
        from services.assistant_core import prompt_optimizer

        captured = {}

        monkeypatch.setattr(prompt_optimizer, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(prompt_optimizer.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(prompt_optimizer, 'model_for_profile', lambda profile, use_case: 'deepseek-ai/DeepSeek-V4-Pro')

        def fake_chat(profile, messages, **kwargs):
            captured['profile'] = profile
            captured['messages'] = messages
            captured['kwargs'] = kwargs
            return {'content': '检索吴明华的简历、岗位和面试记录，并基于证据分析录用风险。'}

        monkeypatch.setattr(prompt_optimizer.llm_client, 'chat_profile', fake_chat)

        result = prompt_optimizer.optimize_prompt('吴明华怎么样', _ctx())

        system_prompt = captured['messages'][0]['content']
        user_prompt = captured['messages'][1]['content']
        assert captured['profile'] == 'strong'
        assert captured['kwargs']['use_case'] == 'prompt_optimization'
        assert 'Skill-first Agent Kernel' in system_prompt
        assert '候选 Skill' in system_prompt
        assert '检索系统中的简历' in system_prompt
        assert 'Agent Kernel 候选 Skill' in user_prompt
        assert result['model'] == 'deepseek-ai/DeepSeek-V4-Pro'
        assert result['routeTrack'] == 'AGENT_KERNEL_SKILL_FIRST'
        assert result['selectedSkill']
        assert result['topSkills']
        assert '录用风险' in result['optimized']

    def test_prompt_optimizer_does_not_import_legacy_planner(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / 'services'
            / 'assistant_core'
            / 'prompt_optimizer.py'
        ).read_text(encoding='utf-8')

        assert 'intent_router.legacy_planner' not in source
        assert 'build_route_decision' not in source

    def test_complex_generation_can_receive_strong_model_planning_brief(self, monkeypatch) -> None:
        from services.assistant_core.intent_router import semantic_refiner

        decision = build_route_decision('分别分析这些候选人的经历并给出面试策略', _ctx())
        monkeypatch.setattr(semantic_refiner, 'feature_enabled', lambda name: True)
        monkeypatch.setattr(semantic_refiner.llm_client, 'is_available', lambda: True)
        monkeypatch.setattr(
            semantic_refiner.llm_client,
            'json_chat_profile',
            lambda *args, **kwargs: {
                'planning_brief': '逐人核验证据并生成策略',
                'required_evidence': ['resume', 'interview'],
                'output_focus': ['风险'],
            },
        )

        enriched = semantic_refiner.enrich_complex_decision(
            '分别分析这些候选人的经历并给出面试策略',
            _ctx(),
            decision,
        )

        assert enriched.generation_plan.constraints['planning_brief'] == '逐人核验证据并生成策略'
        assert enriched.generation_plan.constraints['required_evidence'] == ['resume', 'interview']

