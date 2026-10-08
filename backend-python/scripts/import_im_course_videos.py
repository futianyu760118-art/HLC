"""IM 系统功能培训课程导入脚本。

从 /app/uploads/_im_course_videos 目录读取 6 个模块培训视频（成片汇总），创建：
  1 个课程 + 6 个章节（每章 1 个课时）

每个视频上传到 MinIO（或本地回退），设置 video_key 和 duration。
不创建任何课程指派：按 portal 可见性规则，无指派课程 = 全员可见（公开课）。

用法（容器内）:
    python /app/uploads/_im_course_videos/import_im_course_videos.py --tenant-id <tenant-uuid>
"""
import argparse
import os
import struct
import sys
import uuid

sys.path.insert(0, '/app')

from models import db, Course, CourseChapter, CourseHour, Tenant
from app import create_app
from services import storage

IMPORT_DIR = '/app/uploads/_im_course_videos'

# 课程结构：(章节名, [(课时标题, 视频文件名), ...])
STRUCTURE = [
    ('01 登录与界面总览', [('登录与界面总览', '01-登录与界面总览.mp4')]),
    ('02 单聊与消息操作', [('单聊与消息操作', '02-单聊与消息操作.mp4')]),
    ('03 群聊与群管理', [('群聊与群管理', '03-群聊与群管理.mp4')]),
    ('04 通讯录与好友管理', [('通讯录与好友管理', '04-通讯录与好友管理.mp4')]),
    ('05 应用中心与网盘', [('应用中心与网盘', '05-应用中心与网盘.mp4')]),
    ('06 AI助手与账号设置', [('AI助手与账号设置', '06-AI助手与账号设置.mp4')]),
]

COURSE_TITLE = 'IM 系统功能培训'
COURSE_SHORT_DESC = 'OpenCorp IM 即时通讯系统操作演示：登录、单聊、群聊、通讯录、应用中心与 AI 助手。'
COURSE_CONTENT = '本课程按功能模块逐集演示 OpenCorp IM 的常用操作，共 6 个章节视频，适合新员工快速上手 IM 通讯工具。'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='导入 IM 系统功能培训课程到指定企业')
    parser.add_argument('--tenant-id', required=True, help='目标企业 UUID；不允许无企业归属导入')
    return parser.parse_args(argv)


def upload_training_video(path: str, object_key: str, *, tenant_id: str) -> str:
    if not str(tenant_id or '').strip():
        raise ValueError('tenant_id is required')
    with open(path, 'rb') as fh:
        return storage.upload_video(
            fh,
            object_key,
            content_type='video/mp4',
            tenant_id=tenant_id,
        )


def commit_import(staged_object_keys, *, tenant_id: str) -> None:
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        for key in staged_object_keys:
            storage.delete_object_if_unreferenced(key, tenant_id=tenant_id)
        raise


def read_mp4_duration(path: str) -> int:
    """全文件解析 MP4 mvhd atom，返回时长（秒，四舍五入）。失败返回 0。

    注意：不能只读文件头 2MB——部分编码器的 moov 在 mdat 之后，
    必须扫描整个文件才能找到 mvhd。
    """
    try:
        with open(path, 'rb') as f:
            data = f.read()
        n = len(data)
        pos = 0
        while pos + 8 <= n:
            size = struct.unpack('>I', data[pos:pos + 4])[0]
            atom_type = data[pos + 4:pos + 8]
            if size == 1:
                if pos + 16 > n:
                    break
                size = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
                header = 16
            elif size == 0:
                size = n - pos
                header = 8
            else:
                header = 8
            if atom_type == b'moov':
                inner = pos + header
                end = min(pos + size, n)
                while inner + 8 <= end:
                    isz = struct.unpack('>I', data[inner:inner + 4])[0]
                    itype = data[inner + 4:inner + 8]
                    if isz == 1:
                        if inner + 16 > end:
                            break
                        isz = struct.unpack('>Q', data[inner + 8:inner + 16])[0]
                        iheader = 16
                    elif isz == 0:
                        isz = end - inner
                        iheader = 8
                    else:
                        iheader = 8
                    if itype == b'mvhd':
                        version = data[inner + iheader]
                        off = inner + iheader + 4  # version(1) + flags(3)
                        if version == 1:
                            timescale = struct.unpack('>I', data[off + 16:off + 20])[0]
                            duration = struct.unpack('>Q', data[off + 20:off + 28])[0]
                        else:
                            timescale = struct.unpack('>I', data[off + 8:off + 12])[0]
                            duration = struct.unpack('>I', data[off + 12:off + 16])[0]
                        return round(duration / timescale) if timescale else 0
                    inner += isz
                break
            pos += size
    except Exception as e:
        print(f'  时长读取失败 {path}: {e}')
    return 0


def main(argv=None):
    args = parse_args(argv)
    app = create_app()
    with app.app_context():
        tenant = db.session.get(Tenant, args.tenant_id)
        if tenant is None:
            raise SystemExit('指定企业不存在，已拒绝导入')
        tenant_id = tenant.id

        # 1) 课程（若同名已存在则不重复创建）
        course = Course.query.filter_by(
            tenant_id=tenant_id,
            title=COURSE_TITLE,
        ).first()
        if not course:
            course = Course(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                title=COURSE_TITLE,
                category_id=None,
                is_required=False,
                is_show=True,
                short_desc=COURSE_SHORT_DESC,
                content=COURSE_CONTENT,
                class_hour=0,
                sort=0,
            )
            db.session.add(course)
            db.session.flush()
            print(f'创建课程: {course.title} ({course.id})')
        else:
            print(f'课程已存在: {course.title}，将补充章节/课时')

        # 2) 章节 + 课时 + 视频上传
        total_hours = 0
        staged_object_keys = []
        for ch_idx, (ch_name, hours) in enumerate(STRUCTURE):
            chapter = CourseChapter(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                course_id=course.id,
                name=ch_name,
                sort=ch_idx,
            )
            db.session.add(chapter)
            db.session.flush()
            print(f'  章节: {ch_name}')

            for h_idx, (h_title, vfile) in enumerate(hours):
                hour_id = str(uuid.uuid4())
                vpath = os.path.join(IMPORT_DIR, vfile)
                duration = read_mp4_duration(vpath)
                object_key = f'courses/{course.id}/{hour_id}.mp4'
                uploaded = False
                if os.path.exists(vpath):
                    try:
                        object_key = upload_training_video(
                            vpath,
                            object_key,
                            tenant_id=tenant_id,
                        )
                        staged_object_keys.append(object_key)
                        uploaded = True
                    except Exception as e:
                        print(f'    !! 上传失败 {vfile}: {e}')
                else:
                    print(f'    !! 视频文件不存在: {vfile}')

                hour = CourseHour(
                    id=hour_id,
                    tenant_id=tenant_id,
                    course_id=course.id,
                    chapter_id=chapter.id,
                    title=h_title,
                    type='VIDEO',
                    sort=h_idx,
                    video_key=object_key if uploaded else None,
                    duration=duration,
                )
                db.session.add(hour)
                total_hours += 1
                status = 'OK' if uploaded else 'NO-VIDEO'
                print(f'    [{status}] {h_title} ({duration}s)')

        course.class_hour = total_hours
        commit_import(staged_object_keys, tenant_id=tenant_id)
        print(f'\n导入完成: 课程={course.title}, 章节={len(STRUCTURE)}, 课时={total_hours}')


if __name__ == '__main__':
    main()
