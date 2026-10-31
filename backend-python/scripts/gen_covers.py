"""生成纯渐变课程封面（无文字，避免字体问题）。前端卡片会用 HTML 叠标题。"""
from PIL import Image, ImageDraw
import os, math

UPLOAD = '/app/uploads'
os.makedirs(os.path.join(UPLOAD, 'covers'), exist_ok=True)

# (渐变起色, 渐变止色, 装饰图形)
covers = [
    ((37, 99, 235), (99, 102, 241), 'circles'),    # 蓝（入职）
    ((5, 150, 105), (56, 189, 174), 'diagonal'),   # 绿（Excel）
    ((185, 28, 28), (251, 146, 60), 'waves'),      # 红橙（消防）
    ((109, 40, 217), (217, 70, 239), 'circles'),   # 紫（邮件）
]

W, H = 800, 600
for i, (c1, c2, deco) in enumerate(covers):
    img = Image.new('RGB', (W, H))
    draw = ImageDraw.Draw(img)
    # 对角线渐变
    for y in range(H):
        for x in range(0, W, 4):  # 步进4加速
            t = (x / W * 0.5 + y / H * 0.5)
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            draw.rectangle([x, y, x + 3, y], fill=(r, g, b))

    # 半透明白色装饰（用 RGBA 再合成）
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    if deco == 'circles':
        odraw.ellipse([W - 180, -80, W + 80, 180], outline=(255, 255, 255, 90), width=3)
        odraw.ellipse([W - 240, 60, W - 60, 240], outline=(255, 255, 255, 60), width=2)
        odraw.ellipse([-60, H - 160, 160, H + 60], outline=(255, 255, 255, 70), width=3)
    elif deco == 'diagonal':
        for k in range(-2, 8):
            odraw.line([(k * 120, 0), (k * 120 + 300, H)], fill=(255, 255, 255, 40), width=2)
    elif deco == 'waves':
        for k in range(3):
            odraw.arc([-100 + k * 80, H - 200 + k * 40, 300 + k * 80, H + 100 + k * 40],
                      200, 340, fill=(255, 255, 255, 80), width=3)

    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    path = f'{UPLOAD}/covers/course_{i}.png'
    img.save(path, 'PNG')
    print('OK', path, img.getpixel((400, 300)))

print('DONE')
