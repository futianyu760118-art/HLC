import logging
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask_jwt_extended import create_access_token

from models import db
from services.tenancy import tenant_claims_for
from tests.test_saas_tenancy import _client, saas_app


def test_database_startup_seeds_ai_defaults_inside_schema_lock(saas_app, monkeypatch):
    app, _tokens = saas_app
    import schema_migrations
    from app import _init_database
    from services import ai_resource_governance as governance

    events = []

    @contextmanager
    def tracked_schema_lock():
        events.append('lock-enter')
        try:
            yield
        finally:
            events.append('lock-exit')

    monkeypatch.setattr(schema_migrations, 'schema_migration_lock', tracked_schema_lock)
    monkeypatch.setattr(schema_migrations, 'ensure_schema', lambda: events.append('schema'))
    monkeypatch.setattr(schema_migrations, 'seed_defaults', lambda: events.append('core-seed'))
    monkeypatch.setattr(governance, 'seed_ai_resource_defaults', lambda: events.append('ai-seed'))
    monkeypatch.setattr(db, 'create_all', lambda: events.append('create-all'))

    _init_database(app)

    assert events == [
        'lock-enter',
        'create-all',
        'schema',
        'core-seed',
        'ai-seed',
        'lock-exit',
    ]


def test_ai_resource_models_redact_provider_key_and_serialize_entitlement(saas_app):
    app, tokens = saas_app
    with app.app_context():
        from models import AIAddonPackage, AIModelPolicy, AIProviderConfig, AIUsageLedger, TenantAIEntitlement

        provider = AIProviderConfig(
            id='provider-siliconflow',
            provider_code='siliconflow',
            display_name='SiliconFlow',
            base_url='https://api.siliconflow.cn/v1',
            api_key_encrypted='encrypted-secret',
            api_key_mask='sk-...abcd',
            enabled=True,
        )
        policy = AIModelPolicy(
            id='policy-assistant-standard',
            resource_domain='assistant',
            use_case='dialogue',
            tier='standard',
            provider_code='siliconflow',
            model_profile='standard',
            model='deepseek-ai/DeepSeek-V3.2',
            max_tokens=1200,
            enabled=True,
        )
        package = AIAddonPackage(
            code='ai_assistant',
            name='AI 助手包',
            resource_domains=['assistant'],
            allowed_tiers=['basic', 'standard'],
            default_monthly_quota=1000,
            is_active=True,
        )
        entitlement = TenantAIEntitlement(
            id='ent-alpha-assistant',
            tenant_id=tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['basic', 'standard'],
            monthly_quota=1000,
        )
        ledger = AIUsageLedger(
            id='usage-alpha-1',
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
            tier='standard',
            provider='siliconflow',
            model='deepseek-ai/DeepSeek-V3.2',
            status='success',
            units=1,
            request_id='req-alpha-1',
        )
        db.session.add_all([provider, policy, package, entitlement, ledger])
        db.session.commit()

        assert provider.to_dict()['hasApiKey'] is True
        assert 'apiKey' not in provider.to_dict()
        assert provider.to_dict(include_secret=True)['apiKeyEncrypted'] == 'encrypted-secret'
        assert entitlement.to_dict()['resourceDomain'] == 'assistant'
        assert entitlement.to_dict()['remainingQuota'] == 999
        assert ledger.to_dict()['resourceDomain'] == 'assistant'


def test_ai_governance_blocks_disabled_domain_before_provider_call(saas_app):
    app, tokens = saas_app
    with app.app_context():
        from services.ai_resource_governance import AIResourceDenied, assert_ai_resource_allowed, seed_ai_resource_defaults

        seed_ai_resource_defaults()
        with pytest.raises(AIResourceDenied) as exc:
            assert_ai_resource_allowed(
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                resource_domain='resume_ai',
                use_case='resume_analysis',
            )
        assert exc.value.code == 'AI_RESOURCE_DISABLED'


def test_ai_governance_allows_enabled_domain_and_blocks_quota(saas_app):
    app, tokens = saas_app
    with app.app_context():
        from models import AIUsageLedger
        from services.ai_resource_governance import (
            AIResourceDenied,
            assert_ai_resource_allowed,
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
            allowed_tiers=['basic', 'standard'],
            monthly_quota=1,
        )
        allowed = assert_ai_resource_allowed(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
        )
        assert allowed.resource_domain == 'assistant'
        db.session.add(AIUsageLedger(
            id='usage-alpha-assistant-quota',
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
            tier='standard',
            status='success',
            units=1,
        ))
        db.session.commit()

        with pytest.raises(AIResourceDenied) as exc:
            assert_ai_resource_allowed(
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                resource_domain='assistant',
                use_case='dialogue',
            )
        assert exc.value.code == 'AI_QUOTA_EXCEEDED'


def test_actual_call_quota_reservation_blocks_second_attempt_without_leaking_requests(saas_app):
    app, tokens = saas_app
    from services.ai_resource_governance import (
        AIResourceDenied,
        assert_ai_resource_allowed,
        grant_tenant_ai_entitlement,
        seed_ai_resource_defaults,
    )

    with app.app_context():
        seed_ai_resource_defaults()
        grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=1,
        )

    with app.test_request_context('/first-model-request'):
        # Route-level prechecks are authorization-only and must not consume a slot.
        assert_ai_resource_allowed(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
        )
        assert_ai_resource_allowed(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
        )
        assert_ai_resource_allowed(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
            reserve=True,
        )
        with pytest.raises(AIResourceDenied) as exc:
            assert_ai_resource_allowed(
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                resource_domain='assistant',
                use_case='dialogue',
                reserve=True,
            )
        assert exc.value.code == 'AI_QUOTA_EXCEEDED'

    with app.test_request_context('/next-model-request'):
        allowed = assert_ai_resource_allowed(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='dialogue',
            reserve=True,
        )
        assert allowed.used_this_month == 0


def test_llm_profile_governance_precheck_does_not_reserve_before_runtime(monkeypatch):
    from services import ai_resource_governance as governance
    from services.assistant_core import llm_client

    captured = {}

    def fake_authorize(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            tier='standard',
            entitlement_id='entitlement-test',
            tenant_id='tenant-test',
        )

    monkeypatch.setattr(governance, 'assert_ai_resource_allowed', fake_authorize)
    monkeypatch.setattr(
        llm_client,
        '_resolved_runtime',
        lambda **_kwargs: (SimpleNamespace(provider_code='saved', source='database'), 12),
    )

    llm_client._governance_for_profile(
        ctx=SimpleNamespace(user_id='user-test', tenant_id='tenant-test'),
        resource_domain='assistant',
        use_case='dialogue',
        profile='standard',
        messages=[{'role': 'user', 'content': 'hello'}],
        max_tokens=12,
    )

    assert captured.get('reserve', False) is False


def test_platform_provider_config_masks_secret_and_resolves_policy(saas_app):
    app, _tokens = saas_app
    with app.app_context():
        from services.ai_resource_governance import (
            mask_api_key,
            resolve_model_policy,
            save_model_policy,
            save_provider_config,
            seed_ai_resource_defaults,
        )

        seed_ai_resource_defaults()
        provider = save_provider_config('siliconflow', {
            'displayName': 'SiliconFlow',
            'baseUrl': 'https://api.siliconflow.cn/v1',
            'apiKey': 'sk-test-secret-abcd',
            'enabled': True,
        })
        assert provider.to_dict()['maskedApiKey'] == mask_api_key('sk-test-secret-abcd')
        assert 'sk-test-secret-abcd' not in str(provider.to_dict())

        save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'dialogue',
            'tier': 'standard',
            'providerCode': 'siliconflow',
            'modelProfile': 'standard',
            'model': 'deepseek-ai/DeepSeek-V3.2',
            'maxTokens': 1200,
            'enabled': True,
        })

        resolved = resolve_model_policy('assistant', 'dialogue', 'standard')
        assert resolved.provider_code == 'siliconflow'
        assert resolved.model == 'deepseek-ai/DeepSeek-V3.2'


