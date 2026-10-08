from pathlib import Path
from types import SimpleNamespace


def test_asr_entry_never_uses_bootstrap_local_provider_bypass(monkeypatch, tmp_path):
    from services import speech_to_text

    audio = tmp_path / 'governed.wav'
    audio.write_bytes(b'governed-audio')
    called = {'governed': False, 'local': False}

    monkeypatch.setattr(speech_to_text, 'ASR_PROVIDER', 'local', raising=False)
    monkeypatch.setattr(
        speech_to_text,
        'transcribe_siliconflow',
        lambda *_args, **_kwargs: called.update(governed=True) or {
            'success': True,
            'text': 'governed',
            'error': '',
        },
    )
    monkeypatch.setattr(
        speech_to_text,
        'transcribe_local',
        lambda *_args, **_kwargs: called.update(local=True) or {
            'success': True,
            'text': 'local bypass',
            'error': '',
        },
        raising=False,
    )

    result = speech_to_text.transcribe_audio(
        str(audio),
        tenant_id='tenant-test',
        user_id='user-test',
        resource_domain='assistant',
        use_case='assistant_voice_transcription',
        request_id='governed-asr-entry',
    )

    assert result['text'] == 'governed'
    assert called == {'governed': True, 'local': False}


def test_siliconflow_asr_upload_preserves_audio_mime(monkeypatch, tmp_path):
    from services import ai_resource_governance

    audio = tmp_path / 'voice.webm'
    audio.write_bytes(b'webm-audio')
    captured = {}

    def fake_authorize(**kwargs):
        captured.setdefault('authorizations', []).append(dict(kwargs))
        captured['authorization'] = kwargs
        return SimpleNamespace(tier='standard', entitlement_id='entitlement-test')

    def fake_post(url, *, headers, files, data, timeout):
        captured['file_tuple'] = files['file']
        return SimpleNamespace(ok=True, json=lambda: {'text': '测试语音'})

    monkeypatch.setattr(
        ai_resource_governance,
        'assert_ai_resource_allowed',
        fake_authorize,
    )
    monkeypatch.setattr(
        ai_resource_governance,
        'resolve_ai_runtime',
        lambda *_args, **_kwargs: SimpleNamespace(
            base_url='https://provider.example.test/v1',
            provider_code='siliconflow',
            api_key='test-key',
            model='FunAudioLLM/SenseVoiceSmall',
            max_tokens=1200,
            source='database',
        ),
    )
    monkeypatch.setattr(ai_resource_governance, 'record_ai_usage', lambda **_kwargs: None)
    monkeypatch.setattr(ai_resource_governance.requests, 'post', fake_post)

    result = ai_resource_governance.transcribe_audio_with_governance(
        str(audio),
        tenant_id='tenant-test',
        user_id='user-test',
        resource_domain='assistant',
        use_case='assistant_voice_transcription',
    )

    assert result['success'] is True
    assert captured['file_tuple'][2] == 'audio/webm'
    assert captured['authorization']['reserve'] is True
    assert [item.get('reserve', False) for item in captured['authorizations']] == [False, True]


def test_dashboard_open_jobs_entry_opens_filtered_job_page():
    repo_root = Path(__file__).resolve().parents[2]
    home = (repo_root / 'src/pages/p-home/index.tsx').read_text(encoding='utf-8')
    jobs = (repo_root / 'src/pages/p-job_manage/index.tsx').read_text(encoding='utf-8')

    assert "navigate('/job-manage?status=open')" in home
    assert "useSearchParams" in jobs
    assert "searchParams.get('status')" in jobs


def test_home_page_has_role_presets_and_missing_metric_fallback():
    repo_root = Path(__file__).resolve().parents[2]
    home = (repo_root / 'src/pages/p-home/index.tsx').read_text(encoding='utf-8')

    assert 'ROLE_HOME_PRESETS' in home
    assert 'HR 运营总览' in home
    assert '招聘工作台' in home
    assert '薪酬财务工作台' in home
    assert 'metricValue === undefined ? \'-\'' in home


def test_platform_console_uses_product_primitives():
    repo_root = Path(__file__).resolve().parents[2]
    platform_page = (repo_root / 'src/pages/p-platform-tenants/index.tsx').read_text(encoding='utf-8')

    assert "from '../../components/product'" in platform_page
    assert 'ProductButton' in platform_page
    assert 'ProductEmptyState' in platform_page
    assert 'ProductMetricCard' in platform_page


def test_platform_data_request_update_payload_keeps_blank_evidence_out():
    repo_root = Path(__file__).resolve().parents[2]
    platform_page = (repo_root / 'src/pages/p-platform-tenants/index.tsx').read_text(encoding='utf-8')

    assert 'evidenceRef: dataRequestEvidence' not in platform_page
    assert 'const payload' in platform_page
    assert 'dataRequestEvidence.trim()' in platform_page
    assert 'payload.evidenceRef' in platform_page


def test_feedback_page_selects_feedback_from_notification_link():
    repo_root = Path(__file__).resolve().parents[2]
    feedback_page = (repo_root / 'src/pages/p-feedback/index.tsx').read_text(encoding='utf-8')

    assert 'useSearchParams' in feedback_page
    assert "searchParams.get('id')" in feedback_page
    assert 'setSelected(match)' in feedback_page


def test_hrm_lifecycle_workflow_frontend_contract_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    api = (repo_root / 'src/utils/api.ts').read_text(encoding='utf-8')
    hrm_page = (repo_root / 'src/pages/p-hrm/index.tsx').read_text(encoding='utf-8')

    assert 'export interface WorkflowTransition' in api
    assert 'export interface DomainTimelineEvent' in api
    assert 'getWorkflow:' in api
    assert 'runWorkflowTransition:' in api
    assert 'LIFECYCLE_WORKFLOW_MODULES' in hrm_page
    assert 'loadWorkflow' in hrm_page
    assert 'workflow?.transitions' in hrm_page
    assert 'workflow?.timeline' in hrm_page
    assert "runAction(detail, `workflow:${transition.key}`)" in hrm_page
    assert 'useSearchParams' in hrm_page
    assert "searchParams.get('id')" in hrm_page
    assert 'openDetail(match)' in hrm_page


def test_hrm_lifecycle_workflow_browser_smoke_is_wired():
    repo_root = Path(__file__).resolve().parents[2]
    package_json = (repo_root / 'package.json').read_text(encoding='utf-8')
    script = (repo_root / 'scripts/verify-hrm-lifecycle-workflow-browser-smoke.mjs').read_text(encoding='utf-8')

    assert '"verify:hrm-lifecycle-workflow-browser-smoke": "node scripts/verify-hrm-lifecycle-workflow-browser-smoke.mjs"' in package_json
    assert '/hrm/contracts?id=' in script
    assert '/hrm/probations?id=' in script
    assert '/hrm/resignations?id=' in script
    assert '工作流动作' in script
    assert '流程时间线' in script
