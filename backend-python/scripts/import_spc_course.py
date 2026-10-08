"""SPC 供应链中台培训课程导入脚本。

从 uploads/_spc_import 目录读取 19 个培训视频，创建：
  1 个课程分类 + 1 个课程 + 8 个章节 + 19 个课时
每个视频上传到 MinIO（或本地），设置 video_key 和 duration。

用法（容器内）:
    python /app/scripts/import_spc_course.py --tenant-id <tenant-uuid>
"""
import argparse
import os
import sys
import struct
import uuid
from datetime import datetime

# 把后端根目录加入 sys.path（脚本在 scripts/ 子目录，models/app 在根）
sys.path.insert(0, '/app')

from models import db, Course, CourseCategory, CourseChapter, CourseHour, Tenant
from app import create_app
from services import storage

IMPORT_DIR = '/app/uploads/_spc_import'

# 课程结构：(章节名, [(课时标题, 视频文件名), ...])
STRUCTURE = [
    ('整体介绍', [
        ('整体系统介绍', '00-整体系统介绍-培训视频-v1.mp4'),
    ]),
    ('01 供应链驾驶舱', [
        ('供应链驾驶舱', '01-供应链驾驶舱/01-供应链驾驶舱-供应链驾驶舱-培训视频-v1.mp4'),
    ]),
    ('02 订单交付中心', [
        ('订单总控台', '02-订单交付中心/02-订单交付中心-订单总控台-培训视频-v1.mp4'),
        ('跑单管理', '02-订单交付中心/03-订单交付中心-跑单管理-培训视频-v1.mp4'),
        ('订单风险池', '02-订单交付中心/04-订单交付中心-订单风险池-培训视频-v1.mp4'),
    ]),
    ('03 物料齐套中心', [
        ('采购到料计划', '03-物料齐套中心/05-物料齐套中心-采购到料计划-培训视频-v1.mp4'),
        ('问题物料池', '03-物料齐套中心/06-物料齐套中心-问题物料池-培训视频-v1.mp4'),
        ('长交期物料池', '03-物料齐套中心/07-物料齐套中心-长交期物料池-培训视频-v1.mp4'),
        ('齐套分析', '03-物料齐套中心/08-物料齐套中心-齐套分析-培训视频-v1.mp4'),
        ('供应商风险分析', '03-物料齐套中心/09-物料齐套中心-供应商风险分析-培训视频-v1.mp4'),
        ('供应商付款排程', '03-物料齐套中心/10-物料齐套中心-供应商付款排程-培训视频-v1.mp4'),
    ]),
    ('04 生产协同中心', [
        ('计划排产', '04-生产协同中心/11-生产协同中心-计划排产-培训视频-v1.mp4'),
    ]),
    ('05 异常与质量中心', [
        ('异常总池', '05-异常与质量中心/12-异常与质量中心-异常总池-培训视频-v1.mp4'),
        ('变更日志', '05-异常与质量中心/13-异常与质量中心-变更日志-培训视频-v1.mp4'),
        ('品质异常', '05-异常与质量中心/14-异常与质量中心-品质异常-培训视频-v1.mp4'),
        ('产品封样', '05-异常与质量中心/15-异常与质量中心-产品封样-培训视频-v1.mp4'),
        ('闭环跟踪', '05-异常与质量中心/16-异常与质量中心-闭环跟踪-培训视频-v1.mp4'),
    ]),
    ('08 规则配置中心', [
        ('规则配置模块合集', '08-规则配置中心/17-规则配置中心-模块合集-培训视频-v1.mp4'),
    ]),
    ('09 基础数据与集成中心', [
        ('基础数据与集成模块合集', '09-基础数据与集成中心/18-基础数据与集成中心-模块合集-培训视频-v1.mp4'),
    ]),
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='导入 SPC 培训课程到指定企业')
    parser.add_argument(
        '--tenant-id',
        required=True,
        help='目标企业 UUID；不允许无企业归属导入',
    )
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
    """纯 Python 解析 MP4 mvhd atom，返回时长（秒）。失败返回 0。"""
    try:
        with open(path, 'rb') as f:
            data = f.read(2 * 1024 * 1024)  # 只读前 2MB，mvhd 在文件头部
        pos = 0
        while pos + 8 < len(data):
            size = struct.unpack('>I', data[pos:pos + 4])[0]
            atom_type = data[pos + 4:pos + 8]
            if size == 0:
                break
            if atom_type == b'moov':
                # 在 moov 内找 mvhd
                inner = pos + 8
                while inner + 8 < pos + size and inner + 8 < len(data):
                    isz = struct.unpack('>I', data[inner:inner + 4])[0]
                    itype = data[inner + 4:inner + 8]
                    if isz == 0:
                        break
                    if itype == b'mvhd':
                        version = data[inner + 8]
                        off = inner + 8 + (1 if version == 0 else 0) + 3  # version+flags
                        if version == 0:
                            off += 4 + 4  # creation + modification (32bit)
                            timescale = struct.unpack('>I', data[off + 4:off + 8])[0]
                            duration = struct.unpack('>I', data[off + 8:off + 12])[0]
                        else:
                            off += 8 + 8  # creation + modification (64bit)
                            timescale = struct.unpack('>I', data[off:off + 4])[0]
                            duration = struct.unpack('>Q', data[off + 4:off + 12])[0]
                        return int(duration / timescale) if timescale else 0
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

        # 1) 课程分类
        cat = CourseCategory.query.filter_by(
            tenant_id=tenant_id,
            name='供应链中台培训',
        ).first()
        if not cat:
            cat = CourseCategory(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name='供应链中台培训',
                sort=0,
            )
            db.session.add(cat)
            db.session.flush()
            print(f'创建分类: {cat.name} ({cat.id})')

        # 2) 课程
        course = Course.query.filter_by(
            tenant_id=tenant_id,
            title='SPC供应链中台培训',
        ).first()
        if not course:
            course = Course(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                title='SPC供应链中台培训',
                category_id=cat.id,
                is_required=True,
                is_show=True,
                short_desc='供应链中台全模块操作培训（驾驶舱、订单交付、物料齐套、生产协同、异常质量、规则配置、基础数据）',
                content='本课程覆盖供应链中台 9 大功能中心的标准操作流程，共 19 个培训视频。',
                class_hour=19,
                sort=0,
            )
            db.session.add(course)
            db.session.flush()
            print(f'创建课程: {course.title} ({course.id})')
        else:
            print(f'课程已存在: {course.title}，将补充章节/课时')

        # 3) 章节 + 课时 + 视频上传
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
                # 上传到存储
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
