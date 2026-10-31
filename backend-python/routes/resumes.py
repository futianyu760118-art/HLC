from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
import uuid
import os
import tempfile
from datetime import datetime

from models import db, Resume, Job
from services.ai_analysis import analyze_resume
from services.authz import RECRUITMENT_ROLES, require_roles
from services.pdf_parser import extract_text_from_file
from services.storage import (
    delete_object,
    delete_object_if_unreferenced,
    download_to_file,
    file_exists,
    is_minio_enabled,
    save_local_upload,
    storage_reference_keys,
    upload_file,
)
from services.tenancy import assign_tenant, object_belongs_to_current_tenant
from services.ai_resource_governance import AIResourceDenied, assert_ai_resource_allowed
from services.tenant_storage_quota import (
    StorageQuotaExceeded,
    StorageUsageUnavailable,
    register_storage_quota_error_handler,
)

resumes_bp = Blueprint('resumes', __name__)
register_storage_quota_error_handler(resumes_bp)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def _require_resume_ai(use_case: str):
    from services.tenancy import current_tenant_id
    try:
        return assert_ai_resource_allowed(
            tenant_id=current_tenant_id(),
            user_id=get_jwt_identity(),
            resource_domain='resume_ai',
            use_case=use_case,
        )
    except AIResourceDenied as exc:
        payload, status = exc.to_response()
        return jsonify(payload), status

@resumes_bp.route('/', methods=['GET'])
@jwt_required()
def get_resumes():
    denied = require_roles(RECRUITMENT_ROLES, '无权限查看简历')
    if denied:
        return denied
    # selectinload 消除 to_dict 内 creator/updater 懒加载的 N+1
    query = Resume.query.options(
        selectinload(Resume.creator), selectinload(Resume.updater)
    ).order_by(Resume.created_at.desc())
    page = request.args.get('page', type=int)
    size = request.args.get('size', type=int, default=50)
    if page and page > 0:
        size = max(1, min(size, 200))
        total = query.count()
        resumes = query.offset((page - 1) * size).limit(size).all()
        return jsonify({
            'items': [resume.to_dict() for resume in resumes],
            'total': total,
            'page': page,
            'size': size,
            'pages': (total + size - 1) // size,
        })
    resumes = query.all()
    return jsonify([resume.to_dict() for resume in resumes])

@resumes_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_resume():
    denied = require_roles(RECRUITMENT_ROLES, '无权限上传简历')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    files = request.files.getlist('file')
    job_id = request.form.get('jobId')
    
    if not job_id:
        return jsonify({'error': 'Job ID required'}), 400
    
    # 查找岗位
    job = Job.query.get(job_id)
    if not job or not object_belongs_to_current_tenant(job):
        return jsonify({'error': 'Job not found'}), 404
    allowed = _require_resume_ai('resume_analysis')
    if not hasattr(allowed, 'resource_domain'):
        return allowed
    
    # 创建任务ID
    from routes.tasks import create_task, update_task
    task_id = str(uuid.uuid4())
    create_task(task_id, len(files))
    
    uploaded_resumes = []
    errors = []
    replaced_resumes = []
    pending_delete_references = set()
    successful_staged_keys = set()
    
    print(f'[批量上传] 任务ID: {task_id}')
    print(f'[批量上传] 开始处理 {len(files)} 个文件...')
    
    for i, file in enumerate(files):
        if not file or file.filename == '':
            continue
        
        if not allowed_file(file.filename):
            errors.append({'filename': file.filename, 'error': '不支持的文件类型'})
            continue
        
        staged_object_key = None
        savepoint = db.session.begin_nested()
        try:
            print(f'\n[{i+1}/{len(files)}] 处理文件: {file.filename}')

            # 保存文件 —— 统一走 MinIO 对象存储（容器重建不丢失）
            resume_id = str(uuid.uuid4())
            ext = os.path.splitext(file.filename)[1].lower()
            object_key = f'resumes/{resume_id}{ext}'

            if is_minio_enabled():
                # MinIO 模式：上传后下载临时文件用于文本提取
                object_key = upload_file(file.stream, object_key, content_type='application/pdf')
                staged_object_key = object_key
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp_path = tmp.name
                download_to_file(object_key, tmp_path)
                filepath = tmp_path
            else:
                # 本地回退模式（开发环境无 MinIO 时）
                filename = f'{resume_id}{ext}'
                object_key = save_local_upload(file, filename)
                staged_object_key = object_key
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], object_key)

            file_url = f'/uploads/{object_key}' if is_minio_enabled() else f'/uploads/{object_key}'

            # 提取文本
            file_content = extract_text_from_file(filepath)
            print(f'[简历上传] 提取了 {len(file_content)} 字符')

            # AI分析
            print('[简历上传] 开始AI分析...')
            ai_result = analyze_resume(file_content, job.title, job.description, job.scoring_criteria)
            print(f'[简历上传] AI分析完成 - {ai_result["candidateName"]}')

            # 检测重复
            duplicates = Resume.query.filter(
                Resume.candidate_name == ai_result['candidateName'],
                or_(
                    Resume.job_id == job_id,
                    Resume.email == ai_result.get('email'),
                    Resume.phone == ai_result.get('phone')
                )
            ).all()

            if duplicates:
                print(f'[去重检测] 发现重复简历: {ai_result["candidateName"]}')
                for dup in duplicates:
                    pending_delete_references.update(storage_reference_keys(dup.file_url))
                    db.session.delete(dup)
                
                replaced_resumes.append({
                    'name': ai_result['candidateName'],
                    'count': len(duplicates)
                })
                print(f'[去重检测] 已移除 {len(duplicates)} 条重复记录')
            
            # 创建简历记录
            resume = Resume(
                id=resume_id,
                job_id=job_id,
                candidate_name=ai_result['candidateName'],
                email=ai_result.get('email'),
                phone=ai_result.get('phone'),
                file_url=file_url,
                ai_analysis=ai_result['aiAnalysis'],
                tags=[],
                created_by=current_user_id,
                updated_by=current_user_id
            )
            assign_tenant(resume)
            
            db.session.add(resume)
            uploaded_resumes.append(resume.to_dict())

            # 更新任务进度
            update_task(task_id, i + 1, 'success', f'成功处理: {file.filename}')
            print(f'[{i+1}/{len(files)}] ✓ 成功处理: {file.filename}')
            savepoint.commit()
            successful_staged_keys.add(staged_object_key)

        except (StorageQuotaExceeded, StorageUsageUnavailable):
            savepoint.rollback()
            db.session.rollback()
            for key in sorted(successful_staged_keys | ({staged_object_key} if staged_object_key else set())):
                delete_object(key)
            raise
        except Exception as err:
            savepoint.rollback()
            if staged_object_key:
                delete_object(staged_object_key)
            # 更新任务进度
            update_task(task_id, i + 1, 'error', f'处理失败: {str(err)}')
            print(f'[{i+1}/{len(files)}] ✗ 处理失败: {file.filename} - {str(err)}')
            errors.append({'filename': file.filename, 'error': str(err)})
        finally:
            # 清理 MinIO 模式下的临时文件
            if 'tmp_path' in dir() and tmp_path and os.path.exists(tmp_path):
                try: os.unlink(tmp_path)
                except: pass
                tmp_path = None
    
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        for key in sorted(successful_staged_keys):
            delete_object(key)
        raise
    for reference in sorted(pending_delete_references):
        delete_object_if_unreferenced(reference, tenant_id=job.tenant_id)
    
    print(f'\n[批量上传] 完成！成功: {len(uploaded_resumes)}, 失败: {len(errors)}, 替换: {len(replaced_resumes)}')
    
    if not uploaded_resumes:
        return jsonify({'error': '所有文件上传失败', 'details': errors}), 400
    
    return jsonify({
        'success': len(uploaded_resumes),
        'failed': len(errors),
        'replaced': len(replaced_resumes),
        'taskId': task_id,
        'resumes': uploaded_resumes,
        'errors': errors if errors else None,
        'replacedInfo': replaced_resumes if replaced_resumes else None
    }), 201

