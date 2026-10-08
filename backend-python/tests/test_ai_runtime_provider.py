from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from models import AssistantAuditLog, db
from tests.test_saas_tenancy import _client, saas_app


def _save_runtime_config(
    *,
    provider_code: str = 'saved',
    resource_domain: str = 'assistant',
    use_case: str = '*',
    tier: str = 'standard',
    base_url: str = 'https://saved.example/v1',
    api_key: str = 'sk-saved-secret',
    model: str = 'saved-model',
    max_tokens: int = 321,
):
    from services.ai_resource_governance import save_model_policy, save_provider_config

    provider = save_provider_config(provider_code, {
        'displayName': 'Saved Provider',
        'baseUrl': base_url,
        'apiKey': api_key,
        'enabled': True,
    })
    policy = save_model_policy({
        'resourceDomain': resource_domain,
        'useCase': use_case,
        'tier': tier,
        'providerCode': provider_code,
        'modelProfile': tier,
        'model': model,
        'maxTokens': max_tokens,
        'enabled': True,
    })
    return provider, policy


def test_saved_provider_overrides_bootstrap_environment(saas_app, monkeypatch):
    app, _tokens = saas_app
    monkeypatch.setenv('SILICONFLOW_API_URL', 'https://bootstrap.invalid/v1')
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'sk-bootstrap')
    monkeypatch.setenv('ASSISTANT_STANDARD_MODEL', 'bootstrap-model')

    with app.app_context():
        _save_runtime_config()

        from services.ai_runtime_provider import resolve_ai_runtime

        resolved = resolve_ai_runtime('assistant', '*', 'standard')

    assert resolved.provider_code == 'saved'
    assert resolved.base_url == 'https://saved.example/v1'
    assert resolved.api_key == 'sk-saved-secret'
    assert resolved.model == 'saved-model'
    assert resolved.max_tokens == 321
    assert resolved.source == 'database'


def test_invalid_saved_provider_does_not_silently_fallback(saas_app, monkeypatch):
    app, _tokens = saas_app
    monkeypatch.setenv('SILICONFLOW_API_URL', 'https://bootstrap.example/v1')
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'sk-bootstrap')

    with app.app_context():
        provider, _policy = _save_runtime_config()
        provider.base_url = ''
        db.session.commit()

        from services.ai_runtime_provider import AIRuntimeConfigurationError, resolve_ai_runtime

        with pytest.raises(AIRuntimeConfigurationError) as exc:
            resolve_ai_runtime('assistant', '*', 'standard')

    assert exc.value.code == 'AI_PROVIDER_BASE_URL_INVALID'


def test_bootstrap_environment_is_used_only_without_saved_configuration(saas_app, monkeypatch):
    app, _tokens = saas_app
    monkeypatch.setenv('SILICONFLOW_API_URL', 'https://bootstrap.example/v1/')
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'sk-bootstrap')
    monkeypatch.setenv('ASSISTANT_STANDARD_MODEL', 'bootstrap-model')

    with app.app_context():
        from services.ai_runtime_provider import resolve_ai_runtime

        resolved = resolve_ai_runtime('assistant', 'dialogue', 'standard')

    assert resolved.provider_code == 'siliconflow'
    assert resolved.base_url == 'https://bootstrap.example/v1'
    assert resolved.api_key == 'sk-bootstrap'
    assert resolved.model == 'bootstrap-model'
    assert resolved.source == 'bootstrap_environment'


class _JSONResponse:
    status_code = 200

    def __init__(self, content: str = 'ok'):
        self._content = content

    def json(self):
        return {
            'choices': [{
                'message': {'role': 'assistant', 'content': self._content},
                'finish_reason': 'stop',
            }],
            'usage': {'prompt_tokens': 3, 'completion_tokens': 1},
        }


class _StreamResponse:
    status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_lines(self, decode_unicode=False):
        del decode_unicode
        yield b'data: {"choices":[{"delta":{"content":"saved stream"}}]}'
        yield b'data: [DONE]'


def test_sync_client_uses_saved_url_secret_model_and_token_limit(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _JSONResponse('saved sync')

    monkeypatch.setattr(llm_client, 'API_KEY', 'module-bootstrap-key')
    monkeypatch.setattr(llm_client, 'API_URL', 'https://module-bootstrap.invalid/v1')
    monkeypatch.setattr(llm_client.requests, 'post', fake_post)

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')
        message = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': 'sync'}],
            max_tokens=999,
            use_case='model_call_test',
            resource_domain='system_ai',
        )

    assert message == {'role': 'assistant', 'content': 'saved sync'}
    assert captured['url'] == 'https://saved.example/v1/chat/completions'
    assert captured['headers']['Authorization'] == 'Bearer sk-saved-secret'
    assert captured['json']['model'] == 'saved-model'
    assert captured['json']['max_tokens'] == 321
    assert llm_client.last_call_meta()['provider'] == 'saved'
    assert llm_client.last_call_meta()['runtime_source'] == 'database'


