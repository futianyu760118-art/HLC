"""Task 10.1 —— FastPath 单元测试。

校验目标（Validates: Requirements 2.1, 2.2, 2.3, 2.4）：

* **2.1 写动作直通**：消息命中 ``guardrails.detect_write_intent`` 时返回
  ``forbidden_action_response``，``risk_level=high``、
  ``requires_confirmation=True``、``route_path='fast_path'``，并附带
  ``forbidden_reason``。
* **2.2 高风险域关键词命中**：薪酬关键词（如 "工资"、"社保"、"个税"）命中后
  返回 ``payroll_month_summary``，``risk_level=high``、``route_path='fast_path'``、
  ``candidate_skills=['payroll_analysis']``。
* **2.3 仅高风险域**：yaml 中误配中危 / 低危条目（``task_template_id`` 不属于
  ``payroll_*`` 也不是 ``forbidden_action_response``）→ 启动加载时抛
  ``ValueError``，且错误信息能定位到具体条目。
* **2.4 热加载**：修改 yaml 后，下一次 ``match`` 调用就能看到新值（用
  ``tmp_path`` + ``os.utime`` 模拟 mtime 变化）。
* 未命中：消息既不触发写意图也不命中任何高风险关键词时返回 ``None``。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import yaml

from services.assistant_core.intent_router import fastpath as fp
from services.assistant_core.intent_router.fastpath import (
    ENV_FASTPATH_KEYWORDS_PATH, FastPath,
)
from services.assistant_core.schemas import AssistantContext


# ---- 共享 fixtures ---------------------------------------------------------


def _payroll_only_yaml() -> str:
    """合法的薪酬域配置（与生产 yaml 同款）。"""
    return yaml.safe_dump(
        {
            'payroll': {
                'keywords': ['工资', '工资条', '薪资', '薪酬', '社保', '个税'],
                'task_template_id': 'payroll_month_summary',
                'candidate_skills': ['payroll_analysis'],
                'risk_level': 'high',
            }
        },
        allow_unicode=True,
    )


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding='utf-8')


@pytest.fixture
def keywords_path(tmp_path: Path) -> Path:
    """每个测试一份独立的 yaml 文件。"""
    p = tmp_path / 'fastpath_keywords.yaml'
    _write_yaml(p, _payroll_only_yaml())
    return p


@pytest.fixture
def ctx() -> AssistantContext:
    """轻量上下文；FastPath 当前不消费 ctx 内容。"""
    return AssistantContext(user_id='u-1', role='hr_admin', session_id='s-1')


@pytest.fixture(autouse=True)
def _reset_module_singleton(monkeypatch):
    """避免模块级 ``_default_fastpath`` 的状态在测试间泄漏。"""
    monkeypatch.delenv(ENV_FASTPATH_KEYWORDS_PATH, raising=False)
    fp.reload()
    yield
    fp.reload()


# ---- 2.1 写动作直通 --------------------------------------------------------


class TestForbiddenWriteIntent:
    def test_delete_verb_routes_to_forbidden_action(self, keywords_path: Path, ctx):
        router = FastPath(path=str(keywords_path))
        result = router.match('删除张三的考勤记录', ctx)

        assert result is not None
        assert result.task_template_id == 'forbidden_action_response'
        assert result.risk_level == 'high'
        assert result.requires_confirmation is True
        assert result.route_path == 'fast_path'
        # forbidden_reason 来自 detect_write_intent 的具体原因，非空字符串。
        assert isinstance(result.forbidden_reason, str)
        assert result.forbidden_reason  # 非空
        # entities 中也保留同份原因，便于 trace 复盘。
        assert result.entities.get('forbidden_reason') == result.forbidden_reason
        # 高置信度：FastPath 命中是确定性结果。
        assert result.confidence >= 0.9

    def test_raw_sql_request_routes_to_forbidden_action(self, keywords_path: Path, ctx):
        router = FastPath(path=str(keywords_path))
        result = router.match('帮我执行SQL: SELECT * FROM employees', ctx)

        assert result is not None
        assert result.task_template_id == 'forbidden_action_response'
        assert result.risk_level == 'high'
        assert result.requires_confirmation is True

    def test_send_intent_routes_to_forbidden_action(self, keywords_path: Path, ctx):
        router = FastPath(path=str(keywords_path))
        result = router.match('帮我群发邮件给所有面试候选人', ctx)

        assert result is not None
        assert result.task_template_id == 'forbidden_action_response'
        assert result.requires_confirmation is True

    def test_write_intent_takes_precedence_over_payroll_keyword(
        self, keywords_path: Path, ctx,
    ):
        """同时命中写意图和薪酬关键词时，写意图优先。"""
        router = FastPath(path=str(keywords_path))
        result = router.match('删除小王的工资条记录', ctx)

        assert result is not None
        assert result.task_template_id == 'forbidden_action_response'
        # 不是薪酬域路由
        assert result.intent != 'payroll_month_summary'


# ---- 2.2 薪酬关键词命中 ----------------------------------------------------


class TestPayrollKeywordMatch:
    @pytest.mark.parametrize(
        'message',
        [
            '帮我看下小王本月的工资',
            '想查一下我的工资条',
            '本月薪资',
            '社保缴纳情况',
            '个税起征点',
            '薪酬总额',
        ],
    )
    def test_payroll_keyword_routes_to_payroll_month_summary(
        self, keywords_path: Path, ctx, message: str,
    ):
        router = FastPath(path=str(keywords_path))
        result = router.match(message, ctx)

        assert result is not None, f'expected fastpath hit for {message!r}'
        assert result.task_template_id == 'payroll_month_summary'
        assert result.risk_level == 'high'
        assert result.route_path == 'fast_path'
        assert result.candidate_skills == ['payroll_analysis']
        # entities 至少要记录命中的关键词，方便后续 trace。
        assert result.entities.get('matched_keyword')

    def test_payroll_match_does_not_set_requires_confirmation(
        self, keywords_path: Path, ctx,
    ):
        """薪酬域命中本身只是路由决策，是否 confirm 由 PermissionGate 决定。"""
        router = FastPath(path=str(keywords_path))
        result = router.match('查一下工资条', ctx)
        assert result is not None
        assert result.requires_confirmation is False
        assert result.forbidden_reason is None

    def test_non_matching_message_returns_none(self, keywords_path: Path, ctx):
        router = FastPath(path=str(keywords_path))
        # 既无写意图也不含薪酬关键词
        assert router.match('最近一周来了几份高分简历', ctx) is None
        assert router.match('帮我看一下小王的考勤情况', ctx) is None
        assert router.match('', ctx) is None


# ---- 2.3 yaml 自检：拒绝中危/低危条目 ---------------------------------------


class TestYamlSelfCheck:
    def test_rejects_disallowed_task_template_id(self, tmp_path: Path):
        """``task_template_id`` 不属于 ``payroll_*`` 也不是
        ``forbidden_action_response`` → ``ValueError``。"""
        bad_path = tmp_path / 'bad.yaml'
        _write_yaml(bad_path, yaml.safe_dump(
            {
                'global': {
                    'keywords': ['搜索', '查找'],
                    'task_template_id': 'global_search_answer',  # 低风险，禁止
                    'candidate_skills': ['global_search'],
                    'risk_level': 'high',  # 即便假装 high 也要拒
                }
            },
            allow_unicode=True,
        ))

        with pytest.raises(ValueError) as exc_info:
            FastPath(path=str(bad_path))
        msg = str(exc_info.value)
        # 错误信息能定位到具体条目与具体非法 task_id。
        assert 'global' in msg
        assert 'global_search_answer' in msg

    def test_rejects_medium_risk_level(self, tmp_path: Path):
        bad_path = tmp_path / 'bad.yaml'
        _write_yaml(bad_path, yaml.safe_dump(
            {
                'payroll': {
                    'keywords': ['工资'],
                    'task_template_id': 'payroll_month_summary',
                    'candidate_skills': ['payroll_analysis'],
                    'risk_level': 'medium',  # 必须 high
                }
            },
            allow_unicode=True,
        ))

        with pytest.raises(ValueError) as exc_info:
            FastPath(path=str(bad_path))
        assert 'risk_level' in str(exc_info.value)

    def test_rejects_low_risk_level(self, tmp_path: Path):
        bad_path = tmp_path / 'bad.yaml'
        _write_yaml(bad_path, yaml.safe_dump(
            {
                'payroll': {
                    'keywords': ['工资'],
                    'task_template_id': 'payroll_month_summary',
                    'candidate_skills': ['payroll_analysis'],
                    'risk_level': 'low',
                }
            },
            allow_unicode=True,
        ))

        with pytest.raises(ValueError):
            FastPath(path=str(bad_path))

    def test_rejects_attendance_domain_entry(self, tmp_path: Path):
        """考勤是中等风险域，绝不允许进入 fastpath。"""
        bad_path = tmp_path / 'bad.yaml'
        _write_yaml(bad_path, yaml.safe_dump(
            {
                'attendance': {
                    'keywords': ['考勤', '迟到'],
                    'task_template_id': 'attendance_exception_analysis',
                    'candidate_skills': ['attendance_analysis'],
                    'risk_level': 'high',
                }
            },
            allow_unicode=True,
        ))

        with pytest.raises(ValueError) as exc_info:
            FastPath(path=str(bad_path))
        assert 'attendance_exception_analysis' in str(exc_info.value)

    def test_rejects_missing_task_template_id(self, tmp_path: Path):
        bad_path = tmp_path / 'bad.yaml'
        _write_yaml(bad_path, yaml.safe_dump(
            {
                'payroll': {
                    'keywords': ['工资'],
                    'candidate_skills': ['payroll_analysis'],
                    'risk_level': 'high',
                }
            },
            allow_unicode=True,
        ))

        with pytest.raises(ValueError):
            FastPath(path=str(bad_path))

    def test_accepts_other_payroll_prefixed_task(self, tmp_path: Path):
        """``payroll_`` 前缀下的其它任务应当被允许（前向兼容）。"""
        good_path = tmp_path / 'good.yaml'
        _write_yaml(good_path, yaml.safe_dump(
            {
                'payroll_compare': {
                    'keywords': ['工资对比'],
                    'task_template_id': 'payroll_compare_two_months',
                    'candidate_skills': ['payroll_analysis'],
                    'risk_level': 'high',
                }
            },
            allow_unicode=True,
        ))

        router = FastPath(path=str(good_path))  # 不应抛异常
        assert router.entries
        assert router.entries[0].task_template_id == 'payroll_compare_two_months'

    def test_missing_yaml_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            FastPath(path=str(tmp_path / 'does-not-exist.yaml'))

    def test_empty_yaml_loads_with_no_entries(self, tmp_path: Path, ctx):
        """空 yaml 视为合法（无 fastpath 域）：``match`` 总是返回 ``None``，
        但写意图直通仍然生效。"""
        empty = tmp_path / 'empty.yaml'
        empty.write_text('', encoding='utf-8')

        router = FastPath(path=str(empty))
        assert router.entries == ()
        # 关键词路径肯定不命中
        assert router.match('查一下工资条', ctx) is None
        # 写意图直通仍然工作
        result = router.match('删除张三的工资记录', ctx)
        assert result is not None
        assert result.task_template_id == 'forbidden_action_response'


# ---- 2.4 热加载 ------------------------------------------------------------


class TestHotReload:
    def test_match_sees_new_keywords_after_mtime_bump(
        self, keywords_path: Path, ctx,
    ):
        router = FastPath(path=str(keywords_path))

        # 起初 "奖金" 不在关键词集合内 → 应当未命中。
        assert router.match('请问本月奖金多少', ctx) is None

        # 修改 yaml：新增 "奖金"。文件系统的 mtime 粒度通常 1s，所以显式
        # 用 ``os.utime`` 把 mtime 推到当前时间 + 5 秒，确保下一次 match
        # 一定能看到 mtime 变化。
        new_yaml = yaml.safe_dump(
            {
                'payroll': {
                    'keywords': ['工资', '工资条', '薪资', '薪酬', '社保', '个税', '奖金'],
                    'task_template_id': 'payroll_month_summary',
                    'candidate_skills': ['payroll_analysis'],
                    'risk_level': 'high',
                }
            },
            allow_unicode=True,
        )
        _write_yaml(keywords_path, new_yaml)
        future = time.time() + 5
        os.utime(str(keywords_path), (future, future))

        # 下一次 match 必须看到新值。
        result = router.match('请问本月奖金多少', ctx)
        assert result is not None
        assert result.task_template_id == 'payroll_month_summary'
        assert result.entities.get('matched_keyword') == '奖金'

    def test_no_reload_when_mtime_unchanged(
        self, keywords_path: Path, ctx, monkeypatch: pytest.MonkeyPatch,
    ):
        """mtime 未变 → 不调用 ``_load``，避免每次 match 都做磁盘 IO。"""
        router = FastPath(path=str(keywords_path))

        load_calls = {'count': 0}
        original_load = router._load

        def _spy_load() -> None:
            load_calls['count'] += 1
            original_load()

        monkeypatch.setattr(router, '_load', _spy_load)

        for _ in range(5):
            router.match('查一下工资条', ctx)
        assert load_calls['count'] == 0, (
            f'expected zero reloads when mtime unchanged, got {load_calls["count"]}'
        )

    def test_invalid_yaml_after_reload_raises(
        self, keywords_path: Path, ctx,
    ):
        """热加载到非法 yaml（中危条目）应当抛错，避免脏配置生效。"""
        router = FastPath(path=str(keywords_path))
        # 起始 yaml 合法，确认能正常匹配。
        assert router.match('查一下工资条', ctx) is not None

        # 把 yaml 改成中危条目。
        bad_yaml = yaml.safe_dump(
            {
                'global': {
                    'keywords': ['搜索'],
                    'task_template_id': 'global_search_answer',
                    'candidate_skills': ['global_search'],
                    'risk_level': 'high',
                }
            },
            allow_unicode=True,
        )
        _write_yaml(keywords_path, bad_yaml)
        future = time.time() + 5
        os.utime(str(keywords_path), (future, future))

        with pytest.raises(ValueError):
            router.match('查一下工资条', ctx)


# ---- 路径解析：env / 默认值 / 显式参数 ---------------------------------------


class TestPathResolution:
    def test_env_var_overrides_default_path(
        self, keywords_path: Path, ctx, monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv(ENV_FASTPATH_KEYWORDS_PATH, str(keywords_path))
        router = FastPath()  # 不传 path → 应当用 env
        assert router.path == str(keywords_path)
        assert router.match('查一下工资条', ctx) is not None

    def test_explicit_path_overrides_env_var(
        self, keywords_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # env 指向不存在的路径；显式 path 应当胜出。
        monkeypatch.setenv(
            ENV_FASTPATH_KEYWORDS_PATH, str(tmp_path / 'absent.yaml'),
        )
        router = FastPath(path=str(keywords_path))
        assert router.path == str(keywords_path)

    def test_default_module_path_loads_payroll_only(self, ctx):
        """生产 yaml（仓库自带）必须只含 payroll 条目，且加载不抛错。"""
        router = FastPath()  # 默认指向模块同目录下的 fastpath_keywords.yaml
        # 至少有一条，且全部 task_id 满足白名单。
        assert router.entries
        for entry in router.entries:
            assert (
                entry.task_template_id == 'forbidden_action_response'
                or entry.task_template_id.startswith('payroll_')
            )
        # 默认配置下，薪酬关键词必须能命中。
        result = router.match('查一下工资条', ctx)
        assert result is not None
        assert result.task_template_id == 'payroll_month_summary'
