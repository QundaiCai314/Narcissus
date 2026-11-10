"""Validate and normalize private handwritten answer images before storage."""
import io
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from .errors import fail

MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 4


def normalize(data):
    if not data or len(data) > MAX_BYTES:
        fail(413, "answer_image_size", "每张图片不能超过 8 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError()
                if original.width * original.height > 25_000_000:
                    fail(413, "answer_image_pixels", "图片分辨率过大，请缩小至 2500 万像素以内")
                original.load()
                image = ImageOps.exif_transpose(original).convert("RGBA")
                image.thumbnail((3000, 3000))
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                output = io.BytesIO()
                background.save(output, "JPEG", quality=92)
                return output.getvalue(), background.width, background.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        fail(422, "invalid_answer_image", "请选择有效的 JPG、PNG 或 WebP 图片")


def public_images(attempt_id, question_id, images):
    return [{"id": i["id"], "width": i["width"], "height": i["height"],
             "url": f'/api/quiz-attempts/{attempt_id}/answers/{question_id}/images/{i["id"]}'} for i in images]