def test_saved_provider_is_available_without_bootstrap_key(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    monkeypatch.setattr(llm_client, 'API_KEY', '')
    monkeypatch.delenv('SILICONFLOW_API_KEY', raising=False)

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')

        assert llm_client.is_available() is True


def test_low_level_chat_resolves_saved_runtime_in_app_context(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    captured = {}
    monkeypatch.setattr(llm_client, 'API_KEY', 'module-key')
    monkeypatch.setattr(llm_client, 'API_URL', 'https://module.invalid/v1')
    monkeypatch.setattr(
        llm_client.requests,
        'post',
        lambda url, **kwargs: captured.update(url=url, **kwargs) or _JSONResponse('low-level'),
    )

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')
        message = llm_client.chat(
            [{'role': 'user', 'content': 'low-level'}],
            resource_domain='system_ai',
            use_case='low_level_sync',
        )

    assert message == {'role': 'assistant', 'content': 'low-level'}
    assert captured['url'] == 'https://saved.example/v1/chat/completions'
    assert captured['headers']['Authorization'] == 'Bearer sk-saved-secret'
    assert captured['json']['model'] == 'saved-model'


def test_low_level_json_chat_resolves_saved_runtime_in_app_context(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    captured = {}
    monkeypatch.setattr(llm_client, 'API_KEY', 'module-key')
    monkeypatch.setattr(llm_client, 'API_URL', 'https://module.invalid/v1')
    monkeypatch.setattr(
        llm_client.requests,
        'post',
        lambda url, **kwargs: captured.update(url=url, **kwargs) or _JSONResponse('{"ok": true}'),
    )

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')
        payload = llm_client.json_chat(
            [{'role': 'user', 'content': 'json'}],
            resource_domain='system_ai',
            use_case='low_level_json',
        )

    assert payload == {'ok': True}
    assert captured['url'] == 'https://saved.example/v1/chat/completions'
    assert captured['headers']['Authorization'] == 'Bearer sk-saved-secret'


def test_low_level_stream_chat_resolves_saved_runtime_in_app_context(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    captured = {}
    monkeypatch.setattr(llm_client, 'API_KEY', 'module-key')
    monkeypatch.setattr(llm_client, 'API_URL', 'https://module.invalid/v1')
    monkeypatch.setattr(
        llm_client.requests,
        'post',
        lambda url, **kwargs: captured.update(url=url, **kwargs) or _StreamResponse(),
    )

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')
        chunks = list(llm_client.stream_chat(
            [{'role': 'user', 'content': 'stream'}],
            resource_domain='system_ai',
            use_case='low_level_stream',
        ))

    assert chunks == ['saved stream']
    assert captured['url'] == 'https://saved.example/v1/chat/completions'
    assert captured['headers']['Authorization'] == 'Bearer sk-saved-secret'


def test_ctxless_saved_runtime_call_records_true_audit(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    monkeypatch.setattr(llm_client.requests, 'post', lambda *_args, **_kwargs: _JSONResponse('audited'))

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')
        message = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': 'ctxless audit'}],
            use_case='ctxless_runtime_test',
            resource_domain='system_ai',
            ctx=None,
        )
        audit = AssistantAuditLog.query.filter_by(use_case='ctxless_runtime_test').one()
        audit_payload = audit.to_dict()

    assert message == {'role': 'assistant', 'content': 'audited'}
    assert audit.provider == 'saved'
    assert audit.model == 'saved-model'
    assert audit.response_meta['runtimeSource'] == 'database'
    assert audit_payload['responseMeta']['runtimeSource'] == 'database'
    assert audit.request_id


def test_operator_provider_prevents_seeded_placeholder_policy_bootstrap(saas_app, monkeypatch):
    app, _tokens = saas_app
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'bootstrap-key-must-not-run')

    with app.app_context():
        from services.ai_resource_governance import seed_ai_resource_defaults
        from services.ai_runtime_provider import AIRuntimeConfigurationError, resolve_ai_runtime

        seed_ai_resource_defaults()
        _save_runtime_config(
            provider_code='operator-provider',
            resource_domain='system_ai',
            use_case='operator-only',
        )

        with pytest.raises(AIRuntimeConfigurationError) as exc:
            resolve_ai_runtime('assistant', 'dialogue', 'standard')

    assert exc.value.code == 'AI_MODEL_POLICY_MISSING'


def test_explicit_default_provider_save_without_secret_never_bootstraps(saas_app, monkeypatch):
    app, _tokens = saas_app
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'bootstrap-key-must-not-run')

    with app.app_context():
        from services.ai_resource_governance import save_provider_config, seed_ai_resource_defaults
        from services.ai_runtime_provider import AIRuntimeConfigurationError, resolve_ai_runtime
        from services.assistant_core import llm_client

        monkeypatch.setattr(llm_client, 'API_KEY', '')
        seed_ai_resource_defaults()
        provider = save_provider_config('siliconflow', {
            'displayName': 'Explicit SiliconFlow',
            'baseUrl': 'https://api.siliconflow.cn/v1',
            'enabled': True,
        })
        with pytest.raises(AIRuntimeConfigurationError) as exc:
            resolve_ai_runtime('assistant', 'dialogue', 'standard')
        runtime_available = llm_client.is_available()

    assert provider.settings_json['_configuredByOperator'] is True
    assert '_configuredByOperator' not in provider.to_dict()['settings']
    assert runtime_available is True
    assert exc.value.code == 'AI_PROVIDER_SECRET_INVALID'


def test_rotated_fernet_secret_is_reported_as_stable_configuration_error(saas_app, monkeypatch):
    app, _tokens = saas_app
    from cryptography.fernet import Fernet

    first_key = Fernet.generate_key().decode('ascii')
    rotated_key = Fernet.generate_key().decode('ascii')

    with app.app_context():
        from services.ai_runtime_provider import AIRuntimeConfigurationError, resolve_ai_runtime

        monkeypatch.setenv('AI_PROVIDER_SECRET_KEY', first_key)
        _save_runtime_config(resource_domain='system_ai')
        monkeypatch.setenv('AI_PROVIDER_SECRET_KEY', rotated_key)

        with pytest.raises(AIRuntimeConfigurationError) as exc:
            resolve_ai_runtime('system_ai', '*', 'standard')

    assert exc.value.code == 'AI_PROVIDER_SECRET_INVALID'


def test_runtime_resolution_failure_does_not_consume_request_quota_before_real_http(
    tmp_path,
    monkeypatch,
):
    import sqlite3

    from flask import Flask
    from sqlalchemy import event

    database_path = tmp_path / 'runtime-failure-metering.db'
    app = Flask('runtime-failure-metering')
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{database_path.as_posix()}',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'timeout': 0.1}},
    )
    db.init_app(app)
    from services.assistant_core import llm_client

    provider_calls = []
    monkeypatch.setattr(
        llm_client.requests,
        'post',
        lambda *_args, **_kwargs: provider_calls.append(True) or _JSONResponse('first real call'),
    )

    with app.app_context():
        from models import AIProviderConfig, Tenant, User
        from services.ai_resource_governance import (
            grant_tenant_ai_entitlement,
            save_model_policy,
            save_provider_config,
            seed_ai_resource_defaults,
        )

        @event.listens_for(db.engine, 'connect')
        def enable_sqlite_integrity(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.close()

        db.create_all()
        db.session.add(Tenant(
            id='tenant-runtime-failure',
            name='Runtime Failure Tenant',
            slug='runtime-failure',
            status='active',
        ))
        db.session.add(User(
            id='user-runtime-failure',
            tenant_id='tenant-runtime-failure',
            email='runtime-failure@example.com',
            password_hash='unused',
            name='Runtime Failure User',
            role='admin',
            status='active',
        ))
        db.session.commit()
        seed_ai_resource_defaults()
        grant_tenant_ai_entitlement(
            'tenant-runtime-failure',
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=1,
        )
        provider = save_provider_config('runtime-reservation-provider', {
            'displayName': 'Runtime Reservation Provider',
            'baseUrl': 'https://runtime-reservation.example/v1',
            'apiKey': 'initial-valid-secret',
            'enabled': True,
        })
        save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'runtime_reservation_test',
            'tier': 'standard',
            'providerCode': provider.provider_code,
            'modelProfile': 'standard',
            'model': 'runtime-reservation-model',
            'maxTokens': 64,
            'enabled': True,
        })
        provider.api_key_encrypted = 'corrupt-saved-secret'
        db.session.commit()

    ctx = SimpleNamespace(
        user_id='user-runtime-failure',
        tenant_id='tenant-runtime-failure',
        session_id=None,
        audit_user_id='user-runtime-failure',
        audit_session_id=None,
        request_id='runtime-resolution-no-reservation',
    )
    with app.test_request_context('/runtime-resolution-no-reservation'):
        from services.ai_resource_governance import save_provider_config

        failed = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': 'invalid runtime first'}],
            use_case='runtime_reservation_test',
            resource_domain='assistant',
            ctx=ctx,
            retry_once=False,
        )
        assert failed is None
        assert provider_calls == []

        with sqlite3.connect(database_path) as observer:
            observer.execute('PRAGMA foreign_keys=ON')
            failure_audits = observer.execute(
                'SELECT id, status, error_message, response_meta FROM assistant_audit_logs '
                'WHERE request_id = ?',
                (ctx.request_id,),
            ).fetchall()
            usage_after_failure = observer.execute(
                'SELECT COUNT(*) FROM ai_usage_ledger WHERE request_id = ?',
                (ctx.request_id,),
            ).fetchone()[0]

        assert len(failure_audits) == 1
        assert failure_audits[0][1] == 'error'
        assert 'corrupt-saved-secret' not in str(failure_audits[0])
        assert 'initial-valid-secret' not in str(failure_audits[0])
        assert usage_after_failure == 0

        save_provider_config('runtime-reservation-provider', {
            'apiKey': 'repaired-valid-secret',
        })
        message = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': 'first real provider call'}],
            use_case='runtime_reservation_test',
            resource_domain='assistant',
            ctx=ctx,
            retry_once=False,
        )

        assert message['content'] == 'first real call'
        assert provider_calls == [True]

        with sqlite3.connect(database_path) as observer:
            observer.execute('PRAGMA foreign_keys=ON')
            audit_rows = observer.execute(
                'SELECT id, status FROM assistant_audit_logs WHERE request_id = ? '
                'ORDER BY created_at, id',
                (ctx.request_id,),
            ).fetchall()
            ledger_rows = observer.execute(
                'SELECT assistant_audit_log_id FROM ai_usage_ledger WHERE request_id = ?',
                (ctx.request_id,),
            ).fetchall()

        assert len(audit_rows) == 2
        success_audit_id = next(row[0] for row in audit_rows if row[1] == 'success')
        assert ledger_rows == [(success_audit_id,)]