@pytest.mark.parametrize(
    ('invalid_payload', 'expected_code'),
    [
        ({'providerCode': 'missing-provider'}, 'AI_PROVIDER_NOT_FOUND'),
        ({'providerCode': '   '}, 'AI_PROVIDER_NOT_FOUND'),
        ({'providerCode': 'disabled-provider'}, 'AI_PROVIDER_DISABLED'),
        ({'tier': 'vip'}, 'AI_TIER_INVALID'),
        ({'maxTokens': 0}, 'AI_MODEL_POLICY_INVALID'),
        ({'maxTokens': 'not-a-number'}, 'AI_MODEL_POLICY_INVALID'),
        ({'maxTokens': True}, 'AI_MODEL_POLICY_INVALID'),
        ({'maxTokens': 1.5}, 'AI_MODEL_POLICY_INVALID'),
        ({'model': '   '}, 'AI_MODEL_POLICY_INVALID'),
    ],
)
def test_model_policy_validation_is_stable_and_preserves_existing_row(
    saas_app,
    invalid_payload,
    expected_code,
):
    app, _tokens = saas_app
    with app.app_context():
        from models import AIModelPolicy
        from services.ai_resource_governance import (
            AIResourceDenied,
            save_model_policy,
            save_provider_config,
        )

        save_provider_config('valid-provider', {
            'displayName': 'Valid',
            'baseUrl': 'https://valid.example/v1',
            'apiKey': 'valid-secret',
            'enabled': True,
        })
        save_provider_config('disabled-provider', {
            'displayName': 'Disabled',
            'baseUrl': 'https://disabled.example/v1',
            'apiKey': 'disabled-secret',
            'enabled': False,
        })
        row = save_model_policy({
            'resourceDomain': 'system_ai',
            'useCase': 'policy-validation',
            'tier': 'standard',
            'providerCode': 'valid-provider',
            'modelProfile': 'standard',
            'model': 'stable-model',
            'maxTokens': 777,
            'enabled': True,
        })
        original = (row.resource_domain, row.use_case, row.tier, row.provider_code, row.model, row.max_tokens)
        payload = {
            'id': row.id,
            'resourceDomain': row.resource_domain,
            'useCase': row.use_case,
            'tier': row.tier,
            'providerCode': row.provider_code,
            'modelProfile': row.model_profile,
            'model': row.model,
            'maxTokens': row.max_tokens,
            'enabled': True,
            **invalid_payload,
        }

        with pytest.raises(AIResourceDenied) as exc:
            save_model_policy(payload)
        assert exc.value.code == expected_code
        assert exc.value.status_code == 400
        db.session.rollback()
        persisted = db.session.get(AIModelPolicy, row.id)
        assert (
            persisted.resource_domain,
            persisted.use_case,
            persisted.tier,
            persisted.provider_code,
            persisted.model,
            persisted.max_tokens,
        ) == original


def test_model_policy_scope_conflict_preserves_both_rows(saas_app):
    app, _tokens = saas_app
    with app.app_context():
        from models import AIModelPolicy
        from services.ai_resource_governance import (
            AIResourceDenied,
            save_model_policy,
            save_provider_config,
        )

        save_provider_config('scope-provider', {
            'displayName': 'Scope Provider',
            'baseUrl': 'https://scope.example/v1',
            'apiKey': 'scope-secret',
            'enabled': True,
        })
        first = save_model_policy({
            'resourceDomain': 'system_ai',
            'useCase': 'scope-first',
            'tier': 'standard',
            'providerCode': 'scope-provider',
            'model': 'scope-model-first',
            'maxTokens': 500,
        })
        second = save_model_policy({
            'resourceDomain': 'system_ai',
            'useCase': 'scope-second',
            'tier': 'standard',
            'providerCode': 'scope-provider',
            'model': 'scope-model-second',
            'maxTokens': 600,
        })

        with pytest.raises(AIResourceDenied) as exc:
            save_model_policy({
                'id': first.id,
                'resourceDomain': second.resource_domain,
                'useCase': second.use_case,
                'tier': second.tier,
                'providerCode': first.provider_code,
                'model': 'must-not-persist',
                'maxTokens': 700,
            })
        assert exc.value.code == 'AI_MODEL_POLICY_CONFLICT'
        assert exc.value.status_code == 409
        db.session.rollback()
        persisted_first = db.session.get(AIModelPolicy, first.id)
        persisted_second = db.session.get(AIModelPolicy, second.id)
        assert (persisted_first.use_case, persisted_first.model, persisted_first.max_tokens) == (
            'scope-first', 'scope-model-first', 500,
        )
        assert (persisted_second.use_case, persisted_second.model, persisted_second.max_tokens) == (
            'scope-second', 'scope-model-second', 600,
        )


