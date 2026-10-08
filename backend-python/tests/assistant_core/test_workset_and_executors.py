"""WorkSet and hybrid executor tests."""

from __future__ import annotations

from services.assistant_core.schemas import AssistantContext, GenerationPlan, RouteDecision
from services.assistant_core.workset_store import WorkSetStore, default_store
from services.assistant_core.executors.dialogue_executor import DialogueExecutor
from services.assistant_core.executors.generation_executor import GenerationExecutor
from services.assistant_core.executors.tool_executor import ToolExecutor


def _ctx(role: str = 'hr_admin') -> AssistantContext:
    return AssistantContext(user_id='u-workset', role=role, session_id='sess-workset')


class TestWorkSetStore:
    def test_create_and_resolve_plural_candidate_workset(self) -> None:
        store = WorkSetStore()
        ws = store.create_workset_from_entities(
            session_id='s1',
            user_id='u1',
            label='最近 5 个 Java 候选人',
            entities=[
                {'type': 'candidate', 'id': 'c1', 'title': '张三', 'subtitle': 'Java'},
                {'type': 'candidate', 'id': 'c2', 'title': '李四', 'subtitle': 'Java'},
            ],
        )

        resolved = store.resolve_mention('帮我基于这几个人生成面试题', 's1')

        assert ws['entity_type'] == 'candidate'
        assert resolved is not None
        assert resolved['kind'] == 'workset'
        assert resolved['workset']['id'] == ws['id']
        assert resolved['workset']['items'][0]['entity_id'] == 'c1'

    def test_resolve_ordinal_candidate(self) -> None:
        store = WorkSetStore()
        store.create_workset_from_entities(
            's1',
            'u1',
            '候选人',
            [
                {'type': 'candidate', 'id': 'c1', 'title': '张三'},
                {'type': 'candidate', 'id': 'c2', 'title': '李四'},
                {'type': 'candidate', 'id': 'c3', 'title': '王五'},
            ],
        )

        resolved = store.resolve_mention('第二个适合吗', 's1')

        assert resolved is not None
        assert resolved['kind'] == 'item'
        assert resolved['item']['entity_id'] == 'c2'

    def test_resolve_single_candidate_pronoun_from_latest_item_workset(self) -> None:
        store = WorkSetStore()
        ws = store.create_workset_from_entities(
            's1',
            'u1',
            '候选人画像',
            [{'type': 'candidate', 'id': 'c2', 'title': '杨琳'}],
        )

        resolved = store.resolve_mention('给他安排明天早晨八点面试', 's1')

        assert resolved is not None
        assert resolved['kind'] == 'item'
        assert resolved['workset']['id'] == ws['id']
        assert resolved['item']['entity_id'] == 'c2'

    def test_resolve_pronoun_does_not_collapse_plural_comparison(self) -> None:
        store = WorkSetStore()
        store.create_workset_from_entities(
            's1',
            'u1',
            '候选人列表',
            [
                {'type': 'candidate', 'id': 'c1', 'title': '邓浩'},
                {'type': 'candidate', 'id': 'c2', 'title': '杨琳'},
            ],
        )

        resolved = store.resolve_mention('他们谁更适合', 's1')

        assert resolved is not None
        assert resolved['kind'] == 'workset'

    def test_resolve_every_person_from_latest_resume_workset(self) -> None:
        store = WorkSetStore()
        ws = store.create_workset_from_entities(
            's1',
            'u1',
            '最近电子工程师招聘情况',
            [
                {'type': 'resume', 'id': 'r1', 'title': '李博豪', 'subtitle': '电子工程师'},
                {'type': 'resume', 'id': 'r2', 'title': '高春喜', 'subtitle': '电子工程师'},
            ],
        )

        resolved = store.resolve_mention('帮我针对每个人出一份面试题', 's1')

        assert ws['entity_type'] == 'resume'
        assert resolved is not None
        assert resolved['kind'] == 'workset'
        assert resolved['workset']['id'] == ws['id']
        assert [item['entity_id'] for item in resolved['workset']['items']] == ['r1', 'r2']

    def test_resolve_generic_plural_uses_latest_workset_not_old_candidate(self) -> None:
        store = WorkSetStore()
        store.create_workset_from_entities(
            's1',
            'u1',
            '候选人旧结果',
            [{'type': 'candidate', 'id': 'c1', 'title': '张三'}],
        )
        employee_ws = store.create_workset_from_entities(
            's1',
            'u1',
            '员工新结果',
            [
                {'type': 'employee', 'id': 'e1', 'title': '员工一'},
                {'type': 'employee', 'id': 'e2', 'title': '员工二'},
            ],
        )

        resolved = store.resolve_mention('分别分析一下他们', 's1')

        assert resolved is not None
        assert resolved['kind'] == 'workset'
        assert resolved['workset']['id'] == employee_ws['id']

    def test_resolve_above_resumes_for_compare(self) -> None:
        store = WorkSetStore()
        ws = store.create_workset_from_entities(
            's1',
            'u1',
            '简历列表',
            [
                {'type': 'resume', 'id': 'r1', 'title': '李博豪'},
                {'type': 'resume', 'id': 'r2', 'title': '高春喜'},
            ],
        )

        resolved = store.resolve_mention('对比一下上面这些简历', 's1')

        assert resolved is not None
        assert resolved['kind'] == 'workset'
        assert resolved['workset']['id'] == ws['id']

    def test_resolve_metric_question_from_latest_workset(self) -> None:
        store = WorkSetStore()
        ws = store.create_workset_from_entities(
            's1',
            'u1',
            '最近应聘电子工程师',
            [
                {'type': 'candidate', 'id': 'c1', 'title': '张三'},
                {'type': 'candidate', 'id': 'c2', 'title': '李四'},
            ],
        )

        resolved = store.resolve_mention('其中年龄最小的是谁', 's1')

        assert resolved is not None
        assert resolved['kind'] == 'workset'
        assert resolved['workset']['id'] == ws['id']

    def test_resolve_ranking_report_from_latest_workset(self) -> None:
        store = WorkSetStore()
        ws = store.create_workset_from_entities(
            's1',
            'u1',
            '最近应聘电子工程师',
            [
                {'type': 'candidate', 'id': 'c1', 'title': '张三'},
                {'type': 'candidate', 'id': 'c2', 'title': '李四'},
            ],
        )

        resolved = store.resolve_mention('给上面20个人做排名比对报表', 's1')

        assert resolved is not None
        assert resolved['kind'] == 'workset'
        assert resolved['workset']['id'] == ws['id']