def test_missing_bootstrap_key_audits_without_usage_or_http(saas_app, monkeypatch):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    monkeypatch.setattr(
        llm_client.requests,
        'post',
        lambda *_args, **_kwargs: pytest.fail('missing key must not reach provider HTTP'),
    )
    runtime = SimpleNamespace(
        model='bootstrap-missing-key-model',
        provider_code='siliconflow',
        source='bootstrap_environment',
        api_key='',
        base_url='https://bootstrap-missing-key.example/v1',
        max_tokens=64,
    )
    request_id = 'bootstrap-missing-key-no-usage'
    audit_context = {
        'tenant_id': tokens['alpha_id'],
        'user_id': 'alpha-admin',
        'audit_user_id': 'alpha-admin',
        'session_id': None,
        'audit_session_id': None,
        'request_id': request_id,
        'resource_domain': 'assistant',
        'use_case': 'bootstrap_missing_key',
        'ai_tier': 'standard',
        'provider': 'siliconflow',
        'runtime_source': 'bootstrap_environment',
    }

    with app.test_request_context('/bootstrap-missing-key'):
        result = llm_client.chat(
            [{'role': 'user', 'content': 'must not call provider'}],
            runtime=runtime,
            audit_context=audit_context,
            retry_once=False,
        )

    assert result is None
    with app.app_context():
        from models import AIUsageLedger, AssistantAuditLog

        audit = AssistantAuditLog.query.filter_by(request_id=request_id).one()
        assert audit.status == 'error'
        assert audit.response_meta['configuration'] == 'missing_api_key'
        assert AIUsageLedger.query.filter_by(request_id=request_id).count() == 0


