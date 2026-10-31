import importlib
import sys
import types
import warnings
from pathlib import Path


def test_siliconflow_services_do_not_default_to_committed_api_key(monkeypatch):
    monkeypatch.delenv('SILICONFLOW_API_KEY', raising=False)

    for module_name in [
        'services.ai_analysis',
        'services.interview_analysis',
    ]:
        module = importlib.import_module(module_name)
        module = importlib.reload(module)

        assert module.SILICONFLOW_API_KEY == ''

    speech_to_text = importlib.import_module('services.speech_to_text')
    speech_to_text = importlib.reload(speech_to_text)
    assert not hasattr(speech_to_text, 'SILICONFLOW_API_KEY')


def test_baidu_ocr_credentials_come_from_environment(monkeypatch):
    monkeypatch.delenv('BAIDU_OCR_APP_ID', raising=False)
    monkeypatch.delenv('BAIDU_OCR_API_KEY', raising=False)
    monkeypatch.delenv('BAIDU_OCR_SECRET_KEY', raising=False)
    monkeypatch.setitem(
        sys.modules,
        'PyPDF2',
        types.SimpleNamespace(PdfReader=object),
    )
    monkeypatch.setitem(
        sys.modules,
        'PIL',
        types.SimpleNamespace(Image=object),
    )

    module = importlib.import_module('services.pdf_parser')
    module = importlib.reload(module)

    assert module.BAIDU_OCR_APP_ID == ''
    assert module.BAIDU_OCR_API_KEY == ''
    assert module.BAIDU_OCR_SECRET_KEY == ''


def test_pdf_parser_import_does_not_emit_pypdf2_deprecation_warning(monkeypatch):
    monkeypatch.delenv('BAIDU_OCR_APP_ID', raising=False)
    monkeypatch.delenv('BAIDU_OCR_API_KEY', raising=False)
    monkeypatch.delenv('BAIDU_OCR_SECRET_KEY', raising=False)
    sys.modules.pop('services.pdf_parser', None)
    sys.modules.pop('PyPDF2', None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        importlib.import_module('services.pdf_parser')

    assert not any('PyPDF2 is deprecated' in str(item.message) for item in caught)


def test_backend_requirements_use_supported_pdf_and_image_dependencies():
    requirements = (Path(__file__).resolve().parents[1] / 'requirements.txt').read_text(encoding='utf-8')
    assert 'pypdf==6.14.2' in requirements
    assert 'Pillow==12.3.0' in requirements
    assert 'PyPDF2==' not in requirements
