"""把本地 uploads 目录的简历文件迁移到 MinIO 对象存储。

用法（在 backend-python 目录运行，或容器内 /app 运行）：
    python scripts/migrate_resumes_to_minio.py

行为：
- 遍历本地 uploads/ 根目录的所有 .pdf/.doc/.docx 文件
- 上传到 MinIO bucket 的 resumes/ 前缀下
- 已存在的跳过（幂等，可重复运行）
- 不删除本地文件（迁移确认无误后手动清理）
"""
import os
import sys

# 确保能 import services
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from services.storage import _get_client, _MINIO_BUCKET, _upload_folder


def migrate():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')

    client = _get_client()
    if client is None:
        print('[ERROR] MinIO not available. Check MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY env.')
        sys.exit(1)

    with app.app_context():
        upload_dir = _upload_folder()
        print(f'[migrate] Upload dir: {upload_dir}')
        print(f'[migrate] MinIO bucket: {_MINIO_BUCKET}')

        # 收集本地简历文件
        ALLOWED = {'.pdf', '.doc', '.docx'}
        local_files = []
        for name in os.listdir(str(upload_dir)):
            fp = upload_dir / name
            if fp.is_file() and fp.suffix.lower() in ALLOWED:
                local_files.append(fp)

        print(f'[migrate] Found {len(local_files)} resume files locally')

        # 获取 MinIO 已有对象列表（用于跳过）
        existing = set()
        try:
            for obj in client.list_objects(_MINIO_BUCKET, prefix='resumes/'):
                existing.add(obj.object_name)
        except Exception:
            pass
        print(f'[migrate] {len(existing)} objects already in MinIO resumes/')

        uploaded = 0
        skipped = 0
        failed = 0
        for fp in local_files:
            key = f'resumes/{fp.name}'
            if key in existing:
                skipped += 1
                continue
            try:
                from io import BytesIO
                data = fp.read_bytes()
                client.put_object(_MINIO_BUCKET, key, BytesIO(data), length=len(data),
                                  content_type='application/pdf')
                uploaded += 1
                if uploaded % 50 == 0:
                    print(f'  ... {uploaded} uploaded')
            except Exception as e:
                print(f'  [FAIL] {fp.name}: {e}')
                failed += 1

        print(f'\n[migrate] Done: {uploaded} uploaded, {skipped} skipped, {failed} failed')
        print(f'[migrate] Local files kept. Verify downloads work, then manually remove if desired.')


if __name__ == '__main__':
    migrate()
