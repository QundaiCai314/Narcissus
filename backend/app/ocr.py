"""Bounded local OCR. PDF pages never leave the worker for recognition."""
import csv
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from .config import settings


class OCRFailure(Exception):
    pass


class LocalOCR:
    def __init__(self, data):
        if not shutil.which('pdftoppm') or not shutil.which('tesseract'):
            raise OCRFailure('该资料需要识别图片文字，但后台未安装中文识别工具，请管理员更新服务')
        self.tmp = tempfile.TemporaryDirectory(prefix='narcissus-ocr-')
        self.root = Path(self.tmp.name)
        self.pdf = self.root / 'source.pdf'
        if data is not None:
            self.pdf.write_bytes(data)
        self.started = time.monotonic()
        self.count = 0

    def close(self):
        self.tmp.cleanup()

    def run(self, args):
        left = min(settings().ocr_total_timeout_seconds, 180) - (time.monotonic() - self.started)
        if left <= 0:
            raise OCRFailure('图片文字识别超时，请将资料拆分成较少页数后重试')
        try:
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=max(1, min(settings().ocr_page_timeout_seconds, left)), check=True,
                env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
            return result.stdout.decode('utf-8', errors='replace')
        except subprocess.TimeoutExpired:
            raise OCRFailure('图片文字识别超时，请拆分文件或使用更清晰的原件') from None
        except (subprocess.CalledProcessError, OSError):
            raise OCRFailure('图片文字识别失败，请检查文件或使用更清晰的原件') from None

    def page(self, number):
        self.count += 1
        if self.count > min(settings().ocr_max_pages, 100):
            raise OCRFailure(f'单份资料最多识别 {min(settings().ocr_max_pages, 100)} 页图片文字，请拆分文件')
        target = self.root / 'page'
        self.run(['pdftoppm', '-f', str(number), '-l', str(number), '-singlefile', '-scale-to', '2600', '-gray', '-png', str(self.pdf), str(target)])
        return self.recognize(str(target)+'.png', number)

    def image(self, data):
        from PIL import Image, ImageOps
        path = self.root / 'image.png'
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2600, 2600))
            image.save(path)
        return self.recognize(str(path), 1)

    def recognize(self, path, number):
        raw = self.run(['tesseract', path, 'stdout', '-l', 'chi_sim+eng', '--psm', '3', 'tsv'])
        lines, scores = {}, []
        for row in csv.DictReader(io.StringIO(raw), delimiter='\t', quoting=csv.QUOTE_NONE):
            value = (row.get('text') or '').strip()
            if not value or row.get('level') != '5':
                continue
            confidence = float(row.get('conf', '-1'))
            if confidence < 0:
                continue
            key = tuple(row[k] for k in ('block_num', 'par_num', 'line_num'))
            lines.setdefault(key, []).append(value)
            scores.extend([confidence] * min(30, len(value)))
        text = '\n'.join(' '.join(words) for words in lines.values())
        text = re.sub(r'(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])', '', text)
        confidence = sum(scores) / len(scores) if scores else 0
        if len(re.sub(r'\s', '', text)) < 10 or confidence < 45:
            raise OCRFailure(f'第 {number} 页为扫描页或文字不可辨认，未识别出可靠正文，请提供清晰原件')
        return text, round(confidence, 1)