def test_platform_model_policy_scope_conflict_returns_stable_409(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    with app.app_context():
        from services.ai_resource_governance import save_model_policy, save_provider_config

        save_provider_config('route-scope-provider', {
            'displayName': 'Route Scope Provider',
            'baseUrl': 'https://route-scope.example/v1',
            'apiKey': 'route-scope-secret',
            'enabled': True,
        })
        first = save_model_policy({
            'resourceDomain': 'system_ai',
            'useCase': 'route-scope-first',
            'tier': 'standard',
            'providerCode': 'route-scope-provider',
            'model': 'route-model-first',
            'maxTokens': 500,
        })
        second = save_model_policy({
            'resourceDomain': 'system_ai',
            'useCase': 'route-scope-second',
            'tier': 'standard',
            'providerCode': 'route-scope-provider',
            'model': 'route-model-second',
            'maxTokens': 600,
        })
        first_id = first.id
        second_id = second.id

    response = platform.put(f'/api/platform/ai/model-policies/{first_id}', json={
        'resourceDomain': 'system_ai',
        'useCase': 'route-scope-second',
        'tier': 'standard',
        'providerCode': 'route-scope-provider',
        'model': 'must-not-persist',
        'maxTokens': 700,
    })

    assert response.status_code == 409
    assert response.get_json()['code'] == 'AI_MODEL_POLICY_CONFLICT'
    with app.app_context():
        from models import AIModelPolicy

        assert db.session.get(AIModelPolicy, first_id).use_case == 'route-scope-first'
        assert db.session.get(AIModelPolicy, second_id).use_case == 'route-scope-second'


def test_platform_provider_config_and_audit_commit_once(saas_app, monkeypatch):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    from routes import platform as platform_routes

    original_commit = db.session.commit
    commits = {'count': 0}

    def counted_commit():
        commits['count'] += 1
        return original_commit()

    monkeypatch.setattr(db.session, 'commit', counted_commit)
    response = platform.put('/api/platform/ai/providers/atomic-provider', json={
        'displayName': 'Atomic Provider',
        'baseUrl': 'https://atomic.example/v1',
        'apiKey': 'atomic-secret',
        'enabled': True,
    })

    assert response.status_code == 200
    assert commits['count'] == 1
    with app.app_context():
        from models import AIProviderConfig, PlatformOperationLog

        assert AIProviderConfig.query.filter_by(provider_code='atomic-provider').one()
        assert PlatformOperationLog.query.filter_by(
            action='update_ai_provider', target_id='atomic-provider',
        ).one()
    del platform_routes


def test_platform_provider_route_rejects_invalid_base_url_atomically(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    with app.app_context():
        from services.ai_resource_governance import save_provider_config

        original = save_provider_config('route-url-validation', {
            'displayName': 'Route Original',
            'baseUrl': 'https://route-original.example/v1',
            'apiKey': 'route-original-secret',
            'enabled': True,
        })
        original_secret = original.api_key_encrypted

    response = platform.put('/api/platform/ai/providers/route-url-validation', json={
        'displayName': 'Route Must Not Persist',
        'baseUrl': 'not-a-provider-url',
        'apiKey': 'route-replacement-secret',
        'enabled': False,
    })

    assert response.status_code == 400
    assert response.get_json()['code'] == 'AI_PROVIDER_BASE_URL_INVALID'
    assert 'route-original-secret' not in str(response.get_json())
    assert 'route-replacement-secret' not in str(response.get_json())
    with app.app_context():
        from models import AIProviderConfig, PlatformOperationLog

        row = AIProviderConfig.query.filter_by(provider_code='route-url-validation').one()
        assert row.display_name == 'Route Original'
        assert row.base_url == 'https://route-original.example/v1'
        assert row.api_key_encrypted == original_secret
        assert row.enabled is True
        assert PlatformOperationLog.query.filter_by(
            action='update_ai_provider', target_id='route-url-validation',
        ).count() == 0


@pytest.mark.parametrize(
    'invalid_base_url',
    ['', 'not-a-provider-url', 'https://bad host.example/v1'],
)
def test_provider_service_rejects_explicit_invalid_base_url_before_mutation(
    saas_app,
    invalid_base_url,
):
    app, _tokens = saas_app
    with app.app_context():
        from services.ai_resource_governance import AIResourceDenied, save_provider_config

        original = save_provider_config('service-url-validation', {
            'displayName': 'Service Original',
            'baseUrl': 'https://service-original.example/v1',
            'apiKey': 'service-original-secret',
            'enabled': True,
        })
        original_secret = original.api_key_encrypted
        original_mask = original.api_key_mask

        with pytest.raises(AIResourceDenied) as exc:
            save_provider_config('service-url-validation', {
                'displayName': 'Service Must Not Persist',
                'baseUrl': invalid_base_url,
                'apiKey': 'service-replacement-secret',
                'enabled': False,
            })

        assert exc.value.code == 'AI_PROVIDER_BASE_URL_INVALID'
        row = type(original).query.filter_by(provider_code='service-url-validation').one()
        assert row.display_name == 'Service Original'
        assert row.base_url == 'https://service-original.example/v1'
        assert row.api_key_encrypted == original_secret
        assert row.api_key_mask == original_mask
        assert row.enabled is True


def test_provider_service_omitted_url_and_key_preserve_saved_runtime(saas_app):
    app, _tokens = saas_app
    with app.app_context():
        from services.ai_resource_governance import save_provider_config

        original = save_provider_config('service-preserve-provider', {
            'displayName': 'Before Preserve',
            'baseUrl': 'https://preserved-provider.example/v1/',
            'apiKey': 'preserved-provider-secret',
            'enabled': True,
        })
        original_secret = original.api_key_encrypted
        original_mask = original.api_key_mask

        updated = save_provider_config('service-preserve-provider', {
            'displayName': 'After Preserve',
            'enabled': False,
        })

        assert updated.display_name == 'After Preserve'
        assert updated.base_url == 'https://preserved-provider.example/v1'
        assert updated.api_key_encrypted == original_secret
        assert updated.api_key_mask == original_mask
        assert updated.enabled is False


def test_provider_service_new_provider_requires_explicit_base_url(saas_app):
    app, _tokens = saas_app
    with app.app_context():
        from models import AIProviderConfig
        from services.ai_resource_governance import AIResourceDenied, save_provider_config

        with pytest.raises(AIResourceDenied) as exc:
            save_provider_config('new-provider-without-url', {
                'displayName': 'Missing URL',
                'apiKey': 'must-not-persist',
                'enabled': True,
            })

        assert exc.value.code == 'AI_PROVIDER_BASE_URL_INVALID'
        assert AIProviderConfig.query.filter_by(provider_code='new-provider-without-url').count() == 0


def test_platform_provider_audit_failure_rolls_back_config(saas_app, monkeypatch):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    from routes import platform as platform_routes

    with app.app_context():
        from services.ai_resource_governance import save_provider_config

        save_provider_config('audit-rollback-provider', {
            'displayName': 'Before Audit Failure',
            'baseUrl': 'https://before-audit.example/v1',
            'apiKey': 'before-audit-secret',
            'enabled': True,
        })

    monkeypatch.setattr(
        platform_routes,
        '_platform_log',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('audit write failed')),
    )
    with pytest.raises(RuntimeError, match='audit write failed'):
        platform.put('/api/platform/ai/providers/audit-rollback-provider', json={
            'displayName': 'Must Roll Back',
            'baseUrl': 'https://must-rollback.example/v1',
            'enabled': False,
        })

    with app.app_context():
        from models import AIProviderConfig

        row = AIProviderConfig.query.filter_by(provider_code='audit-rollback-provider').one()
        assert row.display_name == 'Before Audit Failure'
        assert row.base_url == 'https://before-audit.example/v1'
        assert row.enabled is True


def test_platform_policy_final_commit_failure_rolls_back_config_and_audit(saas_app, monkeypatch):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    from routes import platform as platform_routes

    with app.app_context():
        from services.ai_resource_governance import save_model_policy, save_provider_config

        save_provider_config('commit-rollback-provider', {
            'displayName': 'Commit Rollback Provider',
            'baseUrl': 'https://commit-rollback.example/v1',
            'apiKey': 'commit-rollback-secret',
            'enabled': True,
        })
        policy = save_model_policy({
            'resourceDomain': 'system_ai',
            'useCase': 'commit-rollback',
            'tier': 'standard',
            'providerCode': 'commit-rollback-provider',
            'model': 'before-commit-failure',
            'maxTokens': 500,
        })
        policy_id = policy.id

    log_called = {'value': False}
    original_log = platform_routes._platform_log

    def observed_log(*args, **kwargs):
        log_called['value'] = True
        return original_log(*args, **kwargs)

    monkeypatch.setattr(platform_routes, '_platform_log', observed_log)
    original_commit = db.session.commit
    monkeypatch.setattr(
        db.session,
        'commit',
        lambda: (_ for _ in ()).throw(RuntimeError('final commit failed')),
    )
    with pytest.raises(RuntimeError, match='final commit failed'):
        platform.put(f'/api/platform/ai/model-policies/{policy_id}', json={
            'resourceDomain': 'system_ai',
            'useCase': 'commit-rollback',
            'tier': 'standard',
            'providerCode': 'commit-rollback-provider',
            'model': 'must-roll-back',
            'maxTokens': 700,
        })

    assert log_called['value'] is True
    monkeypatch.setattr(db.session, 'commit', original_commit)
    with app.app_context():
        from models import AIModelPolicy, PlatformOperationLog

        assert db.session.get(AIModelPolicy, policy_id).model == 'before-commit-failure'
        assert PlatformOperationLog.query.filter_by(
            action='update_ai_model_policy', target_id=policy_id,
        ).count() == 0


def test_asr_uses_saved_provider_policy_secret_and_model(saas_app, monkeypatch, tmp_path):
    app, tokens = saas_app
    audio = tmp_path / 'voice.webm'
    audio.write_bytes(b'voice')
    captured = {}

    def fake_post(url, *, headers, files, data, timeout):
        captured.update(url=url, headers=headers, files=files, data=data, timeout=timeout)
        return SimpleNamespace(ok=True, json=lambda: {'text': '保存策略转写'}, status_code=200, text='')

    with app.app_context():
        from services import ai_resource_governance as governance

        governance.grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=10,
        )
        governance.save_provider_config('saved-asr', {
            'displayName': 'Saved ASR',
            'baseUrl': 'https://saved-asr.example/v1',
            'apiKey': 'saved-asr-secret',
            'enabled': True,
        })
        governance.save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'assistant_voice_transcription',
            'tier': 'standard',
            'providerCode': 'saved-asr',
            'modelProfile': 'asr',
            'model': 'saved-asr-model',
            'maxTokens': 1200,
            'enabled': True,
        })
        monkeypatch.setattr(governance.requests, 'post', fake_post)

        result = governance.transcribe_audio_with_governance(
            str(audio),
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='assistant_voice_transcription',
            request_id='saved-asr-request',
        )
        from models import AIUsageLedger

        ledger = AIUsageLedger.query.filter_by(request_id='saved-asr-request').one()

    assert result['success'] is True
    assert captured['url'] == 'https://saved-asr.example/v1/audio/transcriptions'
    assert captured['headers']['Authorization'] == 'Bearer saved-asr-secret'
    assert captured['data']['model'] == 'saved-asr-model'
    assert ledger.provider == 'saved-asr'
    assert ledger.model == 'saved-asr-model'
    assert ledger.meta_json['runtimeSource'] == 'database'


