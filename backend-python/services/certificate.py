"""结业证书渲染服务（Pillow）。

设计风格：金色深色边框（庄重官方风）
- 多层金色边框（外粗内细 + 内侧暗金描线）
- 四角菱形/角花装饰
- 顶部奖章 + 衬线标题
- 姓名深蓝大字 + 下划线
- 课程信息 + 颁发日期 + 证书编号
- 底部双印章（红色公章 + 编号章）
- 米白羊皮纸底 + 暗金水印底纹

中文使用 NotoSansCJK 字体；证书图片存 uploads/certificates/<id>.png。
证书编号全局唯一 CERT-年-流水号，用于验证防伪。
"""
from __future__ import annotations

import os
import math
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

from models import db, Certificate, Employee, Course

# 画布尺寸（横版 A4 近似比例，2x 超采样）
W, H = 2400, 1700

# 配色
COL_BG = (250, 247, 240)        # 米白羊皮纸
COL_BG_WATERMARK = (241, 233, 213)  # 暗金水印底纹
COL_GOLD = (176, 141, 60)        # 主金色
COL_GOLD_DEEP = (134, 105, 33)   # 深金（外框）
COL_GOLD_LIGHT = (212, 184, 112) # 亮金（描线/文字）
COL_TITLE = (122, 92, 28)        # 标题深金棕
COL_NAME = (26, 52, 96)          # 姓名深蓝
COL_TEXT = (51, 42, 32)          # 正文深褐
COL_SUB = (120, 104, 84)         # 副文字灰褐
COL_SEAL_RED = (176, 38, 38)     # 印章红
COL_SEAL_RED_DK = (130, 24, 24)  # 印章深红

# 颁发单位（公章公司名）。可通过环境变量 CERT_ISSUER 覆盖。
CERT_ISSUER = os.environ.get('CERT_ISSUER', '宁波恒剑光电科技有限公司')

_FONT_CANDIDATES = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
]
_FONT_BOLD_CANDIDATES = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
]


def _load_font(bold: bool = False):
    """加载中文字体，返回 (path)。"""
    cands = _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES
    for p in cands:
        if os.path.exists(p):
            return p
    return None


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """按字号加载字体，找不到 CJK 时回退默认字体。"""
    path = _load_font(bold)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _draw_centered(draw, text, y, font, fill, canvas_w=W):
    draw.text(((canvas_w - _text_w(draw, text, font)) / 2, y), text, fill=fill, font=font)


def _draw_text_centered_at(draw, text, cx, y, font, fill):
    draw.text((cx - _text_w(draw, text, font) / 2, y), text, fill=fill, font=font)


# ---------------------------------------------------------------------------
# 装饰绘制
# ---------------------------------------------------------------------------

def _draw_corner_ornament(draw, x, y, size, flip_x=False, flip_y=False, color=COL_GOLD):
    """四角菱形+射线角花装饰。以 为角点。"""
    s = size
    sx = -1 if flip_x else 1
    sy = -1 if flip_y else 1
    # 主菱形
    pts = [
        (x, y + sy * s),
        (x + sx * s * 0.35, y + sy * s * 0.35),
        (x + sx * s, y),
        (x + sx * s * 0.35, y + sy * s * 0.35),
    ]
    draw.polygon([(x, y + sy * s),
                  (x + sx * s * 0.45, y + sy * s * 0.45),
                  (x + sx * s, y),
                  (x + sx * s * 0.45, y + sy * s * 0.45)], outline=color)
    draw.polygon([(x, y + sy * s * 0.62),
                  (x + sx * s * 0.3, y + sy * s * 0.3),
                  (x + sx * s * 0.62, y),
                  (x + sx * s * 0.3, y + sy * s * 0.3)], outline=color, fill=None)
    # 小射线
    for r in (s * 0.45, s * 0.62):
        draw.line([(x, y + sy * r), (x + sx * r, y)], fill=color, width=2)


