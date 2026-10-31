"""课程内容 AI 问答（轻量 RAG）。

不做向量索引（单门课程内容通常 <1 万字），而是：
1. 收集课程所有文本（简介 + 章节描述 + 课时标题 + 附件文本）
2. 按段落切分，用 embedding 相似度召回 top-k 相关段落
3. 把召回段落 + 员工问题喂给 LLM 生成回答

复用现有 embedding_client + llm_client。
"""
from __future__ import annotations

import logging
from typing import List

from models import Course, CourseChapter, CourseHour, CourseAttachment, db

logger = logging.getLogger('hengpintong.course_qa')


def gather_course_text(course_id: str) -> List[str]:
    """收集课程所有文本，按段落返回（用于召回）。"""
    chunks: List[str] = []
    course = db.session.get(Course, course_id)
    if not course:
        return chunks
    if course.title:
        chunks.append(f'课程标题：{course.title}')
    if course.short_desc:
        chunks.append(f'课程简介：{course.short_desc}')
    if course.content:
        # content 可能很长，按段落切
        for para in (course.content or '').split('\n'):
            para = para.strip()
            if len(para) > 10:
                chunks.append(para)
    # 章节
    for ch in CourseChapter.query.filter_by(course_id=course_id).all():
        if ch.name:
            chunks.append(f'章节：{ch.name}')
        if ch.description:
            chunks.append(f'{ch.name}说明：{ch.description}')
        # 章节 material 文件名（文本内容不提取，太重）
        for m in (ch.materials or []):
            chunks.append(f'{ch.name}资料：{m.get("title", "")}')
    # 课时标题
    for h in CourseHour.query.filter_by(course_id=course_id).all():
        if h.title:
            chunks.append(f'课时：{h.title}')
    return chunks


def retrieve_relevant_chunks(question: str, chunks: List[str], top_k: int = 5) -> List[str]:
    """召回最相关的 top_k 段落。"""
    if not chunks:
        return []
    return _keyword_fallback(question, chunks, top_k)


def _keyword_fallback(question: str, chunks: List[str], top_k: int) -> List[str]:
    """embedding 不可用时，用关键词重叠召回。"""
    q_words = set(question)
    scored = []
    for ch in chunks:
        overlap = len(q_words & set(ch))
        scored.append((overlap, ch))
    scored.sort(key=lambda x: -x[0])
    return [ch for _, ch in scored[:top_k] if _ > 0] or chunks[:top_k]


def answer_course_question(course_id: str, question: str) -> dict:
    """员工针对课程内容提问，AI 基于 RAG 回答。

    返回 {answer, sources(召回段落), error?}
    """
    chunks = gather_course_text(course_id)
    if not chunks:
        return {'answer': '该课程暂无可供问答的内容。', 'sources': []}
    relevant = retrieve_relevant_chunks(question, chunks, top_k=5)
    context = '\n'.join(f'- {c}' for c in relevant)

    from services.assistant_core import llm_client
    messages = [
        {'role': 'system', 'content': '你是企业培训学习助手。根据提供的课程内容片段，用简洁中文回答员工的问题。'
                                          '如果课程内容中没有相关信息，如实说明，不要编造。回答控制在 200 字以内。'},
        {'role': 'user', 'content': f'课程内容片段：\n{context}\n\n员工问题：{question}'},
    ]
    try:
        msg = llm_client.chat_profile('standard', messages, temperature=0.3, max_tokens=400,
                                      use_case='course_qa', resource_domain='training_ai')
    except Exception as exc:
        logger.warning('course_qa_llm_failed', extra={'error': str(exc)})
        return {'answer': '抱歉，AI 助手暂时不可用，请稍后重试。', 'sources': relevant, 'error': str(exc)}

    if not msg:
        return {'answer': '抱歉，AI 助手暂时不可用，请稍后重试。', 'sources': relevant}
    answer_text = msg.get('content', '') if isinstance(msg, dict) else str(msg)
    return {'answer': answer_text.strip(), 'sources': relevant}
