"""恒聘通 Flask 应用入口。

设计要点：
- 启动时强制初始化日志、请求中间件、错误处理器
- 健康检查真正触达数据库
- 全局错误处理器统一返回 JSON、隐藏栈信息
- 上传文件接口防御路径穿越
- 生产环境绝不开启 Flask debug
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from sqlalchemy import text
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import safe_join, secure_filename
from dotenv import load_dotenv

from config import Config
from logging_config import configure_logging
from models import db

# 必须最先加载 .env，再触发 Config 模块级校验
load_dotenv()
configure_logging()
logger = logging.getLogger('hengpintong.app')


def _register_request_lifecycle(app: Flask) -> None:
    """请求开始/结束钩子：注入 request_id、记录访问日志、回写响应头。"""

    @app.before_request
    def _start_request() -> None:
        from services.request_metadata import request_id_for_client

        g.request_id = request_id_for_client(request.headers.get('X-Request-ID'))
        g.request_start = time.perf_counter()
        # 清空模型层名称缓存，避免跨请求脏读
        from models import _reset_name_cache
        _reset_name_cache()

    @app.after_request
    def _end_request(response: Response) -> Response:
        duration_ms = (time.perf_counter() - getattr(g, 'request_start', time.perf_counter())) * 1000
        response.headers['X-Request-ID'] = getattr(g, 'request_id', '')
        # 安全响应头（与 Nginx 双层兜底）
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')

        # 跳过频繁的健康检查噪声
        if request.path != '/api/health':
            from services.request_metadata import remote_address_digest

            logger.info(
                'request',
                extra={
                    'status': response.status_code,
                    'duration_ms': round(duration_ms, 2),
                    'remote_hash': remote_address_digest(),
                    'tenant_id': getattr(g, 'tenant_id', None),
                },
            )
            # 慢请求告警（>2s 的 API 请求自动记 WARNING，便于排查性能问题）
            if duration_ms > 2000 and request.path.startswith('/api/'):
                logger.warning(
                    'slow_request',
                    extra={
                        'path': request.path,
                        'method': request.method,
                        'status': response.status_code,
                        'duration_ms': round(duration_ms, 2),
                        'request_id': getattr(g, 'request_id', ''),
                    },
                )
        return response


def _register_tenant_context(app: Flask) -> None:
    """Resolve SaaS tenant context and enforce tenant boundaries for APIs."""

    @app.before_request
    def _load_tenant_context():
        from services.tenancy import enforce_request_tenant_boundary, set_request_tenant_context

        set_request_tenant_context()
        return enforce_request_tenant_boundary()


def _register_error_handlers(app: Flask) -> None:
    """全局错误处理：统一 JSON 输出，绝不向客户端暴露栈。"""

    @app.errorhandler(HTTPException)
    def _handle_http(error: HTTPException):
        body = {
            'error': error.description or error.name,
            'code': error.code,
            'requestId': getattr(g, 'request_id', None),
        }
        return jsonify(body), error.code or 500

    @app.errorhandler(Exception)
    def _handle_unhandled(error: Exception):
        # 异常消息和堆栈可能夹带请求体或连接信息；这里只记录固定事件与类型。
        logger.error('unhandled_exception', extra={'error_type': type(error).__name__})
        body = {
            'error': '服务器内部错误，请稍后重试',
            'code': 500,
            'requestId': getattr(g, 'request_id', None),
        }
        return jsonify(body), 500


def _register_health(app: Flask) -> None:
    """K8s/容器友好的健康检查。

    /api/health   — liveness：进程是否活着（轻量）
    /api/ready    — readiness：能否真正服务流量（探数据库和对象存储）
    """

    @app.route('/api/health')
    def _health():
        return {'ok': True, 'service': 'api', 'time': datetime.utcnow().isoformat() + 'Z'}

    @app.route('/api/ready')
    def _ready():
        try:
            db.session.execute(text('SELECT 1'))
            from services import storage
            storage_state = storage.storage_readiness()
            if not storage_state.get('ok'):
                return jsonify({
                    'ok': False,
                    'db': 'up',
                    'storage': 'down',
                    'error': 'object storage unreachable',
                    'time': datetime.utcnow().isoformat() + 'Z',
                }), 503
            return {
                'ok': True,
                'db': 'up',
                'storage': storage_state.get('mode', 'local'),
                'time': datetime.utcnow().isoformat() + 'Z',
            }
        except Exception:  # pragma: no cover
            logger.error('readiness_check_failed')
            return jsonify({'ok': False, 'db': 'down', 'error': 'db unreachable'}), 503


def _register_uploads(app: Flask) -> None:
    """上传文件下载（防路径穿越）。

    所有上传文件都必须鉴权访问。旧 /uploads 路径仅作为兼容入口保留；
    前端正式入口为 /api/files/<key>，通过 fetch 携带 Authorization。
    """
    upload_root = Path(app.config['UPLOAD_FOLDER']).resolve()

    def _resolve_upload_path(filename: str):
        # safe_join 处理 '..'、绝对路径等；返回 None 表示越界
        target = safe_join(str(upload_root), filename)
        if not target:
            logger.warning('upload_path_traversal_attempt', extra={'filename': filename})
            return None, jsonify({'error': 'invalid path'}), 400
        target_path = Path(target).resolve()
        # 二次校验最终路径仍在上传目录内
        if upload_root not in target_path.parents and target_path != upload_root:
            return None, jsonify({'error': 'invalid path'}), 400
        return target_path, None, None

    def _send_upload(filename: str, disposition: str = 'inline'):
        target_path, error_response, status = _resolve_upload_path(filename)
        if error_response:
            return error_response, status

        as_attachment = disposition == 'attachment'
        # 本地有文件直接返回
        if target_path.is_file():
            return send_from_directory(
                str(upload_root),
                filename,
                as_attachment=as_attachment,
                download_name=target_path.name if as_attachment else None,
            )

        # 本地无文件 → 尝试从 MinIO 回源（支持对象存储迁移后的透明下载）
        try:
            from services.storage import _get_client, _MINIO_BUCKET
            client = _get_client()
            if client is not None:
                # 兼容老数据：file_url 可能是 /uploads/{uuid}.pdf（无 resumes/ 前缀）
                # MinIO 中存在 resumes/{uuid}.pdf，尝试两种 key
                candidate_keys = [filename]
                if not filename.startswith('resumes/') and filename.lower().endswith(('.pdf', '.doc', '.docx')):
                    candidate_keys.append(f'resumes/{filename}')
                for try_key in candidate_keys:
                    try:
                        response = client.get_object(_MINIO_BUCKET, try_key)
                        data = response.read()
                        response.close()
                        response.release_conn()
                        if data:
                            import mimetypes
                            ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
                            safe_name = secure_filename(Path(filename).name) or 'download'
                            cd = 'attachment' if as_attachment else 'inline'
                            return Response(data, mimetype=ctype, headers={
                                'Content-Disposition': f'{cd}; filename="{safe_name}"',
                                'Cache-Control': 'private, max-age=3600',
                            })
                    except Exception:
                        continue  # 试下一个 key
        except Exception as exc:
            logger.warning('upload_minio_fallback_failed', extra={'upload_file': filename, 'err': str(exc)})

        return jsonify({'error': 'file not found'}), 404

    def _require_file_auth(filename: str | None = None):
        from flask_jwt_extended import verify_jwt_in_request
        try:
            verify_jwt_in_request()
        except Exception:
            return jsonify({'error': 'unauthorized'}), 401
        if filename and filename.startswith('tenants/'):
            from services.tenancy import current_tenant_id
            parts = filename.split('/', 2)
            file_tenant_id = parts[1] if len(parts) > 1 else None
            if not file_tenant_id or file_tenant_id != current_tenant_id():
                return jsonify({'error': '无权访问其他企业文件', 'code': 'FILE_TENANT_FORBIDDEN'}), 403
        return None

    @app.route('/api/media/<path:filename>')
    def _api_media(filename: str):
        """受保护媒体（视频/大文件）的签名访问端点。

        校验 ?exp=&sig=（HMAC-SHA256，密钥=SECRET_KEY），不要求 Authorization header，
        这样 <video> 标签可直接播放。支持 Range 请求（本地走 send_from_directory，
        MinIO 走 get_object offset/length），可流式播放 / 拖动进度。
        签名由 portal._signed_media_url 生成，短期有效（2h）。
        """
        from services.portal_media_auth import verify_media_signature
        ok, reason = verify_media_signature(filename, request.args.get('exp'), request.args.get('sig'))
        if not ok:
            return jsonify({'error': reason or 'unauthorized'}), 401
        from services.storage import stream_media_range
        result = stream_media_range(filename, request.headers.get('Range', ''))
        mode = result.get('mode')
        if mode == 'local':
            return send_from_directory(result['path'], result['filename'], as_attachment=False)
        if mode == 'stream':
            return Response(result['body'], status=result['status'], headers=result['headers'])
        return jsonify({'error': 'file not found'}), 404

    @app.route('/api/files/<path:filename>')
    def _api_file(filename: str):
        auth_error = _require_file_auth(filename)
        if auth_error:
            return auth_error
        disposition = 'attachment' if request.args.get('disposition') == 'attachment' else 'inline'
        logger.info('protected_file_access', extra={'file_key': filename, 'disposition': disposition})
        return _send_upload(filename, disposition=disposition)

    @app.route('/uploads/<path:filename>')
    def _uploaded_file(filename: str):
        auth_error = _require_file_auth(filename)
        if auth_error:
            return auth_error
        logger.info('legacy_upload_access', extra={'file_key': filename})
        return _send_upload(filename, disposition='inline')


def _register_password_change_gate(app: Flask) -> None:
    """Block business APIs until users replace their initial password."""

    allowed_exact = {
        '/api/auth/login',
        '/api/auth/register',
        '/api/auth/change-password',
        '/api/platform/auth/login',
        '/api/portal/auth/login',
        '/api/portal/auth/change-password',
        # Public enterprise-service applications deliberately work without an
        # account.  The shared browser API client may still carry an existing
        # bearer token, so this route must not inherit that user's initial
        # password-change gate.
        '/api/public/enterprise-applications',
        '/api/health',
        '/api/ready',
    }

    @app.before_request
    def _require_changed_password():
        if request.method == 'OPTIONS':
            return None
        if not request.path.startswith('/api/') or request.path in allowed_exact:
            return None

        from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request
        from models import EmployeePortalAccount, User

        try:
            verify_jwt_in_request(optional=True)
        except Exception:
            return None

        user_id = get_jwt_identity()
        if not user_id:
            return None
        claims = get_jwt() or {}
        account_type = claims.get('account_type') or 'hrm'

        if account_type == 'employee_portal':
            if not (request.path.startswith('/api/portal/') or request.path.startswith('/api/files/')):
                return jsonify({
                    'error': '员工门户账号不能访问管理后台',
                    'code': 'PORTAL_ACCOUNT_ONLY',
                }), 403
            account = db.session.get(EmployeePortalAccount, user_id)
            if account and bool(getattr(account, 'must_change_password', False)):
                return jsonify({
                    'error': '首次登录需要修改密码',
                    'code': 'PASSWORD_CHANGE_REQUIRED',
                }), 403
            return None

        if request.path.startswith('/api/portal/'):
            return jsonify({
                'error': '请使用员工门户账号登录',
                'code': 'EMPLOYEE_PORTAL_LOGIN_REQUIRED',
            }), 403

        user = db.session.get(User, user_id)
        if user and bool(getattr(user, 'must_change_password', False)):
            return jsonify({
                'error': '首次登录需要修改密码',
                'code': 'PASSWORD_CHANGE_REQUIRED',
            }), 403
        return None


def _init_database(app: Flask) -> None:
    """启动时建表与迁移；失败则抛出，让容器重启而非"假活"。"""
    with app.app_context():
        try:
            from schema_migrations import ensure_schema, schema_migration_lock, seed_defaults
            from services.ai_resource_governance import seed_ai_resource_defaults
            with schema_migration_lock():
                db.create_all()
                ensure_schema()
                seed_defaults()
                seed_ai_resource_defaults()
            logger.info('database_init_complete')
        except Exception:
            logger.exception('database_init_failed')
            # 生产环境抛出阻止启动；开发可设 ALLOW_DB_INIT_FAIL=1 跳过
            if os.getenv('ALLOW_DB_INIT_FAIL') != '1':
                raise


def create_app() -> Flask:
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.from_object(Config)

    # 扩展
    db.init_app(app)
    from services.tenancy import register_tenant_orm_filters
    register_tenant_orm_filters()
    JWTManager(app)

    # CORS
    cors_origins = app.config['CORS_ORIGINS']
    cors_kwargs = {
        'methods': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        'allow_headers': ['Content-Type', 'Authorization', 'X-Request-ID', 'Idempotency-Key'],
        'expose_headers': ['X-Request-ID', 'Content-Disposition'],
    }
    if cors_origins == '*':
        cors_kwargs['origins'] = '*'
    else:
        cors_kwargs['origins'] = cors_origins
        cors_kwargs['supports_credentials'] = True

    CORS(
        app,
        resources={
            r'/api/*': cors_kwargs,
            r'/uploads/*': {'origins': cors_origins, 'methods': ['GET', 'OPTIONS']},
        },
    )

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # 蓝图（保留原 URL 前缀，向后兼容）
    from routes import (
        auth_bp, enterprise_applications_platform_bp, enterprise_applications_public_bp,
        extensions_bp, hrm_bp, interviews_bp, jobs_bp, misc_bp, org_bp, platform_bp, portal_bp,
        resumes_bp, tasks_bp,
    )
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(jobs_bp, url_prefix='/api/jobs')
    app.register_blueprint(resumes_bp, url_prefix='/api/resumes')
    app.register_blueprint(interviews_bp, url_prefix='/api/interviews')
    app.register_blueprint(misc_bp, url_prefix='/api')
    app.register_blueprint(tasks_bp, url_prefix='/api/tasks')
    app.register_blueprint(hrm_bp, url_prefix='/api/hrm')
    app.register_blueprint(org_bp, url_prefix='/api/org')
    app.register_blueprint(extensions_bp, url_prefix='/api/extensions')
    app.register_blueprint(portal_bp, url_prefix='/api/portal')
    app.register_blueprint(platform_bp, url_prefix='/api/platform')
    app.register_blueprint(enterprise_applications_public_bp, url_prefix='/api/public')
    app.register_blueprint(enterprise_applications_platform_bp, url_prefix='/api/platform')

    _register_request_lifecycle(app)
    _register_tenant_context(app)
    _register_password_change_gate(app)
    _register_error_handlers(app)
    _register_health(app)
    _register_uploads(app)
    _init_database(app)

    # 对象存储（视频/大文件）：预建 bucket；失败自动回退本地，不致命
    try:
        from services import storage
        storage.init_bucket()
    except Exception:  # pragma: no cover
        logger.warning('storage_init_failed_fallback_local')

    # 学习提醒定时调度（每日检查必修课/考试截止，自动催学）。
    # CLI 导入/维护脚本可通过环境变量禁用，避免建 app 时产生业务通知副作用。
    if os.getenv('DISABLE_STUDY_REMINDER_SCHEDULER') != '1':
        try:
            from services.study_reminder import start_reminder_scheduler
            start_reminder_scheduler(app)
        except Exception:  # pragma: no cover
            logger.warning('study_reminder_start_failed')

    # 00001 公司 OA 员工主数据每日同步。外部 SQL Server 严格只读；多
    # Gunicorn worker 依靠 MySQL advisory lock 和最近成功批次避免重复执行。
    if os.getenv('DISABLE_OA_EMPLOYEE_SYNC_SCHEDULER') != '1':
        try:
            from services.oa_employee_sync import start_oa_employee_scheduler
            start_oa_employee_scheduler(app)
        except Exception:  # pragma: no cover
            logger.warning('oa_employee_scheduler_start_failed')

    if os.getenv('DISABLE_ATTENDANCE_PUNCH_SYNC_SCHEDULER') != '1':
        try:
            from services.attendance_punch_sync import start_attendance_punch_scheduler
            start_attendance_punch_scheduler(app)
        except Exception:  # pragma: no cover
            logger.warning('attendance_punch_scheduler_start_failed')

    return app


if __name__ == '__main__':
    application = create_app()
    is_prod = os.getenv('NODE_ENV', '').lower() == 'production'
    port = int(os.getenv('PORT', '8888'))
    logger.info(
        'server_starting',
        extra={
            'host': '0.0.0.0',
            'port': port,
            'env': 'production' if is_prod else 'development',
        },
    )
    # 生产严禁 debug；生产环境应由 gunicorn 启动而不是这里
    application.run(host='0.0.0.0', port=port, debug=not is_prod)
