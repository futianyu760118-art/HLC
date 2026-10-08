"""只读核验 IM 系统功能培训课程导入结果（DB 行 + MinIO 对象 + 签名地址）。"""
import sys

sys.path.insert(0, '/app')

from models import db, Course, CourseHour
from app import create_app
from services import storage
from services.portal_media_auth import build_signed_url

COURSE_ID = '5d0c82e4-26b0-4005-80de-54b44228f8f9'
TENANT_ID = 'cd416956-373f-4fdc-916e-d5ad3c3d3bf8'

app = create_app()
with app.app_context():
    course = db.session.get(Course, COURSE_ID)
    if course is None or course.tenant_id != TENANT_ID or course.title != 'IM 系统功能培训':
        raise SystemExit('课程不存在或归属不符，已拒绝')
    hours = (
        CourseHour.query.filter_by(course_id=course.id)
        .order_by(CourseHour.sort.asc())
        .all()
    )
    client = storage._get_client()
    bucket = storage._MINIO_BUCKET
    print(f'course: {course.title} ({course.id}) tenant={course.tenant_id} class_hour={course.class_hour} is_show={course.is_show}')
    print(f'hours: {len(hours)}')
    for hour in hours:
        key = hour.video_key
        stat = client.stat_object(bucket, key)
        print(f'  {hour.title} | duration={hour.duration}s | bytes={stat.size} | key={key}')
    first = hours[0].video_key
    print('SIGNED_URL=' + build_signed_url(first))