@pytest.mark.parametrize('denial_mode', ['disabled', 'quota'])
def test_governance_denials_audit_without_usage_or_http(
    saas_app,
    monkeypatch,
    denial_mode,
):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    monkeypatch.setattr(
        llm_client.requests,
        'post',
        lambda *_args, **_kwargs: pytest.fail('governance denial must not reach provider HTTP'),
    )
    with app.app_context():
        from services.ai_resource_governance import (
            grant_tenant_ai_entitlement,
            seed_ai_resource_defaults,
        )

        seed_ai_resource_defaults()
        if denial_mode == 'quota':
            grant_tenant_ai_entitlement(
                tokens['alpha_id'],
                resource_domain='assistant',
                package_code='ai_assistant',
                enabled=True,
                selected_tier='standard',
                allowed_tiers=['standard'],
                monthly_quota=0,
            )
    request_id = f'governance-{denial_mode}-no-usage'
    ctx = SimpleNamespace(
        user_id='alpha-admin',
        tenant_id=tokens['alpha_id'],
        session_id=None,
        audit_user_id='alpha-admin',
        audit_session_id=None,
        request_id=request_id,
    )
    with app.test_request_context(f'/governance/{denial_mode}'):
        result = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': 'must be denied'}],
            use_case='governance_denial_test',
            resource_domain='assistant',
            ctx=ctx,
            retry_once=False,
        )

    assert result is None
    with app.app_context():
        from models import AIUsageLedger, AssistantAuditLog

        audit = AssistantAuditLog.query.filter_by(request_id=request_id).one()
        assert audit.status == 'denied'
        assert AIUsageLedger.query.filter_by(request_id=request_id).count() == 0


def test_real_runtime_callsites_do_not_use_ungoverned_low_level_clients():
    root = Path(__file__).resolve().parents[2]
    legacy_router = (root / 'backend-python/services/assistant_core/legacy_router.py').read_text(encoding='utf-8')
    reranker = (root / 'backend-python/services/assistant_core/intent_router/reranker.py').read_text(encoding='utf-8')
    skills = (root / 'backend-python/services/assistant_core/skills.py').read_text(encoding='utf-8')

    assert 'llm_client.json_chat(' not in legacy_router
    assert 'prepare_profile_runtime(' in reranker
    assert 'runtime=runtime' in reranker
    assert 'ThreadPoolExecutor' not in reranker
    assert 'from .llm_client import chat,' not in skills


