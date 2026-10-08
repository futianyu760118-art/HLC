import os
import requests
import base64
from PIL import Image
import io

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# 百度OCR配置
BAIDU_OCR_APP_ID = os.getenv('BAIDU_OCR_APP_ID', '')
BAIDU_OCR_API_KEY = os.getenv('BAIDU_OCR_API_KEY', '')
BAIDU_OCR_SECRET_KEY = os.getenv('BAIDU_OCR_SECRET_KEY', '')

_baidu_access_token = None

def get_baidu_access_token():
    """获取百度OCR的access_token"""
    global _baidu_access_token
    if _baidu_access_token:
        return _baidu_access_token

    if not BAIDU_OCR_API_KEY or not BAIDU_OCR_SECRET_KEY:
        print('[OCR] 百度OCR未配置，跳过OCR识别')
        return None
    
    try:
        url = 'https://aip.baidubce.com/oauth/2.0/token'
        params = {
            'grant_type': 'client_credentials',
            'client_id': BAIDU_OCR_API_KEY,
            'client_secret': BAIDU_OCR_SECRET_KEY
        }
        response = requests.post(url, params=params, timeout=10)
        if response.ok:
            _baidu_access_token = response.json().get('access_token')
            print('[OCR] 百度OCR认证成功')
            return _baidu_access_token
    except Exception as e:
        print(f'[OCR] 百度OCR认证失败: {str(e)}')
    return None

def split_long_image(img, max_height=4000):
    """将长图片分割成多个部分（仅在必要时分割）
    
    百度OCR限制：最长边4096px，大小4MB
    优化策略：尽量不分割，必须分割时使用最大高度
    """
    width, height = img.size
    
    # 如果高度在限制内，不需要分割
    if height <= max_height:
        return [img]
    
    # 计算需要分割的部分数（尽量少）
    parts = []
    overlap = 50  # 小的重叠区域避免文字被切断
    y = 0
    
    while y < height:
        bottom = min(y + max_height, height)
        part = img.crop((0, y, width, bottom))
        parts.append(part)
        y = bottom - overlap if bottom < height else height
    
    print(f'[OCR] 图片需要分割: {height}px > {max_height}px, 分为 {len(parts)} 部分')
    return parts

def image_to_base64(img, max_bytes=4*1024*1024):
    """将图片转换为base64，控制大小"""
    buffer = io.BytesIO()
    quality = 95
    while quality > 30:
        buffer.seek(0)
        buffer.truncate()
        img.save(buffer, format='JPEG', quality=quality)
        if buffer.tell() < max_bytes:
            break
        quality -= 5
    
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')

def ocr_single_image(img_base64, access_token):
    """OCR识别单张图片（带降级机制）
    
    主接口: 通用文字识别（标准含位置版）/general
    备用接口: 通用文字识别（标准版）/general_basic
    """
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'image': img_base64}
    
    # 主接口：标准含位置版
    url = f'https://aip.baidubce.com/rest/2.0/ocr/v1/general?access_token={access_token}'
    response = requests.post(url, headers=headers, data=data, timeout=30)
    
    if response.ok:
        result = response.json()
        
        # 检查是否需要降级（配额不足等错误）
        if 'error_code' in result:
            error_code = result.get('error_code')
            error_msg = result.get('error_msg', '')
            
            # 17: 每日调用量超限, 18: QPS超限, 19: 总量超限
            if error_code in [17, 18, 19]:
                print(f'[OCR] 主接口配额不足({error_code})，切换到标准版...')
                
                # 备用接口：标准版（免费额度更高）
                url_basic = f'https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic?access_token={access_token}'
                response = requests.post(url_basic, headers=headers, data=data, timeout=30)
                
                if response.ok:
                    result = response.json()
                    if 'words_result' in result:
                        return [item['words'] for item in result['words_result']]
                
                print(f'[OCR] 备用接口也失败: {result.get("error_msg", "未知错误")}')
                return []
            else:
                print(f'[OCR] 百度OCR错误({error_code}): {error_msg}')
                return []
        
        if 'words_result' in result:
            return [item['words'] for item in result['words_result']]
    
    return []

