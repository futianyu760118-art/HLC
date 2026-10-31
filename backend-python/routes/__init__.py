from .auth import auth_bp
from .jobs import jobs_bp
from .resumes import resumes_bp
from .interviews import interviews_bp
from .misc import misc_bp
from .tasks import tasks_bp
from .hrm import hrm_bp
from .org import org_bp
from .portal import portal_bp
from .platform import platform_bp
from .extensions import extensions_bp
from .enterprise_applications import (
    enterprise_applications_platform_bp,
    enterprise_applications_public_bp,
)

__all__ = ['auth_bp', 'jobs_bp', 'resumes_bp', 'interviews_bp', 'misc_bp',
           'tasks_bp', 'hrm_bp', 'org_bp', 'portal_bp', 'platform_bp', 'extensions_bp',
           'enterprise_applications_platform_bp', 'enterprise_applications_public_bp']
