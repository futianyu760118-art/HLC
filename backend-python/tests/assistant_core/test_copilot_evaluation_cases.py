from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / 'services' / 'assistant_core' / 'evaluation_cases.yaml'


def test_copilot_evaluation_cases_have_root_cause_contract() -> None:
    data = yaml.safe_load(CASES_PATH.read_text(encoding='utf-8'))
    taxonomy = set(data['failure_taxonomy'])

    assert data['version'] == 'assistant.evaluation.v1'
    assert len(data['cases']) >= 10

    required_keys = {
        'id',
        'question',
        'scenario',
        'expected_modules',
        'expected_render_blocks',
        'expected_behavior',
        'requires_confirmation',
        'root_cause_dimensions',
    }
    for case in data['cases']:
        assert required_keys <= set(case), case.get('id')
        assert case['expected_modules'], case['id']
        assert case['expected_render_blocks'], case['id']
        assert case['expected_behavior'], case['id']
        assert set(case['root_cause_dimensions']) <= taxonomy, case['id']
        assert set(case['root_cause_dimensions']), case['id']


def test_copilot_evaluation_cases_cover_required_modules_and_render_modes() -> None:
    data = yaml.safe_load(CASES_PATH.read_text(encoding='utf-8'))
    modules = {module for case in data['cases'] for module in case['expected_modules']}
    render_modes = {mode for case in data['cases'] for mode in case['expected_render_blocks']}
    scenarios = {case['scenario'] for case in data['cases']}

    assert {
        'employees',
        'attendance_records',
        'attendance_stats',
        'leave_requests',
        'salary_profiles',
        'performance_reviews',
        'employee_changes',
        'notifications',
        'system_settings',
        'jobs',
        'candidates',
    } <= modules
    assert {'markdown', 'kpi', 'table', 'timeline', 'matrix', 'status', 'confirmation', 'sources', 'media', 'workset', 'notice'} <= render_modes
    assert {
        '考勤异常分析', '员工画像', '招聘匹配', '薪资绩效联动', '员工异动影响分析',
        '写入动作确认执行', '审批动作确认执行', '员工异动确认提交', '权限与脱敏边界', '多形态附件预览',
        '多轮追问与结果集记忆', '系统设置与模型配置',
    } <= scenarios
    assert any(case['requires_confirmation'] for case in data['cases'])
    assert any(case.get('confirmation_flow') for case in data['cases'])
    assert any('page_context' in case['root_cause_dimensions'] for case in data['cases'])
    assert any(case.get('expected_error_code') == 'permission_denied' for case in data['cases'])
    assert any('media' in case['expected_render_blocks'] for case in data['cases'])
    assert any(case.get('turns') for case in data['cases'])


def test_interview_confirmation_case_uses_render_time_placeholder() -> None:
    data = yaml.safe_load(CASES_PATH.read_text(encoding='utf-8'))
    case = next(item for item in data['cases'] if item['id'] == 'confirmed_interview_schedule_from_workset')

    assert '{schedule_at}' in case['question']
    assert '{schedule_at}' in case['preparation_question']
    assert any('{schedule_at}' in turn.get('question', '') for turn in case['preparation_turns'])


