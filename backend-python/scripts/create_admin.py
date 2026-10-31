"""Create or promote a controlled administrator account.

Usage:
  set ADMIN_EMAIL=admin@example.com
  set ADMIN_PASSWORD=StrongPassw0rd!
  python backend-python/scripts/create_admin.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import bcrypt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
from models import User, db  # noqa: E402


def _required(name: str) -> str:
    value = (os.getenv(name) or '').strip()
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


def _validate_password(password: str) -> None:
    if len(password) < 12:
        raise RuntimeError('ADMIN_PASSWORD must be at least 12 characters')
    classes = [
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ]
    if sum(classes) < 3:
        raise RuntimeError('ADMIN_PASSWORD must contain at least 3 character classes')


def main() -> int:
    email = _required('ADMIN_EMAIL').lower()
    password = _required('ADMIN_PASSWORD')
    name = (os.getenv('ADMIN_NAME') or '系统管理员').strip()
    _validate_password(password)

    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        if user:
            user.password_hash = password_hash
            user.name = user.name or name
            user.role = 'admin'
            user.status = 'active'
            action = 'promoted'
        else:
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=password_hash,
                name=name,
                role='admin',
                status='active',
            )
            db.session.add(user)
            action = 'created'
        db.session.commit()
    print(f'admin {action}: {email}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