class TestDialogueExecutor:
    def test_dialogue_fallback_answers_capability_without_llm(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'chat_profile', lambda *a, **kw: None)

        result = DialogueExecutor().execute('你能做什么？', _ctx())

        assert result.summary
        assert '查询' in result.summary
        assert '润色' in result.summary
        assert result.widgets == []
        assert result.entities == []

    def test_dialogue_fallback_polishes_user_text_without_search(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'chat_profile', lambda *a, **kw: None)

        result = DialogueExecutor().execute('帮我润色：请你明天下午三点来公司面试', _ctx())

        assert '润色' in result.summary
        assert '明天下午三点' in result.summary
        assert result.widgets == []


class TestGenerationExecutor:
    def test_interview_question_fallback_respects_requested_count(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'chat_profile', lambda *a, **kw: None)
        plan = GenerationPlan(template_id='interview_questions', output_format='markdown')

        result = GenerationExecutor().execute('生成 8 道 Java 后端面试题', _ctx(), plan, context={})

        assert result.answer['format'] == 'markdown'
        assert '1.' in result.summary
        assert '8.' in result.summary
        assert 'Java' in result.summary
        assert '# ' not in result.summary

    def test_generation_redacts_sensitive_salary_for_employee(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'chat_profile', lambda *a, **kw: {'content': '候选人薪酬 30000 元，电话 13812345678'})
        plan = GenerationPlan(template_id='analysis_report', output_format='markdown')

        result = GenerationExecutor().execute('分析报告', _ctx(role='employee'), plan, context={'facts': []})

        assert '30000' not in result.summary
        assert '13812345678' not in result.summary

    def test_complex_generation_can_use_strong_model_review(self, monkeypatch) -> None:
        from services.assistant_core import llm_client, model_settings

        calls = []

        def fake_chat(profile, messages, **kwargs):
            calls.append({'profile': profile, 'messages': messages, 'kwargs': kwargs})
            if len(calls) == 1:
                return {'content': '初稿：候选人不错。'}
            return {'content': '复核后结论：候选人优势是电源设计，风险是缺少量产证据，建议追问EMC测试。'}

        monkeypatch.setattr(model_settings, 'feature_enabled', lambda name: name == 'multiAgentReasoning')
        monkeypatch.setattr(llm_client, 'chat_profile', fake_chat)
        plan = GenerationPlan(template_id='person_assessment', output_format='markdown', model_profile='standard')
        context = {'details': [{'name': '胡国卫', 'skills': ['电源设计'], 'weaknesses': ['量产证据不足']}]}

        result = GenerationExecutor().execute('胡国卫表现怎么样', _ctx(), plan, context=context)

        assert len(calls) == 2
        assert calls[0]['profile'] == 'standard'
        assert calls[1]['profile'] == 'strong'
        assert calls[1]['kwargs']['use_case'] == 'evidenceAnalysis'
        assert '复核后结论' in result.summary
        assert 'EMC测试' in result.summary

    def test_simple_generation_skips_strong_model_review(self, monkeypatch) -> None:
        from services.assistant_core import llm_client, model_settings

        calls = []

        def fake_chat(profile, messages, **kwargs):
            calls.append(profile)
            return {'content': '面试邀约邮件草稿'}

        monkeypatch.setattr(model_settings, 'feature_enabled', lambda name: name == 'multiAgentReasoning')
        monkeypatch.setattr(llm_client, 'chat_profile', fake_chat)
        plan = GenerationPlan(template_id='hr_email_draft', output_format='markdown', model_profile='standard')

        result = GenerationExecutor().execute('写一封邀约邮件', _ctx(), plan, context={})

        assert calls == ['standard']
        assert '面试邀约邮件草稿' in result.summary

    def test_interview_fallback_uses_personal_resume_questions(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'chat_profile', lambda *a, **kw: None)
        plan = GenerationPlan(template_id='interview_questions', output_format='markdown')
        context = {
            'items': [
                {'title': '李博豪', 'entity_id': 'r1', 'subtitle': '电子工程师'},
                {'title': '高春喜', 'entity_id': 'r2', 'subtitle': '电子工程师'},
            ],
            'details': [
                {
                    'candidate_name': '李博豪',
                    'interview_focus': ['户外电子系统设计经验'],
                    'interview_questions': [
                        {'question': '请说明你做过的户外电源防水设计项目。', 'purpose': '验证项目经历'},
                    ],
                },
                {
                    'candidate_name': '高春喜',
                    'interview_focus': ['抗干扰和散热设计能力'],
                    'interview_questions': [
                        {'question': '请复盘一次灯具散热方案优化经历。', 'purpose': '验证工程权衡'},
                    ],
                },
            ],
        }

        result = GenerationExecutor().execute('帮我针对每个人出一份面试题', _ctx(), plan, context=context)

        assert '户外电源防水设计项目' in result.summary
        assert '灯具散热方案优化经历' in result.summary
        assert result.summary.count('请结合过往项目说明你最熟悉的电子/硬件模块设计经验') <= 1

    def test_candidate_compare_report_uses_loaded_scores_without_llm(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(
            llm_client,
            'chat_profile',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('ranking report should be deterministic')),
        )
        plan = GenerationPlan(template_id='candidate_compare', output_format='markdown')
        context = {
            'items': [
                {'title': '低分候选人', 'entity_id': 'c1', 'subtitle': '电子工程师'},
                {'title': '高分候选人', 'entity_id': 'c2', 'subtitle': '电子工程师'},
            ],
            'details': [
                {'name': '低分候选人', 'resume': {'score': 70, 'match_degree': 75, 'strengths': ['稳定']}},
                {'name': '高分候选人', 'resume': {'score': 90, 'match_degree': 88, 'strengths': ['项目经验强']}},
            ],
        }

        result = GenerationExecutor().execute('给我一个排名比对报表', _ctx(), plan, context=context)

        assert '排名比对报表' in result.summary
        assert result.summary.index('1. 高分候选人') < result.summary.index('2. 低分候选人')
        assert '90分' in result.summary

    def test_single_workset_candidate_risk_followup_uses_evidence_without_llm(self, monkeypatch) -> None:
        from services.assistant_core import llm_client

        monkeypatch.setattr(
            llm_client,
            'chat_profile',
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('single candidate risk follow-up should be deterministic')),
        )
        plan = GenerationPlan(template_id='candidate_assessment', output_format='markdown')
        context = {
            'context_source': 'workset',
            'items': [{'entity_type': 'candidate', 'entity_id': 'c-yanglin', 'title': '杨琳', 'subtitle': '电子工程师'}],
            'details': [{
                'name': '杨琳',
                'candidate': {
                    'status': 'screening',
                    'ai_summary': '传感器调试和低功耗设计较强。',
                    'ai_recommendation': '建议二面验证 EMC 和量产导入经验。',
                },
                'resume': {
                    'score': 86,
                    'match_degree': 88,
                    'summary': '传感器调试、低功耗设计扎实，量产导入经验中等。',
                    'strengths': ['低功耗设计扎实'],
                    'weaknesses': ['EMC整改经验不足', '量产整改案例相对有限'],
                    'interview_focus': ['EMC整改方法', '供应链问题定位'],
                },
                'job': {
                    'title': '电子工程师',
                    'requirements': '熟悉模拟/数字电路、EMC、可靠性测试和量产导入。',
                },
                'interviews': [{'status': 'scheduled', 'notes': '复试验证 EMC 和量产导入细节。'}],
            }],
        }

        result = GenerationExecutor().execute('那第二个人有什么风险，下一步怎么推进？', _ctx(), plan, context=context)

        assert '杨琳 风险与推进建议' in result.summary
        assert 'EMC整改经验不足' in result.summary
        assert '下一步建议' in result.summary
        assert '二次确认' in result.summary
        assert '安排面试' in result.summary

    def test_workset_context_loads_more_than_five_resume_details(self, monkeypatch) -> None:
        from services.assistant_core import legacy_orchestrator as orchestrator

        default_store.clear()
        default_store.create_workset_from_entities(
            'sess-workset',
            'u-workset',
            '最近 8 份简历',
            [{'type': 'resume', 'id': f'r{i}', 'title': f'候选人{i}'} for i in range(1, 9)],
        )
        calls = []

        def fake_execute(self, tool, params, ctx):
            calls.append((tool, dict(params)))
            return {
                'ok': True,
                'tool': tool,
                'data': {'facts': {'resume_id': params['resume_id'], 'interview_focus': [params['resume_id']]}},
                'rows_count': 1,
            }

        monkeypatch.setattr(orchestrator.ToolExecutor, 'execute', fake_execute)
        decision = RouteDecision(
            task_type='generation',
            route_track='B_GENERATION',
            intent='interview_questions',
            confidence=0.9,
            required_context=['latest_workset'],
        )

        context, clarification = orchestrator._context_from_workset(
            '帮我针对每个人出一份面试题',
            _ctx(),
            decision,
        )

        assert clarification is None
        assert context is not None
        assert len(context['items']) == 8
        assert len(context['details']) == 8
        assert len(calls) == 8