def _configure_retry_runtime(app, tokens, *, quota: int, use_case: str) -> SimpleNamespace:
    with app.app_context():
        from services.ai_resource_governance import (
            grant_tenant_ai_entitlement,
            seed_ai_resource_defaults,
        )

        seed_ai_resource_defaults()
        grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=quota,
        )
        _save_runtime_config(
            provider_code='retry-provider',
            resource_domain='assistant',
            use_case=use_case,
            model='retry-model',
        )
    return SimpleNamespace(
        user_id='alpha-admin',
        tenant_id=tokens['alpha_id'],
        session_id=None,
        audit_user_id='alpha-admin',
        audit_session_id=None,
        request_id=f'{use_case}-quota-{quota}',
    )


def _ledger_statuses_by_attempt(request_id: str) -> list[str]:
    from models import AIUsageLedger

    audits = AssistantAuditLog.query.filter_by(request_id=request_id).all()
    ledgers = AIUsageLedger.query.filter_by(request_id=request_id).all()
    ledger_status_by_audit_id = {
        row.assistant_audit_log_id: row.status
        for row in ledgers
    }
    metered_audits = [row for row in audits if row.id in ledger_status_by_audit_id]
    metered_audits.sort(key=lambda row: row.response_meta['attempt'])
    return [ledger_status_by_audit_id[row.id] for row in metered_audits]


@pytest.mark.parametrize(
    ('quota', 'expected_calls', 'expected_content', 'expected_ledger_statuses'),
    [
        (1, 1, None, ['timeout']),
        (2, 2, 'chat retry success', ['timeout', 'success']),
    ],
)
def test_chat_retry_authorizes_and_meters_each_real_http_attempt(
    saas_app,
    monkeypatch,
    quota,
    expected_calls,
    expected_content,
    expected_ledger_statuses,
):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    use_case = 'chat_retry_attempts'
    ctx = _configure_retry_runtime(app, tokens, quota=quota, use_case=use_case)
    provider_calls = []

    def fake_post(*_args, **_kwargs):
        provider_calls.append(True)
        if len(provider_calls) == 1:
            raise llm_client.requests.Timeout('first chat attempt timed out')
        return _JSONResponse('chat retry success')

    monkeypatch.setattr(llm_client.requests, 'post', fake_post)
    with app.test_request_context(f'/{use_case}/{quota}'):
        message = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': 'retry chat'}],
            use_case=use_case,
            resource_domain='assistant',
            ctx=ctx,
            retry_once=True,
        )

    assert len(provider_calls) == expected_calls
    assert (message or {}).get('content') == expected_content
    with app.app_context():
        statuses = _ledger_statuses_by_attempt(ctx.request_id)
    assert statuses == expected_ledger_statuses


@pytest.mark.parametrize(
    ('retry_once', 'http_statuses'),
    [
        (False, [429]),
        (False, [503]),
        (True, [429, 503]),
    ],
)
def test_chat_retryable_http_attempts_are_each_audited_and_metered(
    saas_app,
    monkeypatch,
    retry_once,
    http_statuses,
):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    use_case = f"chat_http_{'retry' if retry_once else 'single'}_{'_'.join(map(str, http_statuses))}"
    ctx = _configure_retry_runtime(
        app,
        tokens,
        quota=len(http_statuses),
        use_case=use_case,
    )
    provider_calls = []

    def fake_post(*_args, **_kwargs):
        if provider_calls:
            from models import AIUsageLedger

            assert AssistantAuditLog.query.filter_by(request_id=ctx.request_id).count() == len(provider_calls)
            assert AIUsageLedger.query.filter_by(request_id=ctx.request_id).count() == len(provider_calls)
        status_code = http_statuses[len(provider_calls)]
        provider_calls.append(status_code)
        return SimpleNamespace(status_code=status_code)

    monkeypatch.setattr(llm_client.requests, 'post', fake_post)
    with app.test_request_context(f'/{use_case}'):
        message = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': 'retryable chat HTTP response'}],
            use_case=use_case,
            resource_domain='assistant',
            ctx=ctx,
            retry_once=retry_once,
        )

    assert message is None
    assert provider_calls == http_statuses
    with app.app_context():
        from models import AIUsageLedger

        audits = AssistantAuditLog.query.filter_by(request_id=ctx.request_id).all()
        ledgers = AIUsageLedger.query.filter_by(request_id=ctx.request_id).all()

    audits.sort(key=lambda row: row.response_meta['attempt'])
    assert [row.status for row in audits] == ['error'] * len(http_statuses)
    assert [row.response_meta['httpStatus'] for row in audits] == http_statuses
    assert [row.response_meta['attempt'] for row in audits] == list(range(len(http_statuses)))
    assert len(ledgers) == len(http_statuses)
    assert {row.status for row in ledgers} == {'error'}
    assert {row.assistant_audit_log_id for row in ledgers} == {row.id for row in audits}


