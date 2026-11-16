"""Offline contents OCR subprocess; bundled recognition weights require no API."""
import json
import sys
from pathlib import Path


def main():
    from rapidocr_onnxruntime import RapidOCR
    jobs_path, result_path = map(Path, sys.argv[1:3])
    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    results = []
    for job in json.loads(jobs_path.read_text()):
        try:
            from .pdf_outline import box_lines
            from PIL import Image
            boxes,_=engine(job['path'],use_cls=False)
            with Image.open(job['path']) as image:width=image.width
            lines=box_lines(boxes or [],width)
        except Exception:
            lines = []
        results.append(dict(pdf_page=job['pdf_page'], lines=lines))
        temporary=result_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
        temporary.replace(result_path)


if __name__ == '__main__':
    main()
