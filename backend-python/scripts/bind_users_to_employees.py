"""按 email 批量绑定 User ↔ Employee。

用法（在 backend-python 目录下）::

    python -m scripts.bind_users_to_employees          # 默认 dry-run，只打印
    python -m scripts.bind_users_to_employees --apply  # 真正写库

匹配规则（幂等）：User.email == Employee.email（忽略大小写）。
- 已绑定的 User 跳过。
- 找不到对应 Employee 的 User 计入 unmatched。
- 一个 Employee 被多个 User 匹配时，绑定第一个未绑定的 User（打印告警）。
"""

from __future__ import annotations

import argparse
import sys

# 允许以 `python scripts/bind_users_to_employees.py` 或 `python -m scripts...` 运行
# 前者需要把 backend-python 加入 sys.path（脚本运行时 cwd 通常就是该目录）。
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.user_employee_binding import bind_users_by_email  # noqa: E402


def _app():
    from app import create_app
    app = create_app()
    return app


def main():
    parser = argparse.ArgumentParser(description='按 email 绑定 User.employee_id')
    parser.add_argument('--apply', action='store_true', help='真正写库（默认 dry-run）')
    args = parser.parse_args()

    app = _app()
    with app.app_context():
        stats = bind_users_by_email(dry_run=not args.apply)
    mode = 'APPLY' if args.apply else 'DRY-RUN'
    print(f'\n=== 绑定完成（{mode}）===')
    print(f"账号总数:         {stats['users_total']}")
    print(f"本次匹配并绑定:   {stats['matched']}")
    print(f"已绑定(跳过):     {stats['already_bound']}")
    print(f"无员工档案匹配:   {stats['no_employee_match']}")
    if not args.apply and stats['matched']:
        print('\n(以上为预演，加 --apply 真正写库)')


if __name__ == '__main__':
    main()