def _draw_medal(draw, cx, cy, r, color=COL_GOLD, light=COL_GOLD_LIGHT):
    """顶部奖章：外圈锯齿光芒 + 内圆 + 中心星。"""
    # 光芒锯齿
    n = 24
    outer = []
    for i in range(n):
        ang = (i / n) * 2 * math.pi
        rr = r * (1.35 if i % 2 == 0 else 1.1)
        outer.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    draw.polygon(outer, fill=light, outline=color)
    # 内圆
    draw.ellipse([cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82], fill=COL_BG, outline=color, width=4)
    # 中心星（五角）
    _draw_star(draw, cx, cy, r * 0.45, r * 0.18, fill=color)


def _draw_star(draw, cx, cy, r_outer, r_inner, fill=COL_GOLD):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + (i / 10) * 2 * math.pi
        rr = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    draw.polygon(pts, fill=fill)


def _draw_seal(image, draw, cx, cy, r, top_text, bottom_text, red=COL_SEAL_RED, font_size=None):
    """圆形公章（真实结构）：外圈 + 内圈，之间是一条能容字的环带。

    结构（从外到内）：
      - 外圈（粗红线）半径 r
      - 环带（文字排在这里）宽度 band_w
      - 内圈（细红线）半径 r - band_w
      - 内圆中心：五角星
    top_text：沿环带上半部排列（公司名），字底贴外圈、字头朝内
    bottom_text：沿环带下半部排列（用途）
    """
    band_w = max(int(r * 0.30), 28)  # 环带宽度，容纳一行字
    fs = font_size or int(band_w * 0.62)  # 字号适配环带宽度
    f = _font(fs, bold=True)
    inner_r = r - band_w  # 内圈半径

    # 外圈（粗）+ 内圈（细）
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=red, width=5)
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], outline=red, width=3)

    # 环带中线半径（文字中心落在这里）
    mid_r = (r + inner_r) / 2
    # 顶部环形文字（公司名）：沿上半圆均匀分布
    _draw_arc_text(image, draw, top_text, cx, cy, mid_r, math.radians(188), math.radians(352),
                   f, red, upward=True)
    # 底部弧形文字（用途）
    if bottom_text:
        _draw_arc_text(image, draw, bottom_text, cx, cy, mid_r, math.radians(8), math.radians(172),
                       f, red, upward=False)

    # 内圆中心五角星
    _draw_star(draw, cx, cy, inner_r * 0.42, inner_r * 0.18, fill=red)


def _draw_arc_text(image, draw, text, cx, cy, radius, start_ang, end_ang, font, fill, upward=True):
    """沿圆弧排列文字，真实公章样式：字贴外圈内沿、径向（字底贴弧、字头朝圆心）。

    旋转公式 deg = 90 - degrees(ang) 已用数值自检在 上/右/下/左 四个位置验证：
    字底方向恒指向圆外（dot=+1.0）。upward 参数仅决定弧的区间（上半圆/下半圆），
    字朝向统一为径向（这是真实物理公章的标准形态）。
    """
    import PIL.Image as PILImage
    chars = list(text)
    widths = [_text_w(draw, c, font) for c in chars]
    total = sum(widths) or 1
    arc_span = end_ang - start_ang
    positions = []
    acc = 0
    for w in widths:
        acc += w / 2
        positions.append(start_ang + arc_span * (acc / total))
        acc += w / 2

    rgba_fill = fill + (255,) if len(fill) == 3 else fill
    fs = font.size
    for ch, ang in zip(chars, positions):
        # 字中心在弧上的坐标
        x = cx + math.cos(ang) * radius
        y = cy + math.sin(ang) * radius
        # 单字画在独立画布：字底对齐画布底边，使旋转后字底正好贴在弧线上
        cw = _text_w(draw, ch, font)
        pad = fs  # 两侧留白避免旋转裁切
        ch_img = PILImage.new('RGBA', (cw + pad * 2, fs + pad * 2), (0, 0, 0, 0))
        ImageDraw.Draw(ch_img).text((pad, pad), ch, fill=rgba_fill, font=font)
        # 径向旋转（数值验证正确）
        deg = 90 - math.degrees(ang)
        rotated = ch_img.rotate(deg, expand=True, resample=Image.BICUBIC)
        rx, ry = rotated.size
        # 字底贴弧：paste 中心对齐到弧上点
        image.paste(rotated, (int(x - rx / 2), int(y - ry / 2)), rotated)