def test_asr_missing_file_does_not_reserve_request_quota_or_write_ledger(
    saas_app,
    monkeypatch,
    tmp_path,
):
    app, tokens = saas_app
    missing_audio = tmp_path / 'missing.webm'
    with app.app_context():
        from services import ai_resource_governance as governance

        governance.seed_ai_resource_defaults()
        governance.grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=1,
        )
        governance.save_provider_config('asr-preflight-provider', {
            'displayName': 'ASR Preflight Provider',
            'baseUrl': 'https://asr-preflight.example/v1',
            'apiKey': 'asr-preflight-secret',
            'enabled': True,
        })
        governance.save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'assistant_voice_transcription',
            'tier': 'standard',
            'providerCode': 'asr-preflight-provider',
            'modelProfile': 'asr',
            'model': 'asr-preflight-model',
            'maxTokens': 1200,
            'enabled': True,
        })
        monkeypatch.setattr(
            governance.requests,
            'post',
            lambda *_args, **_kwargs: pytest.fail('missing file must not reach provider HTTP'),
        )

    with app.test_request_context('/asr-missing-preflight'):
        from models import AIUsageLedger
        from services import ai_resource_governance as governance

        result = governance.transcribe_audio_with_governance(
            str(missing_audio),
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='assistant_voice_transcription',
            request_id='asr-missing-preflight',
        )
        assert result['success'] is False
        assert AIUsageLedger.query.filter_by(request_id='asr-missing-preflight').count() == 0

        allowed = governance.assert_ai_resource_allowed(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='assistant_voice_transcription',
            reserve=True,
        )
        assert allowed.used_this_month == 0


def test_asr_runtime_resolution_failure_does_not_write_usage_or_call_http(
    saas_app,
    monkeypatch,
    tmp_path,
):
    app, tokens = saas_app
    audio = tmp_path / 'runtime-failure.webm'
    audio.write_bytes(b'audio')
    with app.app_context():
        from services import ai_resource_governance as governance

        governance.seed_ai_resource_defaults()
        governance.grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=1,
        )
        provider = governance.save_provider_config('asr-invalid-runtime', {
            'displayName': 'ASR Invalid Runtime',
            'baseUrl': 'https://asr-invalid-runtime.example/v1',
            'apiKey': 'valid-before-corruption',
            'enabled': True,
        })
        governance.save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'assistant_voice_transcription',
            'tier': 'standard',
            'providerCode': provider.provider_code,
            'modelProfile': 'asr',
            'model': 'invalid-runtime-asr-model',
            'maxTokens': 1200,
            'enabled': True,
        })
        provider.api_key_encrypted = 'corrupt-asr-secret'
        db.session.commit()
        monkeypatch.setattr(
            governance.requests,
            'post',
            lambda *_args, **_kwargs: pytest.fail('invalid runtime must not call ASR HTTP'),
        )

    with app.test_request_context('/asr-runtime-failure'):
        from services import ai_resource_governance as governance

        result = governance.transcribe_audio_with_governance(
            str(audio),
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='assistant_voice_transcription',
            request_id='asr-runtime-failure-no-usage',
        )

    assert result['success'] is False
    assert result['code'] == 'AI_PROVIDER_SECRET_INVALID'
    with app.app_context():
        from models import AIUsageLedger, AssistantAuditLog

        audit = AssistantAuditLog.query.filter_by(request_id='asr-runtime-failure-no-usage').one()
        assert audit.status == 'error'
        assert audit.resource_domain == 'assistant'
        assert audit.prompt_messages == []
        assert 'corrupt-asr-secret' not in str(audit.to_dict(include_payload=True))
        assert AIUsageLedger.query.filter_by(request_id='asr-runtime-failure-no-usage').count() == 0


@pytest.mark.parametrize('invalid_payload', ['raises', 'non_dict'])
def test_asr_http_invalid_json_writes_one_error_audit_and_ledger(
    saas_app,
    monkeypatch,
    tmp_path,
    invalid_payload,
):
    app, tokens = saas_app
    audio = tmp_path / f'invalid-json-{invalid_payload}.webm'
    audio.write_bytes(b'audio')
    request_id = f'asr-invalid-json-{invalid_payload}'

    def invalid_json():
        if invalid_payload == 'raises':
            raise ValueError('provider returned malformed json')
        return ['not', 'a', 'mapping']

    with app.app_context():
        from services import ai_resource_governance as governance

        governance.seed_ai_resource_defaults()
        governance.grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=2,
        )
        governance.save_provider_config('asr-invalid-json-provider', {
            'displayName': 'ASR Invalid JSON Provider',
            'baseUrl': 'https://asr-invalid-json.example/v1',
            'apiKey': 'asr-invalid-json-secret',
            'enabled': True,
        })
        governance.save_model_policy({
            'resourceDomain': 'assistant',
            'useCase': 'assistant_voice_transcription',
            'tier': 'standard',
            'providerCode': 'asr-invalid-json-provider',
            'modelProfile': 'asr',
            'model': 'asr-invalid-json-model',
            'maxTokens': 1200,
            'enabled': True,
        })
        monkeypatch.setattr(
            governance.requests,
            'post',
            lambda *_args, **_kwargs: SimpleNamespace(
                ok=True,
                status_code=200,
                text='invalid provider payload',
                json=invalid_json,
            ),
        )

    with app.test_request_context(f'/asr-invalid-json/{invalid_payload}'):
        from services import ai_resource_governance as governance

        result = governance.transcribe_audio_with_governance(
            str(audio),
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='assistant_voice_transcription',
            request_id=request_id,
        )

    assert result['success'] is False
    assert result['code'] == 'AI_PROVIDER_INVALID_RESPONSE'
    with app.app_context():
        from models import AIUsageLedger, AssistantAuditLog

        audit = AssistantAuditLog.query.filter_by(request_id=request_id).one()
        ledger = AIUsageLedger.query.filter_by(request_id=request_id).one()
        assert audit.status == 'error'
        assert ledger.status == 'error'
        assert ledger.error_code == 'AI_PROVIDER_INVALID_RESPONSE'
        assert ledger.assistant_audit_log_id == audit.id


