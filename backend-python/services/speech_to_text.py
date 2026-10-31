"""
语音转文字服务
统一通过平台保存的受控 ASR 运行时进行转写。
"""
from __future__ import annotations

import os
import mimetypes

_AUDIO_MIME_BY_EXT = {
    '.webm': 'audio/webm',
    '.wav': 'audio/wav',
    '.mp3': 'audio/mpeg',
    '.mpeg': 'audio/mpeg',
    '.m4a': 'audio/mp4',
    '.mp4': 'audio/mp4',
    '.ogg': 'audio/ogg',
}


def _audio_mime_type(audio_path: str) -> str:
    ext = os.path.splitext(audio_path)[1].lower()
    guessed, _ = mimetypes.guess_type(audio_path)
    return _AUDIO_MIME_BY_EXT.get(ext) or guessed or 'application/octet-stream'


def transcribe_audio(
    audio_path: str,
    language: str = 'zh',
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    resource_domain: str = 'assistant',
    use_case: str = 'assistant_voice_transcription',
    request_id: str | None = None,
) -> dict:
    """
    将音频文件转换为文字
    
    Args:
        audio_path: 音频文件路径
        language: 语言代码 (zh/en)
    
    Returns:
        {
            'success': bool,
            'text': str,  # 转写文本
            'error': str  # 错误信息（如有）
        }
    """
    return transcribe_siliconflow(
        audio_path,
        language,
        tenant_id=tenant_id,
        user_id=user_id,
        resource_domain=resource_domain,
        use_case=use_case,
        request_id=request_id,
    )


def transcribe_siliconflow(
    audio_path: str,
    language: str = 'zh',
    *,
    tenant_id: str | None = None,
    user_id: str | None = None,
    resource_domain: str = 'assistant',
    use_case: str = 'assistant_voice_transcription',
    request_id: str | None = None,
) -> dict:
    """使用平台保存运行时解析出的受控 ASR 供应商进行语音转文字。"""
    try:
        print(f'[ASR] 使用受控 ASR 供应商转写: {audio_path}')
        from services.ai_resource_governance import transcribe_audio_with_governance

        return transcribe_audio_with_governance(
            audio_path,
            language=language,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_domain=resource_domain,
            use_case=use_case,
            request_id=request_id,
        )
            
    except Exception as e:
        error_msg = f'转写异常: {str(e)}'
        print(f'[ASR] ✗ {error_msg}')
        return {'success': False, 'text': '', 'error': error_msg}
def format_transcript(text: str) -> str:
    """格式化转写文本，添加适当的换行和标点"""
    if not text:
        return text
    
    # 按句子分段
    import re
    
    # 中文句号、问号、感叹号后添加换行
    text = re.sub(r'([。！？])\s*', r'\1\n', text)
    
    # 去除多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()