@resumes_bp.route('/<resume_id>', methods=['PUT'])
@jwt_required()
def update_resume(resume_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限更新简历')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    resume = Resume.query.get(resume_id)
    if not resume or not object_belongs_to_current_tenant(resume):
        return jsonify({'error': 'Not found'}), 404
    
    data = request.get_json()
    
    if 'candidateName' in data:
        resume.candidate_name = data['candidateName']
    if 'email' in data:
        resume.email = data['email']
    if 'phone' in data:
        resume.phone = data['phone']
    if 'tags' in data:
        resume.tags = data['tags']
    
    resume.updated_by = current_user_id
    db.session.commit()
    return jsonify(resume.to_dict())

@resumes_bp.route('/<resume_id>', methods=['DELETE'])
@jwt_required()
def delete_resume(resume_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限删除简历')
    if denied:
        return denied
    resume = Resume.query.get(resume_id)
    if not resume or not object_belongs_to_current_tenant(resume):
        return jsonify({'error': 'Not found'}), 404

    old_references = storage_reference_keys(resume.file_url)
    tenant_id = resume.tenant_id
    db.session.delete(resume)
    db.session.commit()
    for reference in sorted(old_references):
        delete_object_if_unreferenced(reference, tenant_id=tenant_id)

    return jsonify({'removed': True})

@resumes_bp.route('/<resume_id>/reanalyze', methods=['POST'])
@jwt_required()
def reanalyze_resume(resume_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限重新分析简历')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    resume = Resume.query.get(resume_id)
    if not resume or not object_belongs_to_current_tenant(resume):
        return jsonify({'error': '简历不存在'}), 404
    
    job = Job.query.get(resume.job_id)
    if not job or not object_belongs_to_current_tenant(job):
        return jsonify({'error': '关联岗位不存在'}), 404
    allowed = _require_resume_ai('resume_analysis')
    if not hasattr(allowed, 'resource_domain'):
        return allowed
    
    try:
        print(f'\n[重新分析] 简历ID: {resume_id}')
        print(f'[重新分析] 候选人: {resume.candidate_name}')

        # 读取文件（MinIO 或本地，自动适配）
        object_key = (resume.file_url or '').replace('/uploads/', '')
        if not file_exists(object_key):
            return jsonify({'error': '简历文件不存在'}), 404

        # 下载到临时文件用于文本提取
        ext = os.path.splitext(resume.file_url)[1].lower() or '.pdf'
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp_path = tmp.name
        try:
            download_to_file(object_key, tmp_path)
            file_content = extract_text_from_file(tmp_path)
        finally:
            try: os.unlink(tmp_path)
            except: pass

        # AI分析
        print('[重新分析] 开始AI分析...')
        ai_result = analyze_resume(file_content, job.title, job.description, job.scoring_criteria)
        
        # 更新简历
        resume.candidate_name = ai_result['candidateName']
        resume.email = ai_result.get('email') or resume.email
        resume.phone = ai_result.get('phone') or resume.phone
        resume.ai_analysis = ai_result['aiAnalysis']
        resume.updated_by = current_user_id
        
        db.session.commit()
        
        print('[重新分析] ✓ 完成')
        return jsonify(resume.to_dict())
        
    except Exception as err:
        print(f'[重新分析] 错误: {str(err)}')
        return jsonify({'error': f'重新分析失败: {str(err)}'}), 500