def test_asr_never_uses_environment_when_operator_provider_has_no_policy(
    saas_app,
    monkeypatch,
    tmp_path,
):
    app, tokens = saas_app
    audio = tmp_path / 'voice.webm'
    audio.write_bytes(b'voice')
    called = {'value': False}
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'environment-key-must-not-run')

    with app.app_context():
        from services import ai_resource_governance as governance

        governance.grant_tenant_ai_entitlement(
            tokens['alpha_id'],
            resource_domain='assistant',
            package_code='ai_assistant',
            enabled=True,
            selected_tier='standard',
            allowed_tiers=['standard'],
            monthly_quota=10,
        )
        governance.save_provider_config('operator-without-policy', {
            'displayName': 'Operator Provider',
            'baseUrl': 'https://operator.example/v1',
            'apiKey': 'operator-secret',
            'enabled': True,
        })
        monkeypatch.setattr(
            governance.requests,
            'post',
            lambda *_args, **_kwargs: called.update(value=True),
        )

        result = governance.transcribe_audio_with_governance(
            str(audio),
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='assistant',
            use_case='assistant_voice_transcription',
            request_id='missing-asr-policy',
        )

    assert result['success'] is False
    assert result['code'] == 'AI_MODEL_POLICY_MISSING'
    assert called['value'] is False


@pytest.mark.parametrize(
    ('resource_domain', 'use_case', 'tier'),
    [
        ('assistant', 'assistant_voice_transcription', 'basic'),
        ('assistant', 'assistant_voice_transcription', 'standard'),
        ('interview_ai', 'interview_recording_transcription', 'basic'),
        ('interview_ai', 'interview_recording_transcription', 'standard'),
        ('interview_ai', 'interview_recording_transcription', 'professional'),
    ],
)
def test_seeded_asr_policy_wins_for_each_supported_tier(
    saas_app,
    monkeypatch,
    resource_domain,
    use_case,
    tier,
):
    app, _tokens = saas_app
    monkeypatch.setenv('SILICONFLOW_API_KEY', 'bootstrap-asr-key')

    with app.app_context():
        from services.ai_resource_governance import DEFAULT_ASR_MODEL, seed_ai_resource_defaults
        from services.ai_runtime_provider import resolve_ai_runtime

        seed_ai_resource_defaults()
        runtime = resolve_ai_runtime(resource_domain, use_case, tier)

    assert runtime.model == DEFAULT_ASR_MODEL


def test_ai_usage_audit_never_commits_or_rolls_back_pending_interview_fields(
    saas_app,
    monkeypatch,
):
    app, tokens = saas_app
    with app.app_context():
        from models import AIUsageLedger, Interview, Job, Resume
        from services import ai_resource_governance as governance

        db.session.add(Job(
            id='job-audit-uow',
            tenant_id=tokens['alpha_id'],
            title='审计事务岗位',
            description='测试',
        ))
        db.session.add(Resume(
            id='resume-audit-uow',
            tenant_id=tokens['alpha_id'],
            job_id='job-audit-uow',
            candidate_name='审计候选人',
            file_url='/uploads/audit.pdf',
        ))
        interview = Interview(
            id='interview-audit-uow',
            tenant_id=tokens['alpha_id'],
            job_id='job-audit-uow',
            resume_id='resume-audit-uow',
            scheduled_at=db.func.now(),
            recording_url='/uploads/original.webm',
            transcript='原始文本',
        )
        db.session.add(interview)
        db.session.commit()

        interview.recording_url = '/uploads/pending-success.webm'
        interview.transcript = '待回滚成功审计文本'
        governance.record_ai_usage(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='interview_ai',
            use_case='audit_uow_success',
            tier='standard',
            provider='saved',
            model='asr-model',
            status='success',
            request_id='audit-uow-success',
        )
        db.session.rollback()
        restored = db.session.get(Interview, interview.id)
        assert restored.recording_url == '/uploads/original.webm'
        assert restored.transcript == '原始文本'
        assert AIUsageLedger.query.filter_by(request_id='audit-uow-success').count() == 1

        class FailingUsageSession:
            def add(self, _row):
                return None

            def commit(self):
                raise RuntimeError('usage audit commit failed')

            def rollback(self):
                return None

            def close(self):
                return None

        monkeypatch.setattr(
            governance,
            '_new_usage_session',
            lambda: FailingUsageSession(),
            raising=False,
        )
        restored.recording_url = '/uploads/pending-failure.webm'
        restored.transcript = '待回滚失败审计文本'
        governance.record_ai_usage(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            resource_domain='interview_ai',
            use_case='audit_uow_failure',
            tier='standard',
            provider='saved',
            model='asr-model',
            status='error',
            request_id='audit-uow-failure',
        )
        db.session.rollback()
        restored_after_failure = db.session.get(Interview, interview.id)
        assert restored_after_failure.recording_url == '/uploads/original.webm'
        assert restored_after_failure.transcript == '原始文本'
        assert AIUsageLedger.query.filter_by(request_id='audit-uow-failure').count() == 0


def test_assistant_audit_uses_independent_uow_for_pending_interview_fields(
    saas_app,
    monkeypatch,
):
    app, tokens = saas_app
    with app.app_context():
        from models import AssistantAuditLog, Interview, Job, Resume
        from services.assistant_core import audit

        db.session.add(Job(
            id='job-assistant-audit-uow',
            tenant_id=tokens['alpha_id'],
            title='助手审计事务岗位',
            description='测试',
        ))
        db.session.add(Resume(
            id='resume-assistant-audit-uow',
            tenant_id=tokens['alpha_id'],
            job_id='job-assistant-audit-uow',
            candidate_name='助手审计候选人',
            file_url='/uploads/assistant-audit.pdf',
        ))
        interview = Interview(
            id='interview-assistant-audit-uow',
            tenant_id=tokens['alpha_id'],
            job_id='job-assistant-audit-uow',
            resume_id='resume-assistant-audit-uow',
            scheduled_at=db.func.now(),
            recording_url='/uploads/assistant-original.webm',
            transcript='助手原始文本',
        )
        db.session.add(interview)
        db.session.commit()

        interview.recording_url = '/uploads/assistant-pending.webm'
        interview.transcript = '助手待回滚文本'
        audit.record_llm_call(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            session_id=None,
            request_id='assistant-audit-uow-success',
            provider='saved',
            model='saved-model',
            model_profile='standard',
            use_case='assistant_audit_uow',
            messages=[{'role': 'user', 'content': '测试'}],
            response_content='成功',
            resource_domain='assistant',
            ai_tier='standard',
        )
        db.session.rollback()
        restored = db.session.get(Interview, interview.id)
        assert restored.recording_url == '/uploads/assistant-original.webm'
        assert restored.transcript == '助手原始文本'
        assert AssistantAuditLog.query.filter_by(request_id='assistant-audit-uow-success').count() == 1

        class FailingAuditSession:
            def add(self, _row):
                return None

            def flush(self):
                return None

            def commit(self):
                raise RuntimeError('assistant audit commit failed')

            def rollback(self):
                return None

            def close(self):
                return None

        monkeypatch.setattr(
            audit,
            '_new_audit_session',
            lambda: FailingAuditSession(),
            raising=False,
        )
        restored.recording_url = '/uploads/assistant-failing.webm'
        restored.transcript = '助手失败待回滚文本'
        audit.record_llm_call(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            session_id=None,
            request_id='assistant-audit-uow-failure',
            provider='saved',
            model='saved-model',
            model_profile='standard',
            use_case='assistant_audit_uow_failure',
            messages=[{'role': 'user', 'content': '测试失败'}],
            response_content=None,
            resource_domain='assistant',
            ai_tier='standard',
            status='error',
        )
        db.session.rollback()
        restored_after_failure = db.session.get(Interview, interview.id)
        assert restored_after_failure.recording_url == '/uploads/assistant-original.webm'
        assert restored_after_failure.transcript == '助手原始文本'
        assert AssistantAuditLog.query.filter_by(request_id='assistant-audit-uow-failure').count() == 0