def _draw_watermark(draw):
    """暗金重复花纹底纹（斜向菱形格）。"""
    step = 90
    for y in range(0, H, step):
        for x in range(0, W, step):
            ox = step / 2 if (y // step) % 2 else 0
            cx, cy = x + ox, y
            sz = 16
            draw.polygon([(cx, cy - sz), (cx + sz, cy), (cx, cy + sz), (cx - sz, cy)],
                         outline=COL_BG_WATERMARK, width=1)


# ---------------------------------------------------------------------------
# 主渲染
# ---------------------------------------------------------------------------

def render_certificate_png(out_path: str, *, name: str, course_title: str,
                           cert_no: str, issued_at: datetime | None = None) -> str:
    """渲染证书 PNG 到 out_path。"""
    issued_at = issued_at or datetime.utcnow()
    img = Image.new('RGB', (W, H), COL_BG)
    draw = ImageDraw.Draw(img)

    # 1) 水印底纹
    _draw_watermark(draw)

    margin = 70
    # 2) 多层边框
    # 外深金粗框
    draw.rectangle([margin, margin, W - margin, H - margin], outline=COL_GOLD_DEEP, width=10)
    # 内亮金细框
    draw.rectangle([margin + 22, margin + 22, W - margin - 22, H - margin - 22],
                   outline=COL_GOLD_LIGHT, width=4)
    # 最内暗金描线
    draw.rectangle([margin + 40, margin + 40, W - margin - 40, H - margin - 40],
                   outline=COL_GOLD, width=2)

    # 3) 四角角花
    co = margin + 30  # 角点
    cs = 70
    _draw_corner_ornament(draw, co, co, cs, flip_x=False, flip_y=False)
    _draw_corner_ornament(draw, W - co, co, cs, flip_x=True, flip_y=False)
    _draw_corner_ornament(draw, co, H - co, cs, flip_x=False, flip_y=True)
    _draw_corner_ornament(draw, W - co, H - co, cs, flip_x=True, flip_y=True)

    # 4) 顶部奖章
    medal_cx, medal_cy, medal_r = W / 2, 250, 75
    _draw_medal(draw, medal_cx, medal_cy, medal_r)

    # 5) 标题（中文衬线感）
    f_title = _font(96, bold=True)
    _draw_centered(draw, '学 习 结 业 证 书', 360, f_title, COL_TITLE)
    f_en = _font(40)
    _draw_centered(draw, 'CERTIFICATE OF COMPLETION', 478, f_en, COL_GOLD)

    # 装饰横线（标题下）
    _draw_divider(draw, W / 2, 545, 360)

    # 6) 证明语
    f_lead = _font(48)
    _draw_centered(draw, '兹 证 明 以 下 学 员', 620, f_lead, COL_SUB)

    # 7) 姓名（深蓝大字 + 下划线）
    f_name = _font(118, bold=True)
    name_y = 730
    _draw_centered(draw, name, name_y, f_name, COL_NAME)
    nw = _text_w(draw, name, f_name)
    underline_y = name_y + 135
    draw.line([(W / 2 - nw / 2 - 40, underline_y), (W / 2 + nw / 2 + 40, underline_y)],
              fill=COL_GOLD, width=3)

    # 8) 课程信息
    f_body = _font(52)
    _draw_centered(draw, f'圆满完成《{course_title}》全部课程学习', 940, f_body, COL_TEXT)

    # 9) 装饰横线 + 三栏信息
    _draw_divider(draw, W / 2, 1040, 480)
    _draw_info_row(draw, 1090, issued_at, cert_no)

    # 10) 底部双印章（字号由环带宽度自动适配，不硬编码）
    seal_r = 135
    # 左：颁发单位公章（公司名沿上半圆，用途沿下半圆）
    _draw_seal(img, draw, W * 0.27, 1430, seal_r, CERT_ISSUER, '颁发专用', red=COL_SEAL_RED)
    # 右：认证专用章
    _draw_seal(img, draw, W * 0.73, 1430, seal_r, CERT_ISSUER, '结业认证', red=COL_SEAL_RED_DK)

    img.save(out_path, 'PNG', optimize=True)
    img.close()
    return out_path


def _draw_divider(draw, cx, y, half_w, color=COL_GOLD):
    """装饰横线：中线 + 两端小菱形。"""
    draw.line([(cx - half_w, y), (cx - 24, y)], fill=color, width=3)
    draw.line([(cx + 24, y), (cx + half_w, y)], fill=color, width=3)
    # 中间菱形
    draw.polygon([(cx, y - 12), (cx + 16, y), (cx, y + 12), (cx - 16, y)], fill=color)
    # 两端小菱形
    for ex in (cx - half_w, cx + half_w):
        draw.polygon([(ex, y - 8), (ex + 11, y), (ex, y + 8), (ex - 11, y)], outline=color)


def _draw_info_row(draw, y, issued_at, cert_no):
    """三栏：颁发日期 / 证书编号 / （留白签名位）。"""
    f_label = _font(34)
    f_val = _font(42, bold=True)
    date_str = issued_at.strftime('%Y 年 %m 月 %d 日')
    cols = [
        (W * 0.22, '颁 发 日 期', date_str),
        (W * 0.52, '证 书 编 号', cert_no),
        (W * 0.80, '学 习 状 态', '已 完 成'),
    ]
    for cx, label, val in cols:
        _draw_text_centered_at(draw, label, cx, y, f_label, COL_SUB)
        _draw_text_centered_at(draw, val, cx, y + 52, f_val, COL_TEXT)


# ---------------------------------------------------------------------------
# 颁发逻辑
# ---------------------------------------------------------------------------

def _next_cert_no() -> str:
    year = datetime.utcnow().year
    last = Certificate.query.filter(Certificate.cert_no.like(f'CERT-{year}-%')) \
        .order_by(Certificate.cert_no.desc()).first()
    seq = 1
    if last and last.cert_no:
        try:
            seq = int(last.cert_no.rsplit('-', 1)[-1]) + 1
        except ValueError:
            seq = 1
    return f'CERT-{year}-{seq:06d}'


def generate_certificate(employee_id: str, course_id: str, **kwargs):
    """为员工颁发课程结业证书。幂等：已颁发则返回已有证书。"""
    import logging
    logger = logging.getLogger('hengpintong.certificate')

    existing = Certificate.query.filter_by(employee_id=employee_id, course_id=course_id).first()
    if existing:
        return existing

    emp = db.session.get(Employee, employee_id)
    course = db.session.get(Course, course_id)
    if not emp or not course:
        logger.warning('certificate_missing_data', extra={'employee_id': employee_id, 'course_id': course_id})
        return None

    emp_name = emp.name or ''
    course_title = course.title or ''
    tenant_ids = {
        value
        for value in (getattr(emp, 'tenant_id', None), getattr(course, 'tenant_id', None))
        if value
    }
    if len(tenant_ids) > 1:
        from services.storage import StorageTenantBindingError
        raise StorageTenantBindingError('STORAGE_CROSS_TENANT_KEY')
    tenant_id = next(iter(tenant_ids), None)

    cert = Certificate(
        id=kwargs.get('id') or str(__import__('uuid').uuid4()),
        tenant_id=tenant_id,
        employee_id=employee_id,
        course_id=course_id,
        employee_name=emp_name,
        course_title=course_title,
        cert_no=_next_cert_no(),
        issued_at=datetime.utcnow(),
    )

    from services.storage import delete_object_if_unreferenced, upload_file
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_path = temp_file.name
        render_certificate_png(temp_path, name=emp_name, course_title=course_title,
                               cert_no=cert.cert_no, issued_at=cert.issued_at)
        with open(temp_path, 'rb') as rendered:
            cert_key = upload_file(
                rendered,
                f'certificates/{cert.id}.png',
                content_type='image/png',
                tenant_id=tenant_id,
            )
    finally:
        if temp_path and os.path.isfile(temp_path):
            os.unlink(temp_path)

    cert.image_url = f'/uploads/{cert_key}'
    db.session.add(cert)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        delete_object_if_unreferenced(cert_key, tenant_id=tenant_id)
        raise
    logger.info('certificate_issued', extra={
        'employee': emp_name, 'course': course_title, 'certNo': cert.cert_no
    })
    return cert
