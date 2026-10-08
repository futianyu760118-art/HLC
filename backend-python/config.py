"""应用配置。

设计原则：
1. 生产环境必须通过环境变量提供凭据。开发环境若缺失会启动失败并给出明确错误。
2. 不在代码里保留任何真实凭据作为兜底默认值。
3. 长度敏感的密钥（JWT/SECRET）做最小长度校验。
"""

import os
import secrets
import sys
from datetime import timedelta
from urllib.parse import quote_plus


def _is_production() -> bool:
    return os.getenv('NODE_ENV', '').lower() == 'production'


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        if _is_production():
            sys.stderr.write(
                f'[FATAL] 环境变量 {name} 必须设置（生产环境）。\n'
            )
            raise RuntimeError(f'Missing required environment variable: {name}')
        # 开发环境给一个一次性随机值，避免在源码里写死
        value = secrets.token_urlsafe(48)
        sys.stderr.write(
            f'[WARN] 环境变量 {name} 未设置，已生成临时值（仅开发可用）。\n'
        )
    return value


def _required_secret(name: str, min_len: int = 32) -> str:
    value = _required(name)
    if len(value) < min_len:
        if _is_production():
            raise RuntimeError(
                f'{name} 长度必须 >= {min_len}，当前 {len(value)}。'
                f' 生成命令：python -c "import secrets; print(secrets.token_urlsafe(64))"'
            )
        sys.stderr.write(f'[WARN] {name} 长度小于 {min_len}（仅开发环境放过）。\n')
    return value


class Config:
    """应用配置。"""

    # Flask
    SECRET_KEY = _required_secret('SECRET_KEY', min_len=32)

    # JWT
    JWT_SECRET_KEY = _required_secret('JWT_SECRET', min_len=32)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        hours=int(os.getenv('JWT_ACCESS_TOKEN_HOURS', '12'))
    )

    # MySQL
    MYSQL_HOST = os.getenv('DB_HOST', 'mysql')
    MYSQL_PORT = int(os.getenv('DB_PORT', '3306'))
    MYSQL_USER = _required('DB_USER')
    MYSQL_PASSWORD = _required('DB_PASSWORD')
    MYSQL_DB = os.getenv('DB_NAME', 'hengpintong')

    # 用 quote_plus 转义凭据中的特殊字符，避免 URL 解析错乱
    SQLALCHEMY_DATABASE_URI = (
        f'mysql+pymysql://{quote_plus(MYSQL_USER)}:{quote_plus(MYSQL_PASSWORD)}'
        f'@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 生产关闭 SQL 日志（性能 + 不打印参数）
    SQLALCHEMY_ECHO = not _is_production()
    # 连接池（已针对企业培训场景调优）
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,           # 连接前检查有效性（防 MySQL wait_timeout 断连）
        'pool_recycle': 280,             # 连接回收周期 < MySQL wait_timeout(28800s 默认)
        'pool_size': int(os.getenv('DB_POOL_SIZE', '10')),     # 常驻连接数（默认 5→10，培训系统并发更高）
        'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '20')), # 溢出连接数（默认 10→20）
        'pool_timeout': int(os.getenv('DB_POOL_TIMEOUT', '10')), # 获取连接超时（秒，默认无限制→10s 快速失败）
    }

    # 上传（培训视频可达数百 MB，取 MAX_UPLOAD_MB 和 MAX_VIDEO_UPLOAD_MB 的较大值）
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = max(
        int(os.getenv('MAX_UPLOAD_MB', '10')),
        int(os.getenv('MAX_VIDEO_UPLOAD_MB', '500')),
    ) * 1024 * 1024
    ALLOWED_EXTENSIONS = {
        'pdf', 'doc', 'docx', 'txt',
        'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'webp',
    }

    # CORS — 生产严禁 *
    _frontend_url = os.getenv('FRONTEND_URL', '').strip()
    if _is_production() and (not _frontend_url or _frontend_url == '*'):
        raise RuntimeError(
            '生产环境必须设置 FRONTEND_URL 为真实域名（多个用英文逗号分隔），不允许 *'
        )
    # 兼容多域名，逗号分隔
    if not _frontend_url:
        CORS_ORIGINS = ['http://localhost:5173']
    elif _frontend_url == '*':
        CORS_ORIGINS = '*'
    else:
        CORS_ORIGINS = [s.strip() for s in _frontend_url.split(',') if s.strip()]

    # AI（硅基流动）
    SILICONFLOW_API_KEY = os.getenv('SILICONFLOW_API_KEY', '')
    SILICONFLOW_API_URL = os.getenv(
        'SILICONFLOW_API_URL', 'https://api.siliconflow.cn/v1'
    )
    SILICONFLOW_MODEL = os.getenv('SILICONFLOW_MODEL', 'deepseek-ai/DeepSeek-V3')

    # 对象存储（MinIO/S3）。未配置时 storage.py 自动回退到本地 /uploads。
    MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', '')
    MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', '')
    MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', '')
    MINIO_BUCKET = os.getenv('MINIO_BUCKET', 'hrm-courses')
    MINIO_SECURE = os.getenv('MINIO_SECURE', 'false').lower() in ('1', 'true', 'yes', 'on')
    # 视频上传上限：默认 500MB（培训视频通常 100~400MB）
    MAX_VIDEO_UPLOAD_MB = int(os.getenv('MAX_VIDEO_UPLOAD_MB', '500'))