def test_assistant_audit_commit_failure_rolls_back_closes_and_logs_one_safe_event(
    saas_app,
    monkeypatch,
    caplog,
):
    app, tokens = saas_app
    with app.app_context():
        from services.assistant_core import audit

        prompt_secret = 'prompt-private-value'
        response_secret = 'response-private-value'
        api_key_secret = 'sk-private-api-key'
        generic_secret = 'generic-private-secret'

        class CommitFailingAuditSession:
            def __init__(self):
                self.commit_calls = 0
                self.rollback_calls = 0
                self.close_calls = 0

            def add(self, _row):
                return None

            def flush(self):
                return None

            def commit(self):
                self.commit_calls += 1
                raise RuntimeError(
                    f'audit commit failed: {prompt_secret} {response_secret} '
                    f'{api_key_secret} {generic_secret}'
                )

            def rollback(self):
                self.rollback_calls += 1

            def close(self):
                self.close_calls += 1

        failing_session = CommitFailingAuditSession()
        monkeypatch.setattr(audit, '_new_audit_session', lambda: failing_session)

        exception_calls = []
        real_logger_exception = audit.logger.exception

        def capture_logger_exception(message, *args, **kwargs):
            exception_calls.append((message, args, kwargs))
            return real_logger_exception(message, *args, **kwargs)

        monkeypatch.setattr(audit.logger, 'exception', capture_logger_exception)

        with caplog.at_level(logging.ERROR, logger=audit.logger.name):
            result = audit.record_llm_call(
                tenant_id=tokens['alpha_id'],
                user_id='alpha-admin',
                session_id=None,
                request_id='assistant-audit-commit-failure',
                provider='saved-provider',
                model='saved-model',
                model_profile='standard',
                use_case='assistant_audit_commit_failure',
                messages=[{'role': 'user', 'content': prompt_secret}],
                response_content=response_secret,
                response_meta={'apiKey': api_key_secret},
                status='error',
                error_message=generic_secret,
            )

        assert result is None
        assert failing_session.commit_calls == 1
        assert failing_session.rollback_calls == 1
        assert failing_session.close_calls == 1
        assert exception_calls == [
            ('assistant_audit_record_failed', (), {'exc_info': False}),
        ]
        records = [record for record in caplog.records if record.name == audit.logger.name]
        assert len(records) == 1
        assert records[0].getMessage() == 'assistant_audit_record_failed'
        assert not records[0].exc_info
        for sensitive_value in (
            prompt_secret,
            response_secret,
            api_key_secret,
            generic_secret,
        ):
            assert sensitive_value not in caplog.text


@pytest.mark.parametrize('ownership_mismatch', ['tenant_id', 'user_id'])
def test_assistant_audit_does_not_link_to_session_owned_by_another_principal(
    saas_app,
    ownership_mismatch,
):
    app, tokens = saas_app
    with app.app_context():
        from models import AssistantAuditLog, AssistantSession, User
        from services.assistant_core import audit

        if ownership_mismatch == 'tenant_id':
            foreign_session = AssistantSession(
                id='assistant-audit-foreign-tenant-session',
                tenant_id=tokens['beta_id'],
                user_id='beta-admin',
                title='Foreign tenant session',
                messages=[],
                is_active=True,
                message_count=0,
            )
        else:
            db.session.add(User(
                id='alpha-other-audit-user',
                tenant_id=tokens['alpha_id'],
                email='alpha-other-audit@example.com',
                password_hash='unused',
                name='Alpha Other Audit User',
                role='admin',
                status='active',
            ))
            foreign_session = AssistantSession(
                id='assistant-audit-foreign-user-session',
                tenant_id=tokens['alpha_id'],
                user_id='alpha-other-audit-user',
                title='Foreign user session',
                messages=[],
                is_active=True,
                message_count=0,
            )
        db.session.add(foreign_session)
        db.session.commit()

        request_id = f'assistant-audit-{ownership_mismatch}-mismatch'
        audit.record_llm_call(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            session_id=foreign_session.id,
            request_id=request_id,
            provider='saved-provider',
            model='saved-model',
            model_profile='standard',
            use_case='assistant_audit_session_ownership',
            messages=[{'role': 'user', 'content': 'ownership check'}],
            response_content='unlinked audit response',
            response_meta={'runtimeSource': 'database'},
        )
        db.session.remove()

        row = AssistantAuditLog.query.filter_by(request_id=request_id).one()
        assert row.session_id is None
        assert row.response_meta == {
            'runtimeSource': 'database',
            'auditLinkSessionId': foreign_session.id,
        }


def test_first_assistant_session_persists_unlinked_audit_then_links_after_turn_commit(tmp_path):
    import sqlite3
    import time

    from flask import Flask
    from sqlalchemy import event

    database_path = tmp_path / 'assistant-fk.db'
    app = Flask('assistant-fk-regression')
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=f'sqlite:///{database_path.as_posix()}',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'connect_args': {'timeout': 0.05}},
    )
    db.init_app(app)

    with app.app_context():
        from models import Tenant, User
        from services.assistant_core import audit, memory

        @event.listens_for(db.engine, 'connect')
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.close()

        db.create_all()
        db.session.add(Tenant(
            id='tenant-first-session',
            name='首次会话企业',
            slug='first-session',
            status='active',
        ))
        db.session.add(User(
            id='user-first-session',
            tenant_id='tenant-first-session',
            email='first-session@example.com',
            password_hash='unused',
            name='首次会话用户',
            role='admin',
            status='active',
        ))
        db.session.commit()

        ctx = memory.build_context(
            'user-first-session',
            request_id='first-session-request',
        )
        assert ctx.session_id

        started = time.monotonic()
        audit.record_llm_call(
            tenant_id='tenant-first-session',
            user_id='user-first-session',
            session_id=ctx.session_id,
            request_id='first-session-request',
            provider='saved-provider',
            model='saved-model',
            model_profile='standard',
            use_case='first_session_audit',
            messages=[{'role': 'user', 'content': '首次问题'}],
            response_content='首次回答',
            response_meta={'runtimeSource': 'database'},
            resource_domain='assistant',
            ai_tier='standard',
        )
        assert time.monotonic() - started < 0.5

        with sqlite3.connect(database_path) as observer:
            observer.execute('PRAGMA foreign_keys=ON')
            assert observer.execute('SELECT COUNT(*) FROM assistant_sessions').fetchone()[0] == 0
            audit_before_turn = observer.execute(
                'SELECT id, session_id, tenant_id FROM assistant_audit_logs WHERE request_id = ?',
                ('first-session-request',),
            ).fetchone()
            ledger_before_turn = observer.execute(
                'SELECT assistant_audit_log_id, tenant_id FROM ai_usage_ledger WHERE request_id = ?',
                ('first-session-request',),
            ).fetchone()

        assert audit_before_turn[1:] == (None, 'tenant-first-session')
        assert ledger_before_turn == (audit_before_turn[0], 'tenant-first-session')
        assert not hasattr(audit, '_PENDING_AUDITS')

        saved_session_id = memory.save_turn(
            user_id='user-first-session',
            session_id=ctx.session_id,
            request_id='first-session-request',
            question='首次问题',
            summary='首次回答',
        )
        assert saved_session_id == ctx.session_id
        db.session.remove()

        with sqlite3.connect(database_path) as observer:
            observer.execute('PRAGMA foreign_keys=ON')
            session_row = observer.execute(
                'SELECT id FROM assistant_sessions WHERE id = ?',
                (ctx.session_id,),
            ).fetchone()
            audit_row = observer.execute(
                'SELECT id, session_id, tenant_id FROM assistant_audit_logs WHERE request_id = ?',
                ('first-session-request',),
            ).fetchone()
            ledger_row = observer.execute(
                'SELECT assistant_audit_log_id, tenant_id FROM ai_usage_ledger WHERE request_id = ?',
                ('first-session-request',),
            ).fetchone()

        assert session_row == (ctx.session_id,)
        assert audit_row[0] == audit_before_turn[0]
        assert audit_row[1:] == (ctx.session_id, 'tenant-first-session')
        assert ledger_row == (audit_row[0], 'tenant-first-session')