def extract_text_from_image(image_path):
    """使用百度OCR从图片中提取文字（支持长图片分段识别）"""
    access_token = get_baidu_access_token()
    if not access_token:
        return ''
    
    try:
        print(f'[OCR] 正在识别图片: {os.path.basename(image_path)}')
        
        # 打开图片
        img = Image.open(image_path)
        
        # 转换为RGB模式
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        width, height = img.size
        print(f'[OCR] 图片尺寸: {width}x{height}')
        
        # 如果宽度太大，按比例缩放（保持清晰度）
        if width > 2000:
            ratio = 2000 / width
            new_width = 2000
            new_height = int(height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)
            print(f'[OCR] 图片宽度缩放: {width} -> {new_width}')
        
        # 分割长图片
        parts = split_long_image(img)
        
        # 逐个识别
        all_text_lines = []
        for i, part in enumerate(parts):
            if len(parts) > 1:
                print(f'[OCR] 识别第 {i+1}/{len(parts)} 部分...')
            
            img_base64 = image_to_base64(part)
            text_lines = ocr_single_image(img_base64, access_token)
            all_text_lines.extend(text_lines)
        
        text = '\n'.join(all_text_lines)
        print(f'[OCR] 识别到 {len(text)} 字符')
        return text
        
    except Exception as e:
        print(f'[OCR] 识别失败: {str(e)}')
        return ''

def extract_text_from_pdf_with_ocr(filepath):
    """从PDF中提取文本，如果文本为空则使用OCR"""
    try:
        if PdfReader is None:
            print('[PDF] pypdf未安装，跳过PDF文本解析')
            return ''
        # 先尝试直接提取文本
        print('[PDF] 正在解析PDF文件...')
        reader = PdfReader(filepath)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
        
        # 如果提取的文本太少，可能是扫描版PDF，尝试OCR
        if len(text.strip()) < 50:
            print('[PDF] 文本内容较少，尝试百度OCR识别...')
            if get_baidu_access_token():
                # 将PDF转换为图片并OCR
                try:
                    import fitz  # PyMuPDF
                    pdf_document = fitz.open(filepath)
                    ocr_text = ''
                    
                    for page_num in range(len(pdf_document)):
                        page = pdf_document[page_num]
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2倍放大提高识别率
                        img_data = pix.tobytes("png")
                        
                        # 保存临时图片
                        temp_img = filepath + f'_page_{page_num}.png'
                        with open(temp_img, 'wb') as f:
                            f.write(img_data)
                        
                        # OCR识别
                        page_text = extract_text_from_image(temp_img)
                        ocr_text += f'\n--- 第{page_num + 1}页 ---\n{page_text}\n'
                        
                        # 删除临时文件
                        try:
                            os.remove(temp_img)
                        except Exception:
                            pass
                    
                    pdf_document.close()
                    
                    if ocr_text.strip():
                        text = ocr_text
                        print(f'[PDF+OCR] 识别到 {len(text)} 字符')
                    
                except ImportError:
                    print('[PDF+OCR] PyMuPDF未安装，无法转换PDF为图片')
                    print('[PDF+OCR] 安装命令: pip install PyMuPDF')
                except Exception as e:
                    print(f'[PDF+OCR] OCR处理失败: {str(e)}')
        
        print(f'[PDF] 最终提取了 {len(text)} 字符')
        return text
        
    except Exception as e:
        print(f'[PDF] 解析错误: {str(e)}')
        return ''

def extract_text_from_file(filepath):
    """从文件中提取文本内容（支持PDF、图片、文本文件）"""
    ext = os.path.splitext(filepath)[1].lower()
    
    try:
        if ext == '.pdf':
            return extract_text_from_pdf_with_ocr(filepath)
        
        elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp']:
            print(f'[图片] 正在识别图片文件...')
            text = extract_text_from_image(filepath)
            if not text:
                return f'图片文件: {os.path.basename(filepath)} (未识别到文字)'
            return text
        
        elif ext == '.txt':
            print('[TXT] 读取文本文件...')
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
            return text
        
        else:
            # 尝试作为文本读取
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    text = f.read()
                return text
            except Exception:
                return f'文件名: {os.path.basename(filepath)}'
    
    except Exception as e:
        print(f'[文件解析] 错误: {str(e)}')
        return f'文件名: {os.path.basename(filepath)}'
