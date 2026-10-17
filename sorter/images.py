"""Turn PDFs and photos into image bytes a vision model can read."""
import io
from pathlib import Path

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
MAX_SIDE = 1600
MAX_PDF_PAGES = 2


def _shrink(data):
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    except Exception:
        return data  # let the model try the raw bytes


def load_images(path):
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        import fitz  # pymupdf
        out = []
        with fitz.open(path) as doc:
            for page in list(doc)[:MAX_PDF_PAGES]:
                out.append(_shrink(page.get_pixmap(dpi=150).tobytes("png")))
        if not out:
            raise ValueError("empty PDF")
        return out
    return [_shrink(path.read_bytes())]