def test_reused_request_id_does_not_link_an_abandoned_audit_to_a_new_session(saas_app):
    app, tokens = saas_app
    with app.app_context():
        from models import AIUsageLedger, AssistantAuditLog
        from services.assistant_core import audit, memory

        abandoned = memory.build_context('alpha-admin', request_id='reused-audit-request')
        audit.record_llm_call(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            session_id=abandoned.session_id,
            request_id='reused-audit-request',
            provider='saved-provider',
            model='saved-model',
            model_profile='standard',
            use_case='reused_request_old',
            messages=[{'role': 'user', 'content': 'old-sensitive-prompt'}],
            response_content='old-response',
            resource_domain='assistant',
            ai_tier='standard',
        )
        db.session.rollback()

        current = memory.build_context('alpha-admin', request_id='reused-audit-request')
        assert current.session_id != abandoned.session_id
        audit.record_llm_call(
            tenant_id=tokens['alpha_id'],
            user_id='alpha-admin',
            session_id=current.session_id,
            request_id='reused-audit-request',
            provider='saved-provider',
            model='saved-model',
            model_profile='standard',
            use_case='reused_request_current',
            messages=[{'role': 'user', 'content': 'current-prompt'}],
            response_content='current-response',
            resource_domain='assistant',
            ai_tier='standard',
        )
        assert memory.save_turn(
            user_id='alpha-admin',
            session_id=current.session_id,
            request_id='reused-audit-request',
            question='current-prompt',
            summary='current-response',
        ) == current.session_id

        old_row = AssistantAuditLog.query.filter_by(use_case='reused_request_old').one()
        current_row = AssistantAuditLog.query.filter_by(use_case='reused_request_current').one()
        assert old_row.session_id is None
        assert old_row.prompt_messages[0]['content'] == 'old-sensitive-prompt'
        assert current_row.session_id == current.session_id
        assert AIUsageLedger.query.filter_by(request_id='reused-audit-request').count() == 2
        assert not hasattr(audit, '_PENDING_AUDITS')
        assert not hasattr(audit, 'persist_pending_audits')


def test_audit_link_failure_does_not_rollback_committed_turn(saas_app, monkeypatch):
    app, _tokens = saas_app
    with app.app_context():
        from models import AssistantSession
        from services.assistant_core import audit, memory

        ctx = memory.build_context('alpha-admin', request_id='link-failure-request')
        monkeypatch.setattr(
            audit,
            'link_audits_to_session',
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('link failed after commit')),
        )

        saved = memory.save_turn(
            user_id='alpha-admin',
            session_id=ctx.session_id,
            request_id='link-failure-request',
            question='must commit',
            summary='committed despite link failure',
        )
        db.session.remove()

        row = db.session.get(AssistantSession, saved)
        assert row is not None
        assert row.message_count == 2
        assert row.messages[-1]['content'] == 'committed despite link failure'


