from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import uuid
from datetime import datetime

from models import db, Job
from services.authz import RECRUITMENT_ROLES, require_roles
from services.tenancy import assign_tenant, object_belongs_to_current_tenant

jobs_bp = Blueprint('jobs', __name__)

@jobs_bp.route('/', methods=['GET'])
@jwt_required()
def get_jobs():
    denied = require_roles(RECRUITMENT_ROLES, '无权限查看招聘岗位')
    if denied:
        return denied
    query = Job.query.order_by(Job.created_at.desc())
    page = request.args.get('page', type=int)
    size = request.args.get('size', type=int, default=50)
    if page and page > 0:
        size = max(1, min(size, 200))
        total = query.count()
        jobs = query.offset((page - 1) * size).limit(size).all()
        return jsonify({
            'items': [job.to_dict() for job in jobs],
            'total': total,
            'page': page,
            'size': size,
            'pages': (total + size - 1) // size,
        })
    jobs = query.all()
    return jsonify([job.to_dict() for job in jobs])

@jobs_bp.route('/', methods=['POST'])
@jwt_required()
def create_job():
    denied = require_roles(RECRUITMENT_ROLES, '无权限创建招聘岗位')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    data = request.get_json()
    title = data.get('title')
    description = data.get('description', '')
    scoring_criteria = data.get('scoringCriteria')
    category = data.get('category')
    department = data.get('department')
    department_id = data.get('departmentId')
    level = data.get('level')
    responsibilities = data.get('responsibilities')
    requirements = data.get('requirements')
    headcount = data.get('headcount', 1)
    location = data.get('location')
    employment_type = data.get('employmentType', '全职')
    salary_range = data.get('salaryRange')
    
    if not title:
        return jsonify({'error': 'Missing title'}), 400
    
    now = datetime.utcnow()
    job = Job(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        status='open',
        scoring_criteria=scoring_criteria,
        category=category,
        department=department,
        department_id=department_id,
        level=level,
        responsibilities=responsibilities,
        requirements=requirements,
        headcount=headcount,
        location=location,
        employment_type=employment_type,
        salary_range=salary_range,
        created_at=now,
        updated_at=now,
        created_by=current_user_id,
        updated_by=current_user_id
    )
    assign_tenant(job)
    
    db.session.add(job)
    db.session.commit()
    
    return jsonify(job.to_dict()), 201

@jobs_bp.route('/<job_id>', methods=['PUT'])
@jwt_required()
def update_job(job_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限更新招聘岗位')
    if denied:
        return denied
    current_user_id = get_jwt_identity()
    job = Job.query.get(job_id)
    if not job or not object_belongs_to_current_tenant(job):
        return jsonify({'error': 'Not found'}), 404
    
    data = request.get_json()
    
    if 'title' in data:
        job.title = data['title']
    if 'description' in data:
        job.description = data['description']
    if 'status' in data:
        job.status = data['status']
    if 'scoringCriteria' in data:
        job.scoring_criteria = data['scoringCriteria']

    optional_fields = {
        'category': 'category',
        'department': 'department',
        'departmentId': 'department_id',
        'level': 'level',
        'responsibilities': 'responsibilities',
        'requirements': 'requirements',
        'headcount': 'headcount',
        'location': 'location',
        'employmentType': 'employment_type',
        'salaryRange': 'salary_range',
    }
    for input_key, attr in optional_fields.items():
        if input_key in data:
            setattr(job, attr, data[input_key])
    
    job.updated_at = datetime.utcnow()
    job.updated_by = current_user_id
    db.session.commit()
    
    return jsonify(job.to_dict())

@jobs_bp.route('/<job_id>', methods=['DELETE'])
@jwt_required()
def delete_job(job_id):
    denied = require_roles(RECRUITMENT_ROLES, '无权限删除招聘岗位')
    if denied:
        return denied
    job = Job.query.get(job_id)
    if not job or not object_belongs_to_current_tenant(job):
        return jsonify({'error': 'Not found'}), 404
    
    db.session.delete(job)
    db.session.commit()
    
    return jsonify({'removed': True})