@pytest.mark.parametrize(
    ('quota', 'expected_calls', 'expected_chunks', 'expected_ledger_statuses'),
    [
        (1, 1, [], ['timeout']),
        (2, 2, ['saved stream'], ['timeout', 'success']),
    ],
)
def test_stream_retry_authorizes_and_meters_each_real_http_attempt(
    saas_app,
    monkeypatch,
    quota,
    expected_calls,
    expected_chunks,
    expected_ledger_statuses,
):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    use_case = 'stream_retry_attempts'
    ctx = _configure_retry_runtime(app, tokens, quota=quota, use_case=use_case)
    provider_calls = []

    def fake_post(*_args, **_kwargs):
        provider_calls.append(True)
        if len(provider_calls) == 1:
            raise llm_client.requests.Timeout('first stream attempt timed out')
        return _StreamResponse()

    monkeypatch.setattr(llm_client.requests, 'post', fake_post)
    with app.test_request_context(f'/{use_case}/{quota}'):
        chunks = list(llm_client.stream_chat_profile(
            'standard',
            [{'role': 'user', 'content': 'retry stream'}],
            use_case=use_case,
            resource_domain='assistant',
            ctx=ctx,
            retry_once=True,
        ))

    assert len(provider_calls) == expected_calls
    assert chunks == expected_chunks
    with app.app_context():
        statuses = _ledger_statuses_by_attempt(ctx.request_id)
    assert statuses == expected_ledger_statuses


@pytest.mark.parametrize(
    ('retry_once', 'http_statuses'),
    [
        (False, [429]),
        (False, [503]),
        (True, [429, 503]),
    ],
)
def test_stream_retryable_http_attempts_are_each_audited_metered_and_closed(
    saas_app,
    monkeypatch,
    retry_once,
    http_statuses,
):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    use_case = f"stream_http_{'retry' if retry_once else 'single'}_{'_'.join(map(str, http_statuses))}"
    ctx = _configure_retry_runtime(
        app,
        tokens,
        quota=len(http_statuses),
        use_case=use_case,
    )
    provider_calls = []
    response_exits = []

    class RetryableStreamResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc, tb
            response_exits.append((self.status_code, exc_type))
            return False

    def fake_post(*_args, **_kwargs):
        if provider_calls:
            from models import AIUsageLedger, AssistantAuditLog

            assert AssistantAuditLog.query.filter_by(request_id=ctx.request_id).count() == len(provider_calls)
            assert AIUsageLedger.query.filter_by(request_id=ctx.request_id).count() == len(provider_calls)
        status_code = http_statuses[len(provider_calls)]
        provider_calls.append(status_code)
        return RetryableStreamResponse(status_code)

    monkeypatch.setattr(llm_client.requests, 'post', fake_post)
    with app.test_request_context(f'/{use_case}'):
        chunks = list(llm_client.stream_chat_profile(
            'standard',
            [{'role': 'user', 'content': 'retryable stream HTTP response'}],
            use_case=use_case,
            resource_domain='assistant',
            ctx=ctx,
            retry_once=retry_once,
        ))

    assert chunks == []
    assert provider_calls == http_statuses
    assert response_exits == [(status_code, None) for status_code in http_statuses]
    with app.app_context():
        from models import AIUsageLedger

        audits = AssistantAuditLog.query.filter_by(request_id=ctx.request_id).all()
        ledgers = AIUsageLedger.query.filter_by(request_id=ctx.request_id).all()

    audits.sort(key=lambda row: row.response_meta['attempt'])
    assert [row.status for row in audits] == ['error'] * len(http_statuses)
    assert [row.response_meta['httpStatus'] for row in audits] == http_statuses
    assert [row.response_meta['attempt'] for row in audits] == list(range(len(http_statuses)))
    assert len(ledgers) == len(http_statuses)
    assert {row.status for row in ledgers} == {'error'}
    assert {row.assistant_audit_log_id for row in ledgers} == {row.id for row in audits}


def test_stream_consumer_close_audits_and_meters_cancelled_http_attempt(
    saas_app,
    monkeypatch,
):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    use_case = 'stream_consumer_cancelled'
    ctx = _configure_retry_runtime(app, tokens, quota=1, use_case=use_case)
    provider_calls = []
    response_exit_types = []

    class CancellableStreamResponse:
        status_code = 200

        def __enter__(self):
            provider_calls.append('entered')
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc, tb
            response_exit_types.append(exc_type)
            return False

        def iter_lines(self, decode_unicode=False):
            del decode_unicode
            yield b'data: {"choices":[{"delta":{"content":"partial stream"}}]}'
            yield b'data: {"choices":[{"delta":{"content":"must not be consumed"}}]}'

    monkeypatch.setattr(
        llm_client.requests,
        'post',
        lambda *_args, **_kwargs: CancellableStreamResponse(),
    )
    with app.test_request_context(f'/{use_case}'):
        stream = llm_client.stream_chat_profile(
            'standard',
            [{'role': 'user', 'content': 'cancel after the first chunk'}],
            use_case=use_case,
            resource_domain='assistant',
            ctx=ctx,
            retry_once=False,
        )
        assert next(stream) == 'partial stream'
        stream.close()

    assert provider_calls == ['entered']
    assert response_exit_types == [GeneratorExit]
    assert llm_client.last_call_meta()['status'] == 'cancelled'
    with app.app_context():
        from models import AIUsageLedger

        audit = AssistantAuditLog.query.filter_by(request_id=ctx.request_id).one()
        ledger = AIUsageLedger.query.filter_by(request_id=ctx.request_id).one()

    assert audit.status == 'cancelled'
    assert audit.response_content == 'partial stream'
    assert audit.response_meta['attempt'] == 0
    assert audit.response_meta['stream'] is True
    assert audit.response_meta['chunkCount'] == 1
    assert ledger.status == 'cancelled'
    assert ledger.assistant_audit_log_id == audit.id


