from services.assistant_core import skill_registry
from services.assistant_core.schemas import AssistantContext
from services.assistant_core.skills import skill_system_search
from services.hrm_module_catalog import all_module_specs, module_by_id, module_catalog_payload, resource_module_ids


def test_catalog_covers_sidebar_modules_and_ai_skills():
    specs = all_module_specs()
    assert len(specs) == 36
    assert len({spec.id for spec in specs}) == len(specs)
    assert len({spec.label for spec in specs}) == len(specs)

    for spec in specs:
        assert spec.group
        assert spec.path.startswith('/')
        assert spec.ai_skill
        assert skill_registry.exists(spec.ai_skill)


def test_catalog_maps_backend_resources_to_modules():
    resource_map = resource_module_ids()
    expected_resources = {
        'departments',
        'positions',
        'candidates',
        'offers',
        'employees',
        'onboarding-tasks',
        'probations',
        'employee-changes',
        'resignations',
        'contracts',
        'attendance-records',
        'employee-requests',
        'performance-cycles',
        'performance-templates',
        'performance-reviews',
        'salary-profiles',
        'payroll-records',
        'training-courses',
        'training-plans',
        'training-records',
        'users',
        'roles',
        'notifications',
        'feedbacks',
        'operation-logs',
    }

    assert expected_resources.issubset(set(resource_map))
    assert resource_map['offers'] == 'offers'
    assert resource_map['feedbacks'] == 'feedback'
    assert resource_map['payroll-records'] == 'payroll-records'


def test_catalog_exposes_cross_module_flows_and_open_source_benchmarks():
    payload = module_catalog_payload()
    benchmark_names = {item['name'] for item in payload['benchmarks']}

    assert len(payload['modules']) == 36
    assert {flow['id'] for flow in payload['flows']} >= {
        'recruit_to_onboard',
        'employee_lifecycle',
        'attendance_to_payroll',
        'performance_to_growth',
        'performance_to_compensation',
        'workflow_governance',
    }
    assert benchmark_names >= {
        'Frappe HRMS',
        'Horilla',
        'OrangeHRM',
        'IceHrm',
        'TimeOff.Management',
        'Sentrifugo',
        'Jorani',
    }
    assert len(payload['benchmarks']) >= 7
    for item in payload['benchmarks']:
        assert item['githubRepo'].startswith('https://github.com/')
        assert item['stars'] >= 100
        assert item['focusModules']
        assert item['appliedPatterns']

    offers = next(module for module in payload['modules'] if module['id'] == 'offers')
    assert 'employees' in offers['downstream']
    assert 'onboarding-tasks' in offers['downstream']
    assert offers['aiSkill'] == 'recruitment_search'


def test_system_search_module_catalog_overview_is_catalog_backed():
    result = skill_system_search(
        {'module': 'module_catalog', 'view': 'overview'},
        AssistantContext(user_id='u-catalog', role='hr_admin', session_id='s-catalog'),
    )

    assert result['rows_count'] == 36
    assert result['facts']['module'] == 'module_catalog'
    assert result['facts']['view'] == 'overview'
    assert result['facts']['moduleCount'] == 36
    assert len(result['facts']['benchmarks']) >= 7
    assert result['entities'][0]['type'] == 'hrm_module'
    assert '系统共覆盖 36 个 HRM 模块' in result['summary_hint']
    assert 'Frappe HRMS' in result['summary_hint']
    assert 'OrangeHRM' in result['summary_hint']
    assert 'Sentrifugo' in result['summary_hint']
    assert '招聘到入职：岗位管理 -> 简历管理 -> 候选人管理 -> 面试管理 -> Offer管理 -> 员工档案 -> 入职管理 -> 合同管理' in result['summary_hint']


def test_system_search_module_catalog_module_detail_explains_connections():
    result = skill_system_search(
        {'module': 'module_catalog', 'view': 'module', 'module_id': 'offers'},
        AssistantContext(user_id='u-catalog', role='hr_admin', session_id='s-catalog'),
    )

    assert result['rows_count'] == 1
    assert result['facts']['module'] == 'module_catalog'
    assert result['facts']['view'] == 'module'
    assert result['facts']['moduleId'] == 'offers'
    assert result['entities'][0]['title'] == 'Offer管理'
    assert 'Offer管理位于招聘管理' in result['summary_hint']
    assert '上游：候选人管理、面试管理' in result['summary_hint']
    assert '下游：员工档案、入职管理、薪资档案' in result['summary_hint']
    assert 'offer_approval' in result['summary_hint']


def test_employee_changes_connect_approval_and_payroll_governance():
    employee_changes = module_by_id('employee-changes')
    approvals_pending = module_by_id('approvals-pending')
    salary_profiles = module_by_id('salary-profiles')

    assert employee_changes is not None
    assert approvals_pending is not None
    assert salary_profiles is not None
    assert 'approvals-pending' in employee_changes.downstream
    assert 'salary-profiles' in employee_changes.downstream
    assert 'payroll-records' in employee_changes.downstream
    assert 'employee-changes' in approvals_pending.upstream
    assert 'employee-changes' in salary_profiles.upstream
    assert 'approval before payroll impact' in employee_changes.benchmark_patterns


def test_performance_reviews_connect_compensation_and_training_growth():
    performance_reviews = module_by_id('performance-reviews')
    training_records = module_by_id('training-records')

    assert performance_reviews is not None
    assert training_records is not None
    assert 'employee-changes' in performance_reviews.downstream
    assert 'salary-profiles' in performance_reviews.downstream
    assert 'training-courses' in performance_reviews.downstream
    assert 'training-plans' in performance_reviews.downstream
    assert 'training-records' in performance_reviews.downstream
    assert 'performance-reviews' in training_records.upstream
    assert 'performance development plan' in performance_reviews.benchmark_patterns
