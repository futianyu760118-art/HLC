from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from sqlalchemy.orm import selectinload
import uuid
import os
from datetime import datetime

from models import db, Interview, Job, Resume
from services.authz import INTERVIEW_ROLES, require_roles
from services.business_time import parse_business_datetime
from services.tenancy import current_tenant_id
from services.ai_resource_governance import AIResourceDenied, assert_ai_resource_allowed
from services.tenant_storage_quota import register_storage_quota_error_handler
from services.tenant_storage_quota import StorageQuotaExceeded, StorageUsageUnavailable
from services.storage import (
    delete_object,
    delete_object_if_unreferenced,
    save_local_upload,
    storage_reference_keys,
)
from services.interview_analysis import (
    analyze_interview_text,
    analyze_interview_audio,
    analyze_interview_video
)
from services.speech_to_text import transcribe_audio, format_transcript
import secrets
import hashlib

interviews_bp = Blueprint('interviews', __name__)
register_storage_quota_error_handler(interviews_bp)


def _interview_storage_references(interview):
    return (
        storage_reference_keys(interview.feedback_file_url)
        | storage_reference_keys(interview.recording_url)
    )


def _release_interview_storage(references, *, tenant_id):
    for reference in sorted(set(references or ())):
        delete_object_if_unreferenced(reference, tenant_id=tenant_id)

def generate_room_id():
    """生成唯一的Jitsi房间ID"""
    return f"hpt-{secrets.token_hex(8)}"

def generate_invite_token():
    """生成候选人邀约token"""
    return secrets.token_urlsafe(32)

# 允许的音频/视频文件扩展名
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}

def allowed_media_file(filename):
    """检查文件是否是允许的媒体格式"""
    if '.' not in filename:
        return False, None
    ext = filename.rsplit('.', 1)[1].lower()
    if ext in ALLOWED_AUDIO_EXTENSIONS:
        return True, 'audio'
    elif ext in ALLOWED_VIDEO_EXTENSIONS:
        return True, 'video'
    return False, None


def _require_interview_ai(use_case: str):
    try:
        return assert_ai_resource_allowed(
            tenant_id=current_tenant_id(),
            user_id=get_jwt_identity(),
            resource_domain='interview_ai',
            use_case=use_case,
        )
    except AIResourceDenied as exc:
        payload, status = exc.to_response()
        return jsonify(payload), status

@interviews_bp.route('/', methods=['GET'])
@jwt_required()
def get_interviews():
    denied = require_roles(INTERVIEW_ROLES, '无权限查看面试')
    if denied:
        return denied
    # selectinload 消除 to_dict 内 creator/updater 懒加载的 N+1
    interviews = Interview.query.options(
        selectinload(Interview.creator), selectinload(Interview.updater)
    ).order_by(Interview.scheduled_at.desc()).all()
    return jsonify([interview.to_dict() for interview in interviews])