def test_platform_ai_provider_and_tenant_entitlement_apis_are_platform_only(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    tenant = _client(app, tokens['alpha'])

    denied = tenant.get('/api/platform/ai/providers')
    assert denied.status_code in (403, 404)

    saved = platform.put('/api/platform/ai/providers/siliconflow', json={
        'displayName': 'SiliconFlow',
        'baseUrl': 'https://api.siliconflow.cn/v1',
        'apiKey': 'sk-platform-secret-abcd',
        'enabled': True,
    })
    assert saved.status_code == 200
    provider = saved.get_json()
    assert provider['hasApiKey'] is True
    assert 'apiKey' not in provider
    assert 'sk-platform-secret-abcd' not in str(provider)

    entitlements = platform.put(f"/api/platform/tenants/{tokens['alpha_id']}/ai-entitlements", json={
        'entitlements': [
            {
                'resourceDomain': 'assistant',
                'packageCode': 'ai_assistant',
                'enabled': True,
                'selectedTier': 'standard',
                'allowedTiers': ['basic', 'standard'],
                'monthlyQuota': 20,
            }
        ]
    })
    assert entitlements.status_code == 200
    rows = entitlements.get_json()['entitlements']
    assert rows[0]['resourceDomain'] == 'assistant'
    assert rows[0]['monthlyQuota'] == 20


def test_platform_ai_read_endpoints_do_not_seed_or_commit(saas_app, monkeypatch):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    from routes import platform as platform_routes

    assert not hasattr(platform_routes, 'seed_ai_resource_defaults')
    with app.app_context():
        from services import ai_resource_governance as governance

        governance.seed_ai_resource_defaults()

    def fail_if_seeded(*_args, **_kwargs):
        raise AssertionError('AI defaults must be prepared during startup, not in GET requests')

    monkeypatch.setattr(
        'services.ai_resource_governance.seed_ai_resource_defaults',
        fail_if_seeded,
    )

    def fail_if_committed():
        raise AssertionError('AI GET requests must not commit the database session')

    monkeypatch.setattr(db.session, 'commit', fail_if_committed)
    paths = [
        '/api/platform/ai/providers',
        '/api/platform/ai/model-policies',
        '/api/platform/ai/addon-packages',
        f"/api/platform/tenants/{tokens['alpha_id']}/ai-entitlements",
    ]
    for path in paths:
        response = platform.get(path)
        assert response.status_code == 200, path


def test_model_policy_get_does_not_overwrite_saved_policy_values(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    with app.app_context():
        from models import AIModelPolicy
        from services.ai_resource_governance import seed_ai_resource_defaults

        seed_ai_resource_defaults()
        policy = AIModelPolicy.query.filter_by(
            resource_domain='assistant', use_case='dialogue', tier='standard',
        ).first()
        assert policy is not None
        policy.model = 'custom-model-preserved'
        policy.max_tokens = 1777
        db.session.commit()

    response = platform.get('/api/platform/ai/model-policies')
    assert response.status_code == 200
    with app.app_context():
        policy = AIModelPolicy.query.filter_by(
            resource_domain='assistant', use_case='dialogue', tier='standard',
        ).first()
        assert policy.model == 'custom-model-preserved'
        assert policy.max_tokens == 1777


def test_bulk_ai_entitlement_update_is_atomic_on_invalid_item(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    response = platform.put(f"/api/platform/tenants/{tokens['alpha_id']}/ai-entitlements", json={
        'entitlements': [
            {
                'resourceDomain': 'assistant',
                'packageCode': 'ai_assistant',
                'enabled': True,
                'selectedTier': 'standard',
                'allowedTiers': ['basic', 'standard'],
                'monthlyQuota': 20,
            },
            {
                'resourceDomain': 'resume_ai',
                'packageCode': 'recruitment_ai',
                'enabled': True,
                'selectedTier': 'not-allowed',
                'allowedTiers': ['standard'],
                'monthlyQuota': 20,
            },
        ],
    })
    assert response.status_code == 400
    with app.app_context():
        from models import TenantAIEntitlement

        assert TenantAIEntitlement.query.filter_by(
            tenant_id=tokens['alpha_id'], resource_domain='assistant',
        ).first() is None


def test_tenant_ai_entitlement_api_is_redacted_and_tier_limited(saas_app):
    app, tokens = saas_app
    platform = _client(app, tokens['platform'])
    alpha = _client(app, tokens['alpha'])

    platform.put(f"/api/platform/tenants/{tokens['alpha_id']}/ai-entitlements", json={
        'entitlements': [{
            'resourceDomain': 'assistant',
            'packageCode': 'ai_assistant',
            'enabled': True,
            'selectedTier': 'basic',
            'allowedTiers': ['basic', 'standard'],
            'monthlyQuota': 20,
        }]
    })

    payload = alpha.get('/api/hrm/ai/entitlements')
    assert payload.status_code == 200
    text = str(payload.get_json())
    assert 'deepseek' not in text.lower()
    assert 'siliconflow' not in text.lower()
    assert payload.get_json()['entitlements'][0]['selectedTier'] == 'basic'

    ok = alpha.post('/api/hrm/ai/entitlements/assistant/select-tier', json={'tier': 'standard'})
    assert ok.status_code == 200
    assert ok.get_json()['entitlement']['selectedTier'] == 'standard'

    rejected = alpha.post('/api/hrm/ai/entitlements/assistant/select-tier', json={'tier': 'professional'})
    assert rejected.status_code == 400
    assert rejected.get_json()['code'] == 'AI_TIER_NOT_ALLOWED'


def test_llm_client_blocks_assistant_call_when_entitlement_missing(saas_app, monkeypatch):
    app, _tokens = saas_app
    with app.app_context():
        from services.assistant_core import llm_client
        from services.assistant_core.schemas import AssistantContext

        provider_called = {'value': False}

        def fake_post(*_args, **_kwargs):
            provider_called['value'] = True
            raise AssertionError('provider must not be called')

        monkeypatch.setattr(llm_client.requests, 'post', fake_post)
        monkeypatch.setattr(llm_client, 'API_KEY', 'sk-test')

        ctx = AssistantContext(
            user_id='alpha-admin',
            role='admin',
            session_id=None,
            request_id='gate-missing-entitlement',
            client_context={},
        )
        msg = llm_client.chat_profile(
            'standard',
            [{'role': 'user', 'content': '你好'}],
            use_case='dialogue',
            resource_domain='assistant',
            ctx=ctx,
        )

        assert msg is None
        assert provider_called['value'] is False
        assert llm_client.last_call_meta()['status'] == 'governance_denied'
        assert llm_client.last_call_meta()['error_code'] == 'AI_RESOURCE_DISABLED'


def test_exam_generation_route_blocks_unpurchased_exam_ai_before_llm(saas_app, monkeypatch):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])

    called = {'value': False}

    def fake_generate(*_args, **_kwargs):
        called['value'] = True
        return [{'type': 'single', 'stem': 'x', 'options': ['A', 'B'], 'answer': [0], 'difficulty': 1}]

    monkeypatch.setattr('services.exam_generation.generate_questions', fake_generate)
    response = alpha.post('/api/hrm/exam-questions/generate', json={'sourceText': '培训资料不少于几个字', 'count': 1})

    assert response.status_code == 403
    assert response.get_json()['code'] == 'AI_RESOURCE_DISABLED'
    assert called['value'] is False


def test_interview_analysis_route_blocks_unpurchased_interview_ai_before_service(saas_app, monkeypatch):
    app, tokens = saas_app
    with app.app_context():
        from models import Interview, Job, Resume

        db.session.add(Job(id='job-ai-gate', tenant_id=tokens['alpha_id'], title='测试岗位', description='岗位说明'))
        db.session.add(Resume(id='resume-ai-gate', tenant_id=tokens['alpha_id'], job_id='job-ai-gate', candidate_name='候选人', file_url='/uploads/r.pdf'))
        db.session.add(Interview(
            id='interview-ai-gate',
            tenant_id=tokens['alpha_id'],
            job_id='job-ai-gate',
            resume_id='resume-ai-gate',
            scheduled_at=db.func.now(),
        ))
        db.session.commit()

    called = {'value': False}
    monkeypatch.setattr('services.interview_analysis.analyze_interview_text', lambda **_kwargs: called.update(value=True) or {})

    alpha = _client(app, tokens['alpha'])
    response = alpha.post('/api/interviews/interview-ai-gate/analyze/text', json={
        'feedbackText': '这是一段足够长的面试反馈文本，用于证明未购买权益时不会调用分析服务。候选人回答包含项目经验、沟通表现、技术能力和后续观察建议。'
    })

    assert response.status_code == 403
    assert response.get_json()['code'] == 'AI_RESOURCE_DISABLED'
    assert called['value'] is False


def test_portal_course_qa_blocks_unpurchased_training_ai_before_service(saas_app, monkeypatch):
    app, tokens = saas_app
    with app.app_context():
        from models import Course, Employee, EmployeePortalAccount

        db.session.add(Employee(
            id='emp-training-ai-gate',
            tenant_id=tokens['alpha_id'],
            name='培训员工',
            employee_no='TRAIN-AI-001',
            status='active',
        ))
        db.session.add(EmployeePortalAccount(
            id='portal-training-ai-gate',
            tenant_id=tokens['alpha_id'],
            employee_id='emp-training-ai-gate',
            password_hash='x',
            status='active',
        ))
        db.session.add(Course(
            id='course-training-ai-gate',
            tenant_id=tokens['alpha_id'],
            title='培训 AI 门控课程',
            is_show=True,
        ))
        db.session.commit()

    called = {'value': False}
    monkeypatch.setattr('services.course_qa.answer_course_question', lambda *_args, **_kwargs: called.update(value=True) or {})

    with app.app_context():
        from models import Tenant

        alpha_tenant = db.session.get(Tenant, tokens['alpha_id'])
        portal_token = create_access_token(
            identity='portal-training-ai-gate',
            additional_claims={
                'role': 'employee',
                'account_type': 'employee_portal',
                'employee_id': 'emp-training-ai-gate',
                **tenant_claims_for(alpha_tenant, is_platform_admin=False),
            },
        )

    portal = _client(app, portal_token)
    response = portal.post('/api/portal/courses/course-training-ai-gate/ask', json={
        'question': '这节课程的重点是什么？'
    })

    assert response.status_code == 403
    assert response.get_json()['code'] == 'AI_RESOURCE_DISABLED'
    assert called['value'] is False


def test_real_model_diagnostics_are_platform_only_not_tenant_hrm(saas_app):
    app, tokens = saas_app
    alpha = _client(app, tokens['alpha'])
    platform = _client(app, tokens['platform'])

    tenant_result = alpha.post('/api/hrm/assistant/model-call-test', json={'prompt': 'test'})
    assert tenant_result.status_code in (403, 404)

    platform_result = platform.post('/api/platform/ai/diagnostics/model-call-test', json={
        'prompt': '平台诊断测试',
        'modelProfile': 'standard',
    })
    assert platform_result.status_code in (200, 502, 503)
    assert platform_result.status_code != 404


def test_no_hrm_business_ai_service_posts_to_siliconflow_directly():
    root = Path(__file__).resolve().parents[1]
    checked = [
        root / 'services' / 'ai_analysis.py',
        root / 'services' / 'interview_analysis.py',
        root / 'services' / 'exam_generation.py',
        root / 'services' / 'course_qa.py',
        root / 'services' / 'speech_to_text.py',
    ]
    offenders = []
    for path in checked:
        text = path.read_text(encoding='utf-8')
        if 'requests.post(' in text and 'ai_resource_governance' not in text and 'llm_client' not in text:
            offenders.append(str(path))
    assert offenders == []