class TestToolExecutor:
    def test_tool_executor_returns_standard_permission_error(self, monkeypatch) -> None:
        from services.assistant_core import skill_registry

        class _Skill:
            id = 'payroll_analysis'
            allowed_roles = ['admin']
            action_type = 'READ_SENSITIVE'
            risk_level = 'high'
            handler = staticmethod(lambda params, ctx: {'rows_count': 1})

        monkeypatch.setattr(skill_registry, 'get', lambda tool: _Skill())

        out = ToolExecutor().execute('payroll_analysis', {}, _ctx(role='employee'))

        assert out['ok'] is False
        assert out['tool'] == 'payroll_analysis'
        assert out['rows_count'] == 0
        assert '权限' in out['error']


class TestToolWorkbench:
    def test_validates_schema_and_preserves_executor_only_params(self, monkeypatch) -> None:
        from services.assistant_core import skill_registry
        from services.assistant_core.agent_kernel.tool_workbench import ToolWorkbench

        class _Skill:
            id = 'resume_analysis'
            input_schema = {
                'recent_days': {'type': 'integer', 'required': True},
                'top_n': {'type': 'integer', 'default': 10},
            }
            allowed_roles = ['hr_admin']
            action_type = 'READ_HR'

        seen: dict = {}

        def fake_execute(self, tool, params, ctx):
            seen.update({'tool': tool, 'params': dict(params)})
            return {'ok': True, 'tool': tool, 'data': {}, 'rows_count': 0}

        monkeypatch.setattr(skill_registry, 'get', lambda tool: _Skill())
        monkeypatch.setattr(ToolExecutor, 'execute', fake_execute)

        out = ToolWorkbench().call(
            'resume_analysis',
            {'recent_days': '10', 'question': '最近10天我们收到了哪些简历'},
            _ctx(role='hr_admin'),
        )

        assert out['ok'] is True
        assert seen['tool'] == 'resume_analysis'
        assert seen['params'] == {
            'recent_days': 10,
            'question': '最近10天我们收到了哪些简历',
            'top_n': 10,
        }
        assert out['workbench']['schema_checked'] is True
        assert out['workbench']['hidden_params'] == ['question']

    def test_classifies_tool_and_argument_errors(self, monkeypatch) -> None:
        from services.assistant_core import skill_registry
        from services.assistant_core.agent_kernel.tool_workbench import ToolWorkbench

        class _Skill:
            id = 'smart_data_query'
            input_schema = {'question': {'type': 'string', 'required': True}}
            allowed_roles = ['hr_admin']
            action_type = 'READ_HR'

        monkeypatch.setattr(skill_registry, 'get', lambda tool: None)
        missing = ToolWorkbench().call('missing_tool', {}, _ctx(role='hr_admin'))
        assert missing['ok'] is False
        assert missing['error'] == 'tool_not_found'

        monkeypatch.setattr(skill_registry, 'get', lambda tool: _Skill())
        invalid = ToolWorkbench().call('smart_data_query', {'sql': 'select * from employees'}, _ctx(role='hr_admin'))
        assert invalid['ok'] is False
        assert invalid['error'] == 'invalid_tool_arguments'
        assert invalid['error_details']['errors'][0]['error'] == 'forbidden_hidden_param'