def test_reranker_worker_persists_saved_runtime_audit(saas_app, monkeypatch):
    app, tokens = saas_app
    from services.assistant_core import llm_client
    from services.assistant_core.intent_router.reranker import Reranker
    from services.assistant_core.intent_router.retriever import RetrievalCandidates
    from services.assistant_core.schemas import AssistantContext

    provider_response = _JSONResponse(
        '{"task_id":"task1","entities":{},"missing_fields":[],'
        '"confidence":0.91,"clarification_question":null}'
    )
    monkeypatch.setattr(llm_client.requests, 'post', lambda *_args, **_kwargs: provider_response)

    with app.app_context():
        from services.ai_resource_governance import (
            grant_tenant_ai_entitlement,
            save_model_policy,
            save_provider_config,
        )

        grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=10,
        )
        save_provider_config('reranker-saved', {
            'displayName': 'Reranker Saved',
            'baseUrl': 'https://reranker.example/v1',
            'apiKey': 'reranker-secret',
            'enabled': True,
        })
        save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'intent_reranking',
            'tier': 'standard',
            'providerCode': 'reranker-saved',
            'modelProfile': 'small',
            'model': 'reranker-model',
            'maxTokens': 600,
            'enabled': True,
        })
        ctx = AssistantContext(
            user_id='alpha-admin',
            role='admin',
            request_id='reranker-worker-audit',
            audit_user_id='alpha-admin',
        )
        result = Reranker(timeout_ms=2000).rerank(
            '测试重排',
            RetrievalCandidates(items=[('task1', 0.9, '任务一')]),
            ctx,
        )
        audits = AssistantAuditLog.query.filter_by(
            request_id='reranker-worker-audit',
            use_case='intent_reranking',
        ).all()
        from models import AIUsageLedger
        from services.ai_resource_governance import usage_count

        usage_rows = AIUsageLedger.query.filter_by(request_id='reranker-worker-audit').all()
        metered = usage_count(tokens['alpha_id'], 'assistant')

    assert result.task_template_id == 'task1'
    assert len(audits) == 1
    assert audits[0].provider == 'reranker-saved'
    assert audits[0].model == 'reranker-model'
    assert audits[0].tenant_id == tokens['alpha_id']
    assert audits[0].response_meta['runtimeSource'] == 'database'
    assert len(usage_rows) == 1
    assert usage_rows[0].tenant_id == tokens['alpha_id']
    assert metered == 1


def test_reranker_timeout_has_no_late_success_audit(saas_app, monkeypatch):
    import time

    import requests

    app, tokens = saas_app
    from services.assistant_core import llm_client
    from services.assistant_core.intent_router.reranker import Reranker
    from services.assistant_core.intent_router.retriever import RetrievalCandidates
    from services.assistant_core.schemas import AssistantContext

    provider_response = _JSONResponse(
        '{"task_id":"task1","entities":{},"missing_fields":[],'
        '"confidence":0.91,"clarification_question":null}'
    )

    def deadline_aware_post(*_args, **kwargs):
        timeout = float(kwargs.get('timeout') or 0)
        if timeout <= 0.05:
            time.sleep(timeout)
            raise requests.Timeout('deadline reached')
        time.sleep(0.12)
        return provider_response

    monkeypatch.setattr(llm_client.requests, 'post', deadline_aware_post)

    with app.app_context():
        from services.ai_resource_governance import (
            grant_tenant_ai_entitlement,
            save_model_policy,
            save_provider_config,
        )

        grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=10,
        )
        save_provider_config('reranker-timeout', {
            'displayName': 'Reranker Timeout',
            'baseUrl': 'https://reranker-timeout.example/v1',
            'apiKey': 'reranker-timeout-secret',
            'enabled': True,
        })
        save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'intent_reranking',
            'tier': 'standard',
            'providerCode': 'reranker-timeout',
            'modelProfile': 'small',
            'model': 'reranker-timeout-model',
            'maxTokens': 600,
            'enabled': True,
        })
        ctx = AssistantContext(
            user_id='alpha-admin',
            role='admin',
            request_id='reranker-timeout-audit',
            audit_user_id='alpha-admin',
        )
        result = Reranker(timeout_ms=20).rerank(
            '测试超时',
            RetrievalCandidates(items=[('task1', 0.9, '任务一')]),
            ctx,
        )
        time.sleep(0.2)
        audits = AssistantAuditLog.query.filter_by(request_id='reranker-timeout-audit').all()

    assert result.route_path == 'fallback'
    assert [row.status for row in audits] == ['timeout']
    assert audits[0].provider == 'reranker-timeout'
    assert audits[0].model == 'reranker-timeout-model'
    assert audits[0].tenant_id == tokens['alpha_id']
    assert audits[0].response_meta['runtimeSource'] == 'database'