def test_confirmation_flow_assessment_requires_real_execution_evidence() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'confirmed_attendance_notification_execution',
        'expected_modules': ['employees', 'attendance_records', 'attendance_stats', 'notifications'],
        'expected_render_blocks': ['markdown', 'table', 'confirmation', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'root_cause_dimensions': ['audit_confirmation', 'tool_calling', 'data_retrieval', 'module_relationship'],
    }
    response = {
        'summary': '已生成提醒草稿。',
        'widgets': [{'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'confirmation'}],
        'copilot': {'evidence': [{'module': 'notifications', 'title': '确认后写入通知中心'}]},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['attendance_analysis']},
        'confirmationFlow': {
            'actionId': 'act-1',
            'confirmed': False,
            'wroteBeforeConfirmation': False,
            'createdNotifications': [],
            'pendingConsumed': False,
            'duplicateResponse': {},
            'duplicateCreatedNotifications': [],
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    assert 'audit_confirmation' in result['failureCategories']
    assert any(item['type'] == 'confirmation' for item in result['missingExpectations'])
    assert any(item['type'] == 'modules' and 'notifications_write' in item['missing'] for item in result['missingExpectations'])


def test_approval_confirmation_flow_assessment_requires_business_and_audit_writes() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'confirmed_approval_decision_execution',
        'expected_modules': ['approvals', 'leave_requests', 'operation_logs'],
        'expected_render_blocks': ['markdown', 'table', 'confirmation', 'status', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'confirmation_flow_type': 'approval',
        'root_cause_dimensions': ['audit_confirmation', 'tool_calling', 'module_relationship'],
    }
    response = {
        'summary': '准备审批通过。',
        'widgets': [{'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'confirmation'}],
        'copilot': {'evidence': [{'module': 'approvals', 'title': '审批'}]},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['approval_decision']},
        'confirmationFlow': {
            'flowType': 'approval',
            'actionId': 'act-1',
            'confirmed': True,
            'wroteBeforeConfirmation': False,
            'approvalStatus': 'pending',
            'businessStatus': 'pending',
            'createdApprovalRecords': [],
            'createdOperationLogs': 0,
            'pendingConsumed': False,
            'duplicateResponse': {},
            'duplicateCreatedApprovalRecords': 0,
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    missing = result['missingExpectations']
    assert any(item['type'] == 'modules' and 'approval_business_write' in item['missing'] for item in missing)
    assert any(item['type'] == 'modules' and 'approval_record_write' in item['missing'] for item in missing)
    assert any(item['type'] == 'audit' and 'operation_log_write' in item['missing'] for item in missing)


def test_approval_rejection_confirmation_flow_accepts_rejected_business_state() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'confirmed_approval_rejection_execution',
        'expected_modules': ['approvals', 'leave_requests', 'operation_logs'],
        'expected_render_blocks': ['markdown', 'table', 'confirmation', 'status', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'confirmation_flow_type': 'approval',
        'expected_approval_action': 'reject',
        'expected_approval_status': 'rejected',
        'expected_business_status': 'rejected',
        'root_cause_dimensions': ['audit_confirmation', 'tool_calling', 'module_relationship'],
    }
    response = {
        'summary': '准备审批驳回。已执行：审批驳回。没有找到可执行的待确认动作，可能已完成或已过期。',
        'widgets': [
            {'type': 'data_table', 'table': {'rows': [{'id': 'ap-1'}]}},
            {'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]},
            {'type': 'status_badges', 'items': [{'label': '审批已驳回', 'status': 'ok'}]},
            {'type': 'source_citations', 'sources': [
                {'module': 'approvals', 'recordId': 'ap-1'},
                {'module': 'leave_requests', 'recordId': 'leave-1'},
                {'module': 'operation_logs', 'recordId': 'ap-1'},
            ]},
        ],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'confirmation'}, {'kind': 'status'}, {'kind': 'sources'}],
        'copilot': {'evidence': [
            {'module': 'approvals', 'recordId': 'ap-1'},
            {'module': 'leave_requests', 'recordId': 'leave-1'},
            {'module': 'operation_logs', 'recordId': 'ap-1'},
        ]},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['approval_decision']},
        'confirmationFlow': {
            'flowType': 'approval',
            'actionId': 'act-1',
            'confirmed': True,
            'wroteBeforeConfirmation': False,
            'expectedAction': 'reject',
            'expectedApprovalStatus': 'rejected',
            'expectedBusinessStatus': 'rejected',
            'approvalStatus': 'rejected',
            'businessStatus': 'rejected',
            'createdApprovalRecords': [{'id': 'record-1', 'action': 'rejected'}],
            'createdOperationLogs': 1,
            'pendingConsumed': True,
            'duplicateResponse': {'summary': '没有找到可执行的待确认动作，可能已完成或已过期。'},
            'duplicateCreatedApprovalRecords': 0,
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'pass'
    assert result['missingExpectations'] == []


def test_interview_confirmation_flow_assessment_requires_interview_write_and_duplicate_block() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'confirmed_interview_schedule_from_workset',
        'expected_modules': ['jobs', 'candidates', 'resumes', 'interviews'],
        'expected_render_blocks': ['markdown', 'matrix', 'table', 'entity_cards', 'workset', 'confirmation', 'status', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'confirmation_flow_type': 'interview',
        'root_cause_dimensions': ['entity_resolution', 'audit_confirmation', 'tool_calling', 'module_relationship'],
    }
    response = {
        'summary': '准备安排面试。确认执行后已创建面试。没有找到可执行的待确认动作，可能已完成或已过期。',
        'entities': [
            {'type': 'job', 'id': 'job-1', 'title': '电子工程师'},
            {'type': 'candidate', 'id': 'cand-2', 'title': '杨琳'},
            {'type': 'resume', 'id': 'resume-2', 'title': '杨琳'},
        ],
        'widgets': [
            {'type': 'comparison_matrix', 'rows': []},
            {'type': 'table', 'table': {'rows': []}},
            {'type': 'workset_summary', 'workset': {'items': [{'title': '杨琳', 'rank': 2}]}},
            {'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]},
            {'type': 'status_badges', 'items': [{'label': '面试记录已创建', 'status': 'ok'}]},
            {'type': 'source_citations', 'sources': [
                {'module': 'jobs', 'recordId': 'job-1'},
                {'module': 'candidates', 'recordId': 'cand-2'},
                {'module': 'resumes', 'recordId': 'resume-2'},
                {'module': 'interviews', 'recordId': 'interview-1'},
            ]},
        ],
        'renderBlocks': [
            {'kind': 'markdown'}, {'kind': 'matrix'}, {'kind': 'table'}, {'kind': 'entity_cards'},
            {'kind': 'workset'}, {'kind': 'confirmation'}, {'kind': 'status'}, {'kind': 'sources'},
        ],
        'copilot': {'evidence': [
            {'module': 'jobs', 'recordId': 'job-1'},
            {'module': 'candidates', 'recordId': 'cand-2'},
            {'module': 'resumes', 'recordId': 'resume-2'},
            {'module': 'interviews', 'recordId': 'interview-1'},
        ]},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['recruitment_match_matrix', 'interview_create']},
        'confirmationFlow': {
            'flowType': 'interview',
            'actionId': 'act-1',
            'confirmed': True,
            'wroteBeforeConfirmation': False,
            'createdInterviews': [{'id': 'interview-1', 'resumeId': 'resume-2', 'jobId': 'job-1'}],
            'pendingConsumed': True,
            'duplicateResponse': {'summary': '没有找到可执行的待确认动作，可能已完成或已过期。'},
            'duplicateCreatedInterviews': 0,
        },
        'conversationFlow': {'turnCount': 2},
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'pass'
    assert result['missingExpectations'] == []


def test_confirmation_flow_merge_preserves_multi_turn_preparation_render_blocks() -> None:
    from services.assistant_core.evaluation import _merge_flow_response, assess_response

    case = {
        'id': 'confirmed_interview_schedule_from_workset',
        'expected_modules': ['jobs', 'candidates', 'resumes', 'interviews'],
        'expected_render_blocks': ['markdown', 'matrix', 'table', 'entity_cards', 'workset', 'confirmation', 'status', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'confirmation_flow_type': 'interview',
        'root_cause_dimensions': ['entity_resolution', 'audit_confirmation', 'tool_calling', 'module_relationship'],
    }
    prepare_first = {
        'summary': '电子工程师候选人对比矩阵。',
        'entities': [
            {'type': 'job', 'id': 'job-1', 'title': '电子工程师'},
            {'type': 'candidate', 'id': 'cand-2', 'title': '杨琳'},
            {'type': 'resume', 'id': 'resume-2', 'title': '杨琳'},
        ],
        'widgets': [
            {'type': 'comparison_matrix', 'rows': [{'candidate': '杨琳'}]},
            {'type': 'table', 'table': {'rows': [{'candidate': '杨琳'}]}},
            {'type': 'entity_cards', 'items': [{'id': 'cand-2', 'title': '杨琳'}]},
            {'type': 'workset_summary', 'workset': {'items': [{'entity_id': 'cand-2', 'rank': 2, 'title': '杨琳'}]}},
            {'type': 'source_citations', 'sources': [
                {'module': 'jobs', 'recordId': 'job-1'},
                {'module': 'candidates', 'recordId': 'cand-2'},
                {'module': 'resumes', 'recordId': 'resume-2'},
            ]},
        ],
        'copilot': {'evidence': [
            {'module': 'jobs', 'recordId': 'job-1'},
            {'module': 'candidates', 'recordId': 'cand-2'},
            {'module': 'resumes', 'recordId': 'resume-2'},
        ]},
        'meta': {'usedSkills': ['recruitment_match_matrix']},
    }
    prepare_second_core = {
        'summary': '安排面试：杨琳；时间：2026-06-03 15:00。确认后将在系统中创建记录。',
        'entities': prepare_first['entities'],
        'widgets': [{'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]}],
        'copilot': {'evidence': prepare_first['copilot']['evidence']},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['candidate_evidence_bundle']},
    }
    prepare_second = {
        **prepare_second_core,
        '_preparationResponses': [prepare_first, prepare_second_core],
    }

    merged = _merge_flow_response(
        prepare_second,
        {
            'summary': '已执行：安排面试，成功 1/1 项。',
            'sessionId': 'session-1',
            'entities': [{'type': 'interview', 'id': 'interview-1', 'title': '杨琳 - 电子工程师'}],
            'meta': {'usedSkills': ['interview_create']},
        },
        {'summary': '没有找到可执行的待确认动作，可能已完成或已过期。'},
        action_payload='确认执行动作：act-1',
        action_id='act-1',
        wrote_before_confirmation=False,
        created_notifications=[],
        pending_consumed=True,
        duplicate_created_notifications=[],
        confirmed_write_label='确认后已创建面试',
        confirmed_write_ok=True,
    )
    merged['copilot']['evidence'].append({'module': 'interviews', 'recordId': 'interview-1'})
    merged['confirmationFlow'].update({
        'flowType': 'interview',
        'createdInterviews': [{'id': 'interview-1', 'resumeId': 'resume-2', 'jobId': 'job-1'}],
        'duplicateCreatedInterviews': 0,
    })

    result = assess_response(case, merged)

    assert {'matrix', 'table', 'workset', 'confirmation', 'status', 'sources'} <= set(result['actualRenderBlocks'])
    assert result['passStatus'] == 'pass'
    assert result['missingExpectations'] == []


def test_interview_confirmation_flow_fails_without_created_interview() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'confirmed_interview_schedule_from_workset',
        'expected_modules': ['jobs', 'candidates', 'resumes', 'interviews'],
        'expected_render_blocks': ['markdown', 'confirmation', 'status', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'confirmation_flow_type': 'interview',
        'root_cause_dimensions': ['audit_confirmation', 'tool_calling', 'module_relationship'],
    }
    response = {
        'summary': '准备安排面试。',
        'widgets': [{'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'confirmation'}],
        'copilot': {'evidence': [{'module': 'interviews', 'title': '面试'}]},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['recruitment_match_matrix']},
        'confirmationFlow': {
            'flowType': 'interview',
            'actionId': 'act-1',
            'confirmed': True,
            'wroteBeforeConfirmation': False,
            'createdInterviews': [],
            'pendingConsumed': False,
            'duplicateResponse': {'summary': ''},
            'duplicateCreatedInterviews': 1,
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    missing = result['missingExpectations']
    assert any(item['type'] == 'modules' and 'interviews_write' in item['missing'] for item in missing)
    assert any(item['type'] == 'confirmation' and 'pending_action_consumed' in item['missing'] for item in missing)
    assert any(item['type'] == 'audit' and 'duplicate_confirmation_blocked' in item['missing'] for item in missing)


def test_employee_change_confirmation_flow_assessment_requires_change_approval_audit_and_no_direct_update() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'confirmed_employee_change_submission_execution',
        'expected_modules': ['employees', 'departments', 'employee_changes', 'approvals', 'operation_logs'],
        'expected_render_blocks': ['markdown', 'table', 'confirmation', 'status', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'confirmation_flow_type': 'employee_change',
        'root_cause_dimensions': ['audit_confirmation', 'tool_calling', 'module_relationship'],
    }
    response = {
        'summary': '准备提交员工异动。',
        'widgets': [{'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'confirmation'}],
        'copilot': {'evidence': [{'module': 'employees', 'title': '员工'}]},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['employee_change_submit']},
        'confirmationFlow': {
            'flowType': 'employee_change',
            'actionId': 'act-1',
            'confirmed': True,
            'wroteBeforeConfirmation': False,
            'createdEmployeeChanges': [],
            'createdApprovals': [],
            'createdOperationLogs': 0,
            'directEmployeeUpdate': True,
            'pendingConsumed': False,
            'duplicateResponse': {},
            'duplicateCreatedEmployeeChanges': 0,
            'duplicateCreatedApprovals': 0,
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    missing = result['missingExpectations']
    assert any(item['type'] == 'modules' and 'employee_change_write' in item['missing'] for item in missing)
    assert any(item['type'] == 'modules' and 'employee_change_approval_write' in item['missing'] for item in missing)
    assert any(item['type'] == 'audit' and 'operation_log_write' in item['missing'] for item in missing)
    assert any(item['type'] == 'confirmation' and 'no_direct_employee_update_before_approval' in item['missing'] for item in missing)


def test_salary_adjustment_confirmation_flow_requires_salary_change_and_no_direct_salary_update() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'confirmed_salary_adjustment_submission_execution',
        'expected_modules': ['employees', 'salary_profiles', 'performance_reviews', 'employee_changes', 'approvals', 'operation_logs', 'notifications'],
        'expected_render_blocks': ['markdown', 'kpi', 'table', 'timeline', 'status', 'confirmation', 'sources'],
        'requires_confirmation': True,
        'confirmation_flow': True,
        'confirmation_flow_type': 'salary_adjustment',
        'root_cause_dimensions': ['audit_confirmation', 'tool_calling', 'module_relationship'],
    }
    response = {
        'summary': '准备提交调薪异动。',
        'widgets': [
            {'type': 'metrics', 'metrics': [{'label': '调薪金额', 'value': 1800}]},
            {'type': 'table', 'table': {'rows': [{'module': '薪资档案'}]}},
            {'type': 'timeline', 'items': [{'title': '确认后'}]},
            {'type': 'status_badges', 'items': [{'label': '薪资档案未直接变更', 'status': 'error'}]},
            {'type': 'confirmation_card', 'actions': [{'payload': '确认执行动作：act-1'}]},
            {'type': 'source_citations', 'sources': [
                {'module': 'employees', 'recordId': 'emp-1'},
                {'module': 'salary_profiles', 'recordId': 'sp-1'},
                {'module': 'performance_reviews', 'recordId': 'pr-1'},
                {'module': 'employee_changes', 'recordId': 'chg-1'},
                {'module': 'approvals', 'recordId': 'ap-1'},
                {'module': 'operation_logs', 'recordId': 'chg-1'},
                {'module': 'notifications', 'recordId': 'notice-1'},
            ]},
        ],
        'renderBlocks': [{'kind': 'markdown'}],
        'copilot': {'evidence': [
            {'module': 'employees'}, {'module': 'salary_profiles'}, {'module': 'performance_reviews'},
            {'module': 'employee_changes'}, {'module': 'approvals'}, {'module': 'operation_logs'}, {'module': 'notifications'},
        ]},
        'meta': {'requiresConfirmation': True, 'usedSkills': ['employee_salary_adjustment_impact', 'employee_change_submit']},
        'confirmationFlow': {
            'flowType': 'salary_adjustment',
            'actionId': 'act-1',
            'confirmed': True,
            'wroteBeforeConfirmation': False,
            'createdEmployeeChanges': [{'id': 'chg-1', 'changeType': 'transfer'}],
            'createdApprovals': [{'id': 'ap-1'}],
            'createdOperationLogs': 1,
            'createdSalaryAdjustment': False,
            'expectedSalaryAdjustment': '1800',
            'createdSalaryAdjustmentAmounts': ['800'],
            'salaryAdjustmentAmountMatches': False,
            'directEmployeeUpdate': False,
            'directSalaryUpdate': True,
            'pendingConsumed': True,
            'duplicateResponse': {'summary': '没有找到可执行的待确认动作，可能已完成或已过期。'},
            'duplicateCreatedEmployeeChanges': 0,
            'duplicateCreatedApprovals': 0,
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    missing = result['missingExpectations']
    assert any(item['type'] == 'modules' and 'salary_adjustment_change_write' in item['missing'] for item in missing)
    assert any(item['type'] == 'data_retrieval' and 'salary_adjustment_amount_match' in item['missing'] for item in missing)
    assert any(item['type'] == 'confirmation' and 'no_direct_salary_update_before_approval' in item['missing'] for item in missing)


def test_copilot_evaluation_assessor_records_structural_gaps() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'attendance_top_notify',
        'question': '帮我给本月迟到最多的5个人生成提醒',
        'expected_modules': ['employees', 'attendance_records', 'notifications'],
        'expected_render_blocks': ['markdown', 'table', 'confirmation', 'sources'],
        'requires_confirmation': True,
        'root_cause_dimensions': ['data_retrieval', 'audit_confirmation', 'frontend_rendering'],
    }
    response = {
        'summary': '本月迟到最多的是张三。',
        'entities': [{'id': 'emp-1', 'type': 'employees', 'title': '张三'}],
        'widgets': [],
        'meta': {'requiresConfirmation': False, 'usedSkills': ['employee_search']},
        'copilot': {'evaluationHints': {'failureCategories': []}},
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    assert {'data_retrieval', 'audit_confirmation', 'frontend_rendering'} & set(result['failureCategories'])
    assert any(item['type'] == 'confirmation' for item in result['missingExpectations'])
    assert any(item['type'] == 'renderBlocks' for item in result['missingExpectations'])


def test_expected_skill_is_a_hard_evaluation_gate() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'skill_gate_case',
        'expected_skill': 'payroll.anomaly',
        'expected_modules': ['payroll_records'],
        'expected_render_blocks': ['markdown'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['intent_recognition', 'tool_calling'],
    }
    response = {
        'summary': '工资异常分析完成。',
        'renderBlocks': [{'kind': 'markdown'}],
        'copilot': {
            'routeTrace': {
                'selected_skill': 'employee.profile',
            },
            'evidence': [{'module': 'payroll_records', 'recordId': 'payroll-1'}],
        },
        'meta': {
            'routeDecision': {'intent': 'employee.profile'},
            'usedSkills': ['payroll_analysis'],
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    assert result['actualSelectedSkill'] == 'employee.profile'
    assert {'intent_recognition', 'tool_calling'} <= set(result['failureCategories'])
    assert any(
        item['type'] == 'skill'
        and 'expected_skill:payroll.anomaly' in item['missing']
        and item['actual'] == 'employee.profile'
        for item in result['missingExpectations']
    )


def test_expected_turn_skills_gate_multi_turn_kernel_selection() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'turn_skill_gate_case',
        'expected_turn_skills': ['candidate.resume_analysis', 'candidate.evaluation'],
        'expected_modules': ['candidates'],
        'expected_render_blocks': ['markdown'],
        'expect_conversation_turns': 2,
        'requires_confirmation': False,
        'root_cause_dimensions': ['intent_recognition', 'entity_resolution'],
    }
    response = {
        'summary': '第 1 轮：简历。第 2 轮：评估。',
        'renderBlocks': [{'kind': 'markdown'}],
        'copilot': {'evidence': [{'module': 'candidates', 'recordId': 'cand-1'}]},
        'conversationFlow': {
            'turnCount': 2,
            'turns': [
                {'index': 1, 'selectedSkill': 'candidate.resume_analysis'},
                {'index': 2, 'selectedSkill': 'recruitment.open_jobs'},
            ],
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    assert result['actualTurnSkills'] == ['candidate.resume_analysis', 'recruitment.open_jobs']
    assert any(
        item['type'] == 'skill'
        and 'expected_turn_2_skill:candidate.evaluation' in item['missing']
        for item in result['missingExpectations']
    )


def test_expected_permission_denied_case_can_pass_without_source_links() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'payroll_permission_denied_employee',
        'expected_modules': ['payroll_records'],
        'expected_render_blocks': ['markdown', 'notice'],
        'expected_error_code': 'permission_denied',
        'forbidden_patterns': [r'(工资|薪资).{0,12}\d{4,}'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['permission_policy', 'response_composition'],
    }
    response = {
        'summary': '权限不足，当前角色不能查询他人的工资条。',
        'widgets': [{'type': 'warning', 'level': 'danger', 'message': '权限不足'}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'notice'}],
        'meta': {
            'routeDecision': {
                'taskType': 'forbidden',
                'safetyFlags': ['permission_denied'],
            },
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'pass'
    assert result['missingExpectations'] == []


def test_permission_denied_task_template_counts_as_expected_error_code() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'payroll_permission_denied_employee',
        'expected_modules': ['payroll_records'],
        'expected_render_blocks': ['markdown', 'notice'],
        'expected_error_code': 'permission_denied',
        'required_patterns': ['权限|无权|不能|无法|不允许'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['permission_policy', 'response_composition'],
    }
    response = {
        'summary': '权限不足：当前角色无权查看薪酬数据明细，无法继续查询。',
        'widgets': [{'type': 'warning', 'level': 'danger', 'message': '权限不足'}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'notice'}],
        'meta': {
            'taskTemplateId': 'permission_denied_response',
            'routeDecision': {
                'taskTemplateId': 'permission_denied_response',
                'taskType': 'forbidden',
            },
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'pass'
    assert result['missingExpectations'] == []


def test_sensitive_leak_in_permission_case_fails_structurally() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'payroll_permission_denied_employee',
        'expected_modules': ['payroll_records'],
        'expected_render_blocks': ['markdown', 'notice'],
        'expected_error_code': 'permission_denied',
        'forbidden_patterns': [r'(工资|薪资).{0,12}\d{4,}'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['permission_policy', 'response_composition'],
    }
    response = {
        'summary': '权限不足，但张三工资 30000。',
        'widgets': [{'type': 'warning', 'level': 'danger', 'message': '权限不足'}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'notice'}],
        'meta': {
            'routeDecision': {
                'taskType': 'forbidden',
                'safetyFlags': ['permission_denied'],
            },
        },
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'fail'
    assert 'permission_policy' in result['failureCategories']
    assert any(item['type'] == 'permission' and 'sensitive_text_leak' in item['missing'] for item in result['missingExpectations'])


def test_field_level_evidence_requirements_are_hard_evaluation_gates() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'field_gate_case',
        'expected_modules': ['employees', 'performance_reviews'],
        'expected_render_blocks': ['markdown', 'sources'],
        'min_field_evidence_count': 3,
        'expected_field_evidence_modules': ['employees', 'performance_reviews'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['data_retrieval', 'response_composition'],
    }
    response = {
        'summary': '绩效分析完成。',
        'widgets': [{'type': 'source_citations', 'sources': [
            {'module': 'employees', 'recordId': 'emp-1', 'fields': [
                {'key': 'employee.department', 'label': '部门', 'value': '研发部'},
            ]},
            {'module': 'performance_reviews', 'recordId': 'pr-1'},
        ]}],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'sources'}],
        'copilot': {'evidence': [
            {'module': 'employees', 'recordId': 'emp-1', 'fields': [
                {'key': 'employee.department', 'label': '部门', 'value': '研发部'},
            ]},
            {'module': 'performance_reviews', 'recordId': 'pr-1'},
        ]},
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'needs_review'
    assert {'data_retrieval', 'response_composition'} <= set(result['failureCategories'])
    assert any(
        item['type'] == 'field_evidence'
        and 'field_evidence_count:3' in item['missing']
        and item['actual'] == 1
        for item in result['missingExpectations']
    )
    assert any(
        item['type'] == 'field_evidence'
        and 'performance_reviews' in item['missing']
        for item in result['missingExpectations']
    )


def test_media_preview_widget_counts_as_media_render_block() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'resume_media_preview_denghao',
        'expected_modules': ['candidates', 'resumes'],
        'expected_render_blocks': ['markdown', 'media'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['frontend_rendering', 'data_retrieval'],
    }
    response = {
        'summary': '邓浩简历附件如下。',
        'entities': [{'type': 'candidate', 'id': 'cand-1', 'title': '邓浩'}],
        'widgets': [
            {'type': 'media_preview', 'items': [{'title': '邓浩 简历附件', 'url': '/uploads/demo-denghao.pdf'}]},
            {'type': 'source_citations', 'sources': [{'module': 'resumes', 'title': '邓浩简历'}]},
        ],
        'meta': {'usedSkills': ['candidate_evidence_bundle']},
    }

    result = assess_response(case, response)

    assert 'media' in result['actualRenderBlocks']
    assert result['passStatus'] == 'pass'


def test_model_settings_trace_rejects_general_company_setting_as_false_green() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'system_model_settings_trace',
        'expected_modules': ['system_settings'],
        'expected_render_blocks': ['markdown', 'table', 'entity_cards', 'sources'],
        'required_patterns': ['assistantModelSettings', '/ai-model-settings|AI 模型管理'],
        'forbidden_patterns': ['companyName'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['data_retrieval', 'module_relationship'],
    }
    response = {
        'summary': '系统检索命中 1 条：AI 模型配置1条（配置键：companyName）',
        'entities': [{'type': 'model_setting', 'id': 'companyName', 'title': 'companyName', 'url': '/ai-model-settings'}],
        'widgets': [
            {'type': 'table', 'table': {'rows': [{'key': 'companyName', 'category': 'AI 模型配置'}]}},
            {'type': 'source_citations', 'sources': [{'module': 'system_settings', 'recordId': 'companyName', 'url': '/ai-model-settings'}]},
        ],
        'renderBlocks': [{'kind': 'markdown'}, {'kind': 'table'}, {'kind': 'entity_cards'}, {'kind': 'sources'}],
        'copilot': {'evidence': [{'module': 'system_settings', 'recordId': 'companyName', 'url': '/ai-model-settings'}]},
        'meta': {'usedSkills': ['system_search']},
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'fail'
    assert any(item['type'] == 'permission' and 'sensitive_text_leak' in item['missing'] for item in result['missingExpectations'])
    assert any(item['type'] == 'response' and 'assistantModelSettings' in item['missing'] for item in result['missingExpectations'])


def test_recruitment_workset_followup_rejects_roman_as_second_rank_false_green() -> None:
    from services.assistant_core.evaluation import assess_response

    case = {
        'id': 'recruitment_workset_followup_second_candidate',
        'expected_modules': ['jobs', 'candidates', 'resumes', 'interviews'],
        'expected_render_blocks': ['markdown', 'matrix', 'table', 'entity_cards', 'workset', 'actions', 'sources'],
        'expect_conversation_turns': 2,
        'required_patterns': ['第二|杨琳|风险|下一步|推进', '杨琳'],
        'forbidden_patterns': [r'第\s*2\s*(?:名|位|个)?.{0,30}罗伟|罗伟.{0,30}第\s*2\s*(?:名|位|个)?'],
        'requires_confirmation': False,
        'root_cause_dimensions': ['entity_resolution', 'module_relationship'],
    }
    response = {
        'summary': '第 1 轮：邓浩第一。第 2 轮：罗伟作为第 2 名候选人，风险是独立设计经验不足，下一步推进技术加试。',
        'entities': [
            {'type': 'job', 'id': 'job-1', 'title': '电子工程师'},
            {'type': 'candidate', 'id': 'c-luowei', 'title': '罗伟'},
        ],
        'widgets': [
            {'type': 'comparison_matrix', 'rows': []},
            {'type': 'table', 'table': {'rows': []}},
            {'type': 'workset_summary', 'workset': {'items': [{'title': '罗伟', 'rank': 2}]}},
            {'type': 'follow_up_actions', 'actions': [{'label': '安排面试', 'payload': '给罗伟安排明天下午三点面试'}]},
            {'type': 'source_citations', 'sources': [{'module': 'candidates', 'recordId': 'c-luowei'}]},
        ],
        'renderBlocks': [
            {'kind': 'markdown'}, {'kind': 'matrix'}, {'kind': 'table'},
            {'kind': 'entity_cards'}, {'kind': 'workset'}, {'kind': 'actions'}, {'kind': 'sources'},
        ],
        'copilot': {'evidence': [{'module': 'candidates', 'recordId': 'c-luowei'}]},
        'meta': {'usedSkills': ['recruitment_match_matrix', 'candidate_evidence_bundle']},
        'conversationFlow': {'turnCount': 2},
    }

    result = assess_response(case, response)

    assert result['passStatus'] == 'fail'
    assert any(item['type'] == 'response' and '杨琳' in item['missing'] for item in result['missingExpectations'])
    assert any(item['type'] == 'permission' and item.get('matches') for item in result['missingExpectations'])


def test_real_model_audit_failure_prevents_green_evaluation_result() -> None:
    from services.assistant_core.evaluation import _apply_model_audit_gate

    assessment = {
        'passStatus': 'pass',
        'failureCategories': [],
        'missingExpectations': [],
        'rootCauseNotes': '通过基础契约校验；仍需人工抽样判断业务结论质量。',
        'fixPlan': '无需结构性修复；建议保留为回归样本。',
    }
    model_audit = {
        'requestId': 'eval-case-timeout',
        'ok': False,
        'status': 'timeout',
        'error': 'request timeout',
        'auditRecorded': True,
    }

    result = _apply_model_audit_gate(assessment, model_audit)

    assert result['passStatus'] == 'fail'
    assert {'audit_confirmation', 'tool_calling'} <= set(result['failureCategories'])
    assert any(
        item['type'] == 'model_audit'
        and 'copilot_evaluation_success_audit' in item['missing']
        and item['status'] == 'timeout'
        for item in result['missingExpectations']
    )


def test_real_model_audit_success_keeps_evaluation_assessment_green() -> None:
    from services.assistant_core.evaluation import _apply_model_audit_gate

    assessment = {
        'passStatus': 'pass',
        'failureCategories': [],
        'missingExpectations': [],
        'rootCauseNotes': '通过基础契约校验；仍需人工抽样判断业务结论质量。',
        'fixPlan': '无需结构性修复；建议保留为回归样本。',
    }
    model_audit = {
        'requestId': 'eval-case-success',
        'ok': True,
        'status': 'success',
        'auditRecorded': True,
        'auditLogId': 'audit-success-1',
        'provider': 'siliconflow',
        'useCase': 'copilot_evaluation',
    }

    assert _apply_model_audit_gate(assessment, model_audit) == assessment


def test_model_audit_gate_rejects_non_siliconflow_or_incomplete_audit() -> None:
    from services.assistant_core.evaluation import _apply_model_audit_gate

    assessment = {
        'passStatus': 'pass',
        'failureCategories': [],
        'missingExpectations': [],
        'rootCauseNotes': '通过基础契约校验；仍需人工抽样判断业务结论质量。',
        'fixPlan': '无需结构性修复；建议保留为回归样本。',
    }
    model_audit = {
        'requestId': 'eval-case-fake-green',
        'ok': True,
        'status': 'success',
        'auditRecorded': True,
        'auditLogId': '',
        'provider': 'mock',
        'useCase': 'model_call_test',
    }

    result = _apply_model_audit_gate(assessment, model_audit)

    assert result['passStatus'] == 'fail'
    missing = next(item for item in result['missingExpectations'] if item['type'] == 'model_audit')
    assert 'siliconflow_provider_audit' in missing['missing']
    assert 'copilot_evaluation_use_case' in missing['missing']
    assert 'assistant_audit_log_id' in missing['missing']


def test_evaluation_run_dict_exposes_real_model_audit_gate() -> None:
    from datetime import datetime

    from models import AssistantEvaluationRun

    row = AssistantEvaluationRun(
        id='run-1',
        case_id='attendance_employee_anomaly',
        question='吴明华最近考勤异常吗？请给证据',
        scenario='考勤异常分析',
        user_id='admin-1',
        session_id='session-1',
        request_id='eval-attendance_employee_anomaly-real',
        expected_modules=['employees', 'attendance_records'],
        expected_render_blocks=['markdown', 'sources'],
        expected_behavior=['真实运行并写入模型审计'],
        actual_modules=['employees', 'attendance_records'],
        actual_render_blocks=['markdown', 'sources'],
        used_tools=['employee_attendance_profile'],
        evidence_sources=[{'module': 'employees', 'recordId': 'emp-1'}],
        entity_summary=[{'type': 'employee', 'title': '吴明华'}],
        time_range={'label': '最近'},
        response_summary='通过',
        pass_status='pass',
        failure_categories=[],
        missing_expectations=[],
        root_cause_notes='通过真实硅基流动评估审计。',
        fix_plan='保留为回归样本。',
        response_payload={
            'evaluationAudit': {
                'requestId': 'eval-attendance_employee_anomaly-real',
                'useCase': 'copilot_evaluation',
                'modelProfile': 'strong',
                'model': 'deepseek-ai/DeepSeek-V4-Pro',
                'status': 'success',
                'ok': True,
                'auditRecorded': True,
                'auditLogId': 'audit-1',
            },
        },
        created_at=datetime.utcnow(),
    )

    payload = row.to_dict()

    assert payload['passStatus'] == 'pass'
    assert payload['evaluationAudit']['useCase'] == 'copilot_evaluation'
    assert payload['evaluationAudit']['status'] == 'success'
    assert payload['evaluationAudit']['ok'] is True
    assert payload['evaluationAudit']['model'] == 'deepseek-ai/DeepSeek-V4-Pro'