class IntentRouterConfig:
    """Assistant Intent Router (v2) 环境变量名 + 默认值的集中登记。

    设计目标：

    1. 把 ``services.assistant_core.intent_router`` 各模块以前直接写在源码里的
       环境变量名集中到这一处，重命名时只动这一个文件。
    2. 不破坏现有 :func:`os.environ` + ``module.reload()`` 的测试模式：每个
       下游模块仍然按需读 ``os.environ``，本类只暴露 *名字常量* 与 *默认值
       常量*，不缓存任何运行期值。
    3. 不在导入期触碰生产配置（不放进 :class:`Config`），避免单元测试在不需
       要 DB / JWT 的场景下被 ``_required_*`` 副作用拖累。

    用法（在下游模块）::

        from config import IntentRouterConfig

        _ENV_V2_ENABLED = IntentRouterConfig.ENV_V2_ENABLED
        DEFAULT_LOW_THRESHOLD = IntentRouterConfig.DEFAULT_LOW_THRESHOLD
    """

    # --- FeatureFlag ------------------------------------------------------
    ENV_V2_ENABLED = 'ASSISTANT_INTENT_ROUTER_V2_ENABLED'
    ENV_ROLLOUT_PCT = 'ASSISTANT_INTENT_ROUTER_ROLLOUT_PCT'
    DEFAULT_V2_ENABLED = False
    DEFAULT_ROLLOUT_PCT = 0

    # --- ConfidenceGate ---------------------------------------------------
    ENV_LOW_THRESHOLD = 'ASSISTANT_INTENT_ROUTER_LOW_THRESHOLD'
    ENV_HIGH_THRESHOLD = 'ASSISTANT_INTENT_ROUTER_HIGH_THRESHOLD'
    DEFAULT_LOW_THRESHOLD = 0.50
    DEFAULT_HIGH_THRESHOLD = 0.75

    # --- Reranker ---------------------------------------------------------
    ENV_RERANKER_TIMEOUT_MS = 'ASSISTANT_INTENT_ROUTER_RERANKER_TIMEOUT_MS'
    DEFAULT_RERANKER_TIMEOUT_MS = 3000

    # --- FastPath ---------------------------------------------------------
    ENV_FASTPATH_KEYWORDS_PATH = 'ASSISTANT_INTENT_ROUTER_FASTPATH_KEYWORDS_PATH'
    #: 默认指向 ``services/assistant_core/intent_router/fastpath_keywords.yaml``
    #: （由调用方按需拼成绝对路径，本类只承诺文件名）。
    DEFAULT_FASTPATH_KEYWORDS_FILENAME = 'fastpath_keywords.yaml'

    # --- EntityMemory -----------------------------------------------------
    ENV_ENTITY_MEMORY_TTL_MINUTES_DEFAULT = (
        'ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_DEFAULT'
    )
    ENV_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW = (
        'ASSISTANT_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW'
    )
    DEFAULT_ENTITY_MEMORY_TTL_MINUTES = 30
    DEFAULT_ENTITY_MEMORY_TTL_MINUTES_TIME_WINDOW = 10

    # --- EmbeddingClient（非 8 个核心变量之一，但与 Intent Router 同源） --
    ENV_EMBEDDING_MODEL = 'ASSISTANT_EMBEDDING_MODEL'
    DEFAULT_EMBEDDING_MODEL = 'BAAI/bge-m3'