def test_stream_client_uses_saved_runtime(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    captured = {}

    class StreamResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def iter_lines(self, decode_unicode=False):
            yield b'data: {"choices":[{"delta":{"content":"saved stream"}}]}'
            yield b'data: [DONE]'

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return StreamResponse()

    monkeypatch.setattr(llm_client, 'API_KEY', 'module-bootstrap-key')
    monkeypatch.setattr(llm_client, 'API_URL', 'https://module-bootstrap.invalid/v1')
    monkeypatch.setattr(llm_client.requests, 'post', fake_post)

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')
        chunks = list(llm_client.stream_chat_profile(
            'standard',
            [{'role': 'user', 'content': 'stream'}],
            max_tokens=999,
            use_case='model_stream_test',
            resource_domain='system_ai',
            retry_once=False,
        ))

    assert chunks == ['saved stream']
    assert captured['url'] == 'https://saved.example/v1/chat/completions'
    assert captured['headers']['Authorization'] == 'Bearer sk-saved-secret'
    assert captured['json']['model'] == 'saved-model'
    assert captured['json']['max_tokens'] == 321


def test_tool_client_uses_saved_runtime(saas_app, monkeypatch):
    app, _tokens = saas_app
    from services.assistant_core import llm_client

    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _JSONResponse('tool call')

    monkeypatch.setattr(llm_client, 'API_KEY', 'module-bootstrap-key')
    monkeypatch.setattr(llm_client, 'API_URL', 'https://module-bootstrap.invalid/v1')
    monkeypatch.setattr(llm_client.requests, 'post', fake_post)

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')
        message = llm_client.chat_with_tools(
            [{'role': 'user', 'content': 'tool'}],
            [{'type': 'function', 'function': {'name': 'lookup'}}],
            max_tokens=999,
            use_case='model_tool_test',
            resource_domain='system_ai',
        )

    assert message == {'role': 'assistant', 'content': 'tool call'}
    assert captured['url'] == 'https://saved.example/v1/chat/completions'
    assert captured['headers']['Authorization'] == 'Bearer sk-saved-secret'
    assert captured['json']['model'] == 'saved-model'
    assert captured['json']['max_tokens'] == 321


def test_platform_diagnostic_reports_and_audits_saved_runtime(saas_app, monkeypatch):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _JSONResponse('diagnostic saved')

    monkeypatch.setattr(llm_client, 'API_KEY', 'module-bootstrap-key')
    monkeypatch.setattr(llm_client, 'API_URL', 'https://module-bootstrap.invalid/v1')
    monkeypatch.setattr(llm_client.requests, 'post', fake_post)

    with app.app_context():
        _save_runtime_config(resource_domain='system_ai')

    response = _client(app, tokens['platform']).post(
        '/api/platform/ai/diagnostics/model-call-test',
        json={'prompt': 'diagnostic', 'modelProfile': 'standard'},
        headers={'X-Request-ID': 'saved-runtime-diagnostic'},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True
    assert payload['provider'] == 'saved'
    assert payload['model'] == 'saved-model'
    assert 'sk-saved-secret' not in str(payload)
    assert captured['url'] == 'https://saved.example/v1/chat/completions'

    with app.app_context():
        from models import AIUsageLedger

        audit = AssistantAuditLog.query.filter_by(request_id='saved-runtime-diagnostic').one()
        ledger = AIUsageLedger.query.filter_by(request_id='saved-runtime-diagnostic').one()
        assert audit.provider == 'saved'
        assert audit.model == 'saved-model'
        assert ledger.assistant_audit_log_id == audit.id
        assert 'sk-saved-secret' not in str(audit.to_dict())


def test_prompt_optimizer_without_save_turn_keeps_unlinked_audit_and_ledger(saas_app, monkeypatch):
    app, tokens = saas_app
    from services.assistant_core import llm_client

    monkeypatch.setattr(llm_client.requests, 'post', lambda *_args, **_kwargs: _JSONResponse('optimized saved'))
    with app.app_context():
        from services.ai_resource_governance import grant_tenant_ai_entitlement, seed_ai_resource_defaults

        seed_ai_resource_defaults()
        grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=10,
        )
        _save_runtime_config(
            resource_domain='assistant',
            use_case='prompt_optimization',
        )

    response = _client(app, tokens['alpha']).post(
        '/api/hrm/assistant/optimize-prompt',
        json={'prompt': '优化这句话'},
        headers={'X-Request-ID': 'optimizer-without-save-turn'},
    )
    assert response.status_code == 200
    assert response.get_json()['optimized'] == 'optimized saved'

    with app.app_context():
        from models import AIUsageLedger

        audit = AssistantAuditLog.query.filter_by(use_case='prompt_optimization').one()
        ledger = AIUsageLedger.query.filter_by(assistant_audit_log_id=audit.id).one()
        assert audit.use_case == 'prompt_optimization'
        assert ledger.assistant_audit_log_id == audit.id
