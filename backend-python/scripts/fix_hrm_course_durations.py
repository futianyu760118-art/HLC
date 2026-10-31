"""修正 HRM 系统功能培训课程课时时长。

导入脚本首次运行时旧版 read_mp4_duration 只读文件头 2MB，而本批成片 moov
位于文件尾部，导致 duration 全部为 0。本脚本用全文件解析器重新计算时长并
更新 course_hours.duration（仅更新目标课程下标题匹配的课时）。
"""
import os
import struct
import sys

sys.path.insert(0, '/app')

from models import db, Course, CourseHour
from app import create_app

TENANT_ID = 'cd416956-373f-4fdc-916e-d5ad3c3d3bf8'
COURSE_TITLE = 'HRM 系统功能培训'
IMPORT_DIR = '/app/uploads/_hrm_course_videos'

STRUCTURE = [
    ('01 数据驾驶舱', [('数据驾驶舱', '01-数据驾驶舱.mp4')]),
    ('02 人才智能', [('人才智能', '02-人才智能.mp4')]),
    ('03 招聘管理', [('招聘管理', '03-招聘管理.mp4')]),
    ('04 组织管理', [('组织管理', '04-组织管理.mp4')]),
    ('05 员工管理', [('员工管理', '05-员工管理.mp4')]),
    ('06 考勤与申请', [('考勤与申请', '06-考勤与申请.mp4')]),
    ('07 审批中心', [('审批中心', '07-审批中心.mp4')]),
    ('08 绩效管理', [('绩效管理', '08-绩效管理.mp4')]),
    ('09 薪酬管理', [('薪酬管理', '09-薪酬管理.mp4')]),
    ('10 学习发展', [('学习发展', '10-学习发展.mp4')]),
    ('11 考试中心', [('考试中心', '11-考试中心.mp4')]),
    ('12 系统管理', [('系统管理', '12-系统管理.mp4')]),
    ('13 员工门户', [('员工门户', '13-员工门户.mp4')]),
    ('14 平台管理', [('平台管理', '14-平台管理.mp4')]),
]


def read_mp4_duration(path: str) -> int:
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
                        off = inner + iheader + 4
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


def main():
    app = create_app()
    with app.app_context():
        course = Course.query.filter_by(tenant_id=TENANT_ID, title=COURSE_TITLE).first()
        if course is None:
            raise SystemExit('课程不存在，已拒绝执行')
        hours = {h.title: h for h in CourseHour.query.filter_by(course_id=course.id).all()}
        updated = 0
        for _ch_name, entries in STRUCTURE:
            for h_title, vfile in entries:
                vpath = os.path.join(IMPORT_DIR, vfile)
                duration = read_mp4_duration(vpath)
                hour = hours.get(h_title)
                if hour is None:
                    print(f'  !! 课时不存在: {h_title}')
                    continue
                hour.duration = duration
                updated += 1
                print(f'  {h_title}: {duration}s ({vfile})')
        db.session.commit()
        print(f'时长更新完成: {updated} 个课时')


if __name__ == '__main__':
    main()
