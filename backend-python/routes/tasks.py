from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from datetime import datetime

tasks_bp = Blueprint('tasks', __name__)

# 任务队列（内存存储，简单实现）
upload_tasks = {}

def create_task(task_id, total_files):
    """创建上传任务"""
    upload_tasks[task_id] = {
        'id': task_id,
        'total': total_files,
        'current': 0,
        'completed': 0,
        'failed': 0,
        'status': 'processing',
        'files': [],
        'created_at': datetime.now().isoformat()
    }
    return upload_tasks[task_id]

def update_task(task_id, current_file, status, message=''):
    """更新任务进度"""
    if task_id in upload_tasks:
        task = upload_tasks[task_id]
        task['current'] = current_file
        if status == 'success':
            task['completed'] += 1
        elif status == 'error':
            task['failed'] += 1
        
        task['files'].append({
            'index': current_file,
            'status': status,
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
        
        # 检查是否全部完成
        if task['current'] >= task['total']:
            task['status'] = 'completed'
        
        return task
    return None

def get_task(task_id):
    """获取任务状态"""
    return upload_tasks.get(task_id)

@tasks_bp.route('/upload/<task_id>', methods=['GET'])
@jwt_required()
def get_upload_task(task_id):
    """查询上传任务进度"""
    task = get_task(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)