@interviews_bp.route('/', methods=['POST'])
@jwt_required()
def create_interview():
    denied = require_roles(INTERVIEW_ROLES, '无权限创建面试')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    data = request.get_json()
    job_id = data.get('jobId')
    resume_id = data.get('resumeId')
    scheduled_at = data.get('scheduledAt')
    notes = data.get('notes')
    
    if not all([job_id, resume_id, scheduled_at]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    interview = Interview(
        id=str(uuid.uuid4()),
        job_id=job_id,
        resume_id=resume_id,
        scheduled_at=parse_business_datetime(scheduled_at),
        status='scheduled',
        notes=notes,
        # 自动生成在线面试房间和邀约链接
        room_id=generate_room_id(),
        invite_token=generate_invite_token(),
        created_by=current_user_id,
        updated_by=current_user_id
    )
    
    db.session.add(interview)
    db.session.commit()
    
    print(f'[面试] 创建面试 {interview.id}')
    print(f'[面试] 房间ID: {interview.room_id}')
    print(f'[面试] 邀约Token: {interview.invite_token}')
    
    return jsonify(interview.to_dict()), 201

@interviews_bp.route('/<interview_id>', methods=['PUT'])
@jwt_required()
def update_interview(interview_id):
    denied = require_roles(INTERVIEW_ROLES, '无权限更新面试')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': 'Not found'}), 404
    
    data = request.get_json()
    
    if 'scheduledAt' in data:
        interview.scheduled_at = parse_business_datetime(data['scheduledAt'])
    if 'status' in data:
        interview.status = data['status']
    if 'notes' in data:
        interview.notes = data['notes']
    
    interview.updated_by = current_user_id
    db.session.commit()
    return jsonify(interview.to_dict())

@interviews_bp.route('/<interview_id>', methods=['DELETE'])
@jwt_required()
def delete_interview(interview_id):
    denied = require_roles(INTERVIEW_ROLES, '无权限删除面试')
    if denied:
        return denied
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': 'Not found'}), 404
    
    storage_references = _interview_storage_references(interview)
    tenant_id = interview.tenant_id
    db.session.delete(interview)
    db.session.commit()
    _release_interview_storage(storage_references, tenant_id=tenant_id)
    
    return jsonify({'removed': True})


# ============ 面试AI分析相关接口 ============

@interviews_bp.route('/<interview_id>/analyze/text', methods=['POST'])
@jwt_required()
def analyze_interview_text_api(interview_id):
    denied = require_roles(INTERVIEW_ROLES, '无权限分析面试')
    if denied:
        return denied
    """
    通过文本分析面试结果
    请求体: { "feedbackText": "面试反馈内容..." }
    """
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': '面试记录不存在'}), 404
    
    data = request.get_json()
    feedback_text = data.get('feedbackText', '').strip()
    
    if not feedback_text:
        return jsonify({'error': '面试反馈内容不能为空'}), 400
    
    if len(feedback_text) < 50:
        return jsonify({'error': '面试反馈内容过短，请提供更详细的内容（至少50字）'}), 400
    
    # 获取关联的岗位和简历信息
    job = Job.query.get(interview.job_id)
    resume = Resume.query.get(interview.resume_id)
    
    if not job or not resume:
        return jsonify({'error': '关联的岗位或简历信息不存在'}), 404
    allowed = _require_interview_ai('interview_analysis')
    if not hasattr(allowed, 'resource_domain'):
        return allowed

    try:
        print(f'\n[面试分析API] 开始分析面试 {interview_id}')
        print(f'[面试分析API] 候选人: {resume.candidate_name}, 岗位: {job.title}')
        
        # 获取简历摘要
        resume_summary = None
        if resume.ai_analysis:
            resume_summary = resume.ai_analysis.get('summary', '')
        
        # 调用AI分析
        ai_result = analyze_interview_text(
            feedback_text=feedback_text,
            candidate_name=resume.candidate_name,
            job_title=job.title,
            job_description=job.description or '',
            resume_summary=resume_summary
        )
        
        # 检查是否分析失败
        if ai_result.get('error'):
            return jsonify({'error': ai_result['message']}), 400
        
        # 更新面试记录
        interview.feedback_text = feedback_text
        interview.feedback_file_type = 'text'
        interview.ai_analysis = ai_result
        interview.analyzed_at = datetime.utcnow()
        
        db.session.commit()
        
        print(f'[面试分析API] ✓ 分析完成')
        return jsonify(interview.to_dict())
        
    except Exception as e:
        print(f'[面试分析API] 错误: {str(e)}')
        return jsonify({'error': f'分析失败: {str(e)}'}), 500


@interviews_bp.route('/<interview_id>/analyze/media', methods=['POST'])
@jwt_required()
def analyze_interview_media_api(interview_id):
    denied = require_roles(INTERVIEW_ROLES, '无权限分析面试')
    if denied:
        return denied
    """
    通过音频/视频文件分析面试结果（预留接口）
    请求体: multipart/form-data, file字段
    """
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': '面试记录不存在'}), 404
    
    if 'file' not in request.files:
        return jsonify({'error': '请上传音频或视频文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    
    # 检查文件类型
    is_allowed, file_type = allowed_media_file(file.filename)
    if not is_allowed:
        return jsonify({
            'error': '不支持的文件格式',
            'supported_audio': list(ALLOWED_AUDIO_EXTENSIONS),
            'supported_video': list(ALLOWED_VIDEO_EXTENSIONS)
        }), 400
    
    # 获取关联信息
    job = Job.query.get(interview.job_id)
    resume = Resume.query.get(interview.resume_id)
    
    if not job or not resume:
        return jsonify({'error': '关联的岗位或简历信息不存在'}), 404
    allowed = _require_interview_ai('interview_analysis')
    if not hasattr(allowed, 'resource_domain'):
        return allowed
    
    old_storage_references = _interview_storage_references(interview)
    staged_object_key = None
    try:
        # 保存文件
        file_id = str(uuid.uuid4())
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f'interview_{file_id}.{ext}'
        
        object_key = save_local_upload(file, f'interviews/{filename}')
        staged_object_key = object_key
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], object_key)
        file_url = f'/uploads/{object_key}'
        
        print(f'\n[面试媒体分析API] 文件已保存: {filepath}')
        print(f'[面试媒体分析API] 文件类型: {file_type}')
        
        # 调用对应的分析函数
        if file_type == 'audio':
            ai_result = analyze_interview_audio(
                file_path=filepath,
                candidate_name=resume.candidate_name,
                job_title=job.title,
                job_description=job.description or ''
            )
        else:
            ai_result = analyze_interview_video(
                file_path=filepath,
                candidate_name=resume.candidate_name,
                job_title=job.title,
                job_description=job.description or ''
            )
        
        # 检查是否功能未实现
        if ai_result.get('status') == 'not_implemented':
            # 保存文件信息，但不更新分析结果
            interview.feedback_file_url = file_url
            interview.feedback_file_type = file_type
            db.session.commit()
            _release_interview_storage(
                old_storage_references - _interview_storage_references(interview),
                tenant_id=interview.tenant_id,
            )
            
            return jsonify({
                'message': ai_result['message'],
                'fileUrl': file_url,
                'fileType': file_type,
                'status': 'file_saved',
                'interview': interview.to_dict()
            }), 202  # 202 Accepted - 已接收但未处理
        
        # 更新面试记录
        interview.feedback_file_url = file_url
        interview.feedback_file_type = file_type
        interview.ai_analysis = ai_result
        interview.analyzed_at = datetime.utcnow()
        
        db.session.commit()
        _release_interview_storage(
            old_storage_references - _interview_storage_references(interview),
            tenant_id=interview.tenant_id,
        )
        
        return jsonify(interview.to_dict())
        
    except (StorageQuotaExceeded, StorageUsageUnavailable):
        db.session.rollback()
        if staged_object_key and staged_object_key not in old_storage_references:
            delete_object(staged_object_key)
        raise
    except Exception as e:
        db.session.rollback()
        if staged_object_key and staged_object_key not in old_storage_references:
            delete_object(staged_object_key)
        print(f'[面试媒体分析API] 错误: {str(e)}')
        return jsonify({'error': f'处理失败: {str(e)}'}), 500


@interviews_bp.route('/<interview_id>/analyze', methods=['DELETE'])
@jwt_required()
def clear_interview_analysis(interview_id):
    """清除面试分析结果"""
    denied = require_roles(INTERVIEW_ROLES, '无权限清除面试分析')
    if denied:
        return denied
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': '面试记录不存在'}), 404
    allowed = _require_interview_ai('interview_recording_transcription')
    if not hasattr(allowed, 'resource_domain'):
        return allowed
    
    old_storage_references = storage_reference_keys(interview.feedback_file_url)

    # 清除分析数据
    interview.feedback_text = None
    interview.feedback_file_url = None
    interview.feedback_file_type = None
    interview.ai_analysis = None
    interview.analyzed_at = None
    
    db.session.commit()
    _release_interview_storage(old_storage_references, tenant_id=interview.tenant_id)
    
    return jsonify({'cleared': True, 'interview': interview.to_dict()})


# ============ 在线面试相关接口 ============

@interviews_bp.route('/invite/<invite_token>', methods=['GET'])
def get_interview_by_invite(invite_token):
    """
    通过邀约token获取面试信息（候选人访问，无需登录）
    """
    interview = Interview.query.filter_by(invite_token=invite_token).first()
    if not interview:
        return jsonify({'error': '面试邀约不存在或已过期'}), 404
    
    # 获取关联的岗位和简历信息
    job = Job.query.get(interview.job_id)
    resume = Resume.query.get(interview.resume_id)
    
    # 返回候选人需要的信息（不含敏感数据）
    return jsonify({
        'interview': {
            'id': interview.id,
            'scheduledAt': interview.scheduled_at.isoformat() if interview.scheduled_at else None,
            'status': interview.status,
            'roomId': interview.room_id,
        },
        'job': {
            'title': job.title if job else '未知岗位',
            'department': job.department if job else '',
        },
        'candidate': {
            'name': resume.candidate_name if resume else '候选人',
        }
    })


@interviews_bp.route('/<interview_id>/meeting/start', methods=['POST'])
@jwt_required()
def start_meeting(interview_id):
    """面试官开始面试"""
    denied = require_roles(INTERVIEW_ROLES, '无权限操作面试会议')
    if denied:
        return denied
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': '面试记录不存在'}), 404
    
    interview.meeting_started_at = datetime.utcnow()
    interview.status = 'in_progress'
    db.session.commit()
    
    print(f'[在线面试] 面试开始: {interview_id}')
    return jsonify(interview.to_dict())


@interviews_bp.route('/<interview_id>/meeting/end', methods=['POST'])
@jwt_required()
def end_meeting(interview_id):
    """面试官结束面试"""
    denied = require_roles(INTERVIEW_ROLES, '无权限操作面试会议')
    if denied:
        return denied
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': '面试记录不存在'}), 404
    
    interview.meeting_ended_at = datetime.utcnow()
    interview.status = 'completed'
    db.session.commit()
    
    print(f'[在线面试] 面试结束: {interview_id}')
    return jsonify(interview.to_dict())


@interviews_bp.route('/<interview_id>/recording', methods=['POST'])
@jwt_required()
def upload_recording(interview_id):
    """上传面试录音并自动转文字和 AI 分析。"""
    denied = require_roles(INTERVIEW_ROLES, '无权限上传面试录音')
    if denied:
        return denied
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': '面试记录不存在'}), 404
    
    if 'file' not in request.files:
        return jsonify({'error': '请上传录音文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    
    # 检查文件类型
    is_allowed, file_type = allowed_media_file(file.filename)
    if not is_allowed:
        return jsonify({'error': '不支持的文件格式'}), 400
    
    old_storage_references = _interview_storage_references(interview)
    staged_object_key = None
    try:
        # 保存录音文件
        file_id = str(uuid.uuid4())
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f'recording_{interview_id}_{file_id}.{ext}'
        
        object_key = save_local_upload(file, f'recordings/{filename}')
        staged_object_key = object_key
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], object_key)
        file_url = f'/uploads/{object_key}'
        interview.recording_url = file_url
        
        print(f'[在线面试] 录音已保存: {filepath}')
        
        # 自动转文字
        print(f'[在线面试] 开始语音转文字...')
        asr_result = transcribe_audio(
            filepath,
            tenant_id=current_tenant_id(),
            user_id=get_jwt_identity(),
            resource_domain='interview_ai',
            use_case='interview_recording_transcription',
        )
        
        if asr_result['success']:
            transcript = format_transcript(asr_result['text'])
            interview.transcript = transcript
            interview.feedback_text = transcript  # 同时设置为反馈文本
            interview.feedback_file_type = 'audio'
            interview.feedback_file_url = file_url
            print(f'[在线面试] ✓ 转文字完成，长度: {len(transcript)} 字')
            
            # 自动进行AI分析
            job = Job.query.get(interview.job_id)
            resume = Resume.query.get(interview.resume_id)
            
            if job and resume and len(transcript) >= 50:
                print(f'[在线面试] 开始AI分析...')
                
                resume_summary = None
                if resume.ai_analysis:
                    resume_summary = resume.ai_analysis.get('summary', '')
                
                ai_result = analyze_interview_text(
                    feedback_text=transcript,
                    candidate_name=resume.candidate_name,
                    job_title=job.title,
                    job_description=job.description or '',
                    resume_summary=resume_summary
                )
                
                if not ai_result.get('error'):
                    interview.ai_analysis = ai_result
                    interview.analyzed_at = datetime.utcnow()
                    print(f'[在线面试] ✓ AI分析完成')
                else:
                    print(f'[在线面试] AI分析失败: {ai_result.get("message")}')
            else:
                print(f'[在线面试] 转文字内容过短，跳过AI分析')
        else:
            print(f'[在线面试] ✗ 转文字失败: {asr_result["error"]}')
            interview.transcript = f'[转文字失败] {asr_result["error"]}'
        
        db.session.commit()
        _release_interview_storage(
            old_storage_references - _interview_storage_references(interview),
            tenant_id=interview.tenant_id,
        )
        
        return jsonify({
            'success': True,
            'interview': interview.to_dict(),
            'transcriptSuccess': asr_result['success'],
            'transcriptError': asr_result.get('error', '')
        })
        
    except (StorageQuotaExceeded, StorageUsageUnavailable):
        db.session.rollback()
        if staged_object_key and staged_object_key not in old_storage_references:
            delete_object(staged_object_key)
        raise
    except Exception as e:
        db.session.rollback()
        if staged_object_key and staged_object_key not in old_storage_references:
            delete_object(staged_object_key)
        print(f'[在线面试] 录音处理失败: {str(e)}')
        return jsonify({'error': f'处理失败: {str(e)}'}), 500


@interviews_bp.route('/<interview_id>/regenerate-room', methods=['POST'])
@jwt_required()
def regenerate_room(interview_id):
    """重新生成面试房间ID（用于安全考虑）"""
    denied = require_roles(INTERVIEW_ROLES, '无权限重置面试房间')
    if denied:
        return denied
    interview = Interview.query.get(interview_id)
    if not interview:
        return jsonify({'error': '面试记录不存在'}), 404
    
    interview.room_id = generate_room_id()
    interview.invite_token = generate_invite_token()
    db.session.commit()
    
    print(f'[在线面试] 重新生成房间: {interview.room_id}')
    return jsonify(interview.to_dict())
