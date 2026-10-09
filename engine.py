"""
PDF ToolHub - processing engine.

Pure-Python helpers with no Streamlit dependency, so every operation can be
unit-tested or reused from a CLI / API. All functions take and return bytes.
"""
from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from typing import Iterable, Sequence

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4, LETTER, A3, A5, LEGAL
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from xml.sax.saxutils import escape

PAGE_SIZES = {"A3": A3, "A4": A4, "A5": A5, "Letter": LETTER, "Legal": LEGAL}


# --------------------------------------------------------------------------- #
# Unicode font support (Telugu, Hindi, Tamil, Cyrillic, ...)
# --------------------------------------------------------------------------- #
import glob
import os
import unicodedata
from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:  # optional: needed for correct Indic/Thai conjuncts and vowel signs
    import uharfbuzz  # noqa: F401
    SHAPING = True
except Exception:  # pragma: no cover
    SHAPING = False
try:
    from reportlab.pdfbase.ttfonts import shapeStr
except Exception:  # pragma: no cover
    shapeStr = None

STANDARD_FONTS = ["Helvetica", "Times-Roman", "Courier"]
APP_FONT_DIR = Path(__file__).parent / "fonts"
_SCRIPTS = [
    ("Telugu", 0x0C00, 0x0C7F), ("Devanagari", 0x0900, 0x097F), ("Tamil", 0x0B80, 0x0BFF),
    ("Kannada", 0x0C80, 0x0CFF), ("Malayalam", 0x0D00, 0x0D7F), ("Bengali", 0x0980, 0x09FF),
    ("Gujarati", 0x0A80, 0x0AFF), ("Gurmukhi", 0x0A00, 0x0A7F), ("Oriya", 0x0B00, 0x0B7F),
    ("Arabic", 0x0600, 0x06FF), ("Hebrew", 0x0590, 0x05FF), ("Thai", 0x0E00, 0x0E7F),
    ("Cyrillic", 0x0400, 0x04FF), ("Greek", 0x0370, 0x03FF), ("CJK", 0x3040, 0x9FFF),
    ("Hangul", 0xAC00, 0xD7AF),
]
_COMPLEX = {"Telugu", "Devanagari", "Tamil", "Kannada", "Malayalam", "Bengali", "Gujarati",
            "Gurmukhi", "Oriya", "Thai", "Arabic"}
_RTL = {"Arabic", "Hebrew"}
_GENERIC_HINTS = ("notosans-regular", "notosans[", "dejavusans.", "freesans.", "nirmala.", "nirmalaui",
                  "arialuni", "gautami", "mangal", "latha", "tunga", "raavi", "kartika", "shruti", "vrinda")


def needs_unicode(text: str) -> bool:
    """True if the text cannot be drawn with the built-in PDF fonts."""
    try:
        text.encode("cp1252")
        return False
    except UnicodeEncodeError:
        return True


def detect_scripts(text: str) -> list[str]:
    found: list[str] = []
    for ch in set(text):
        cp = ord(ch)
        if cp < 0x250 or ch.isspace():
            continue
        for name, lo, hi in _SCRIPTS:
            if lo <= cp <= hi:
                if name not in found:
                    found.append(name)
                break
    return sorted(found)


@lru_cache(maxsize=1)
def discover_fonts() -> dict[str, str]:
    """Find TrueType fonts: the app's ./fonts folder first, then common system locations."""
    patterns = [str(APP_FONT_DIR / "**" / "*.ttf"), "/usr/share/fonts/**/*.ttf",
                "/usr/local/share/fonts/**/*.ttf", "~/.fonts/**/*.ttf", "~/.local/share/fonts/**/*.ttf",
                "/Library/Fonts/**/*.ttf", "/System/Library/Fonts/Supplemental/*.ttf", "~/Library/Fonts/*.ttf",
                "C:/Windows/Fonts/*.ttf", "~/AppData/Local/Microsoft/Windows/Fonts/*.ttf"]
    out: dict[str, str] = {}
    for pat in patterns:
        for p in glob.glob(os.path.expanduser(pat), recursive=True):
            out.setdefault(Path(p).stem, p)
    return out


def _ranked_fonts(scripts: Sequence[str]) -> list[tuple[str, str]]:
    ranked = []
    for name, path in discover_fonts().items():
        low = name.lower()
        if str(APP_FONT_DIR) in path:
            score = 0
        elif any(sc.lower() in low for sc in scripts):
            score = 1
        elif any(h in low + "." or h in low for h in _GENERIC_HINTS):
            score = 2
        else:
            continue
        if any(k in low for k in ("bold", "italic", "oblique", "light", "mono", "condensed", "serif")) and score > 0:
            score += 3
        ranked.append((score, name, path))
    ranked.sort()
    return [(n, p) for _, n, p in ranked]


def _register(name: str, path: str) -> str:
    reg = "TH_" + name
    if reg not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(reg, path))
    return reg


def _covers(fontname: str, text: str) -> bool:
    cmap = pdfmetrics.getFont(fontname).face.charToGlyph
    for ch in set(text):
        if ch.isspace() or unicodedata.category(ch) in ("Cf", "Cc"):
            continue
        if ord(ch) not in cmap:
            return False
    return True


def unicode_font_choices() -> list[str]:
    """Font names worth showing in a picker (user-supplied + well-known Unicode fonts)."""
    return [n for n, _ in _ranked_fonts([])]


def resolve_font(text: str, requested: str = "Auto") -> tuple[str, list[str]]:
    """Return (reportlab_font_name, warnings). Raises PDFError if the text cannot be drawn correctly."""
    scripts = detect_scripts(text)
    warns: list[str] = []
    if requested in STANDARD_FONTS:
        if needs_unicode(text):
            raise PDFError(f"{requested} can't display {', '.join(scripts) or 'these characters'}. "
                           "Pick 'Auto' or a Unicode font.")
        return requested, warns
    name = None
    if requested != "Auto":
        path = discover_fonts().get(requested)
        if not path:
            raise PDFError(f"Font '{requested}' was not found.")
        name = _register(requested, path)
        if not _covers(name, text):
            raise PDFError(f"'{requested}' is missing characters used in your text"
                           f"{' (' + ', '.join(scripts) + ')' if scripts else ''}.")
    elif not needs_unicode(text):
        return "Helvetica", warns
    else:
        for fname, path in _ranked_fonts(scripts):
            try:
                cand = _register(fname, path)
                if _covers(cand, text):
                    name = cand
                    break
            except Exception:
                continue
        if not name:
            raise PDFError(
                f"No installed font can display {', '.join(scripts) or 'this text'}. Download a free font "
                "(e.g. 'Noto Sans Telugu' / 'Noto Sans Devanagari' from fonts.google.com/noto) and put the "
                ".ttf file in the 'fonts' folder next to app.py, then try again.")
    if set(scripts) & _COMPLEX and not SHAPING:
        warns.append("Complex scripts need the 'uharfbuzz' package for correct letter joining and vowel "
                     "signs. Run: pip install uharfbuzz")
    if set(scripts) & _RTL:
        warns.append("Right-to-left scripts (Arabic, Hebrew) are not laid out right-to-left by this tool.")
    return name, warns


def _shape(text: str, fontname: str, size: float) -> str:
    """Pre-shape text for canvas drawing (paragraphs shape themselves)."""
    if SHAPING and shapeStr and fontname.startswith("TH_"):
        try:
            return shapeStr(text, fontname, size)
        except Exception:
            return text
    return text


class PDFError(Exception):
    """User-facing processing error."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _reader(data: bytes, password: str | None = None) -> PdfReader:
    try:
        r = PdfReader(io.BytesIO(data))
    except Exception as exc:  # corrupt file
        raise PDFError(f"Could not read PDF: {exc}") from exc
    if r.is_encrypted:
        if not password or not r.decrypt(password):
            raise PDFError("This PDF is password-protected. Use the Unlock tool first.")
    return r


def _to_bytes(writer: PdfWriter) -> bytes:
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def page_count(data: bytes, password: str | None = None) -> int:
    return len(_reader(data, password).pages)


def parse_ranges(spec: str, total: int) -> list[int]:
    """
    Parse a page spec into 0-based indices (order preserved, repeats allowed).
    Supports: "1-3,5,8-", "all", "odd", "even", "last", "5-1" (reverse).
    """
    spec = (spec or "").strip().lower()
    if not spec or spec == "all":
        return list(range(total))
    if spec == "odd":
        return list(range(0, total, 2))
    if spec == "even":
        return list(range(1, total, 2))
    out: list[int] = []
    for token in spec.replace(" ", "").split(","):
        if not token:
            continue
        if token == "last":
            out.append(total - 1)
            continue
        try:
            if "-" in token:
                a, b = token.split("-", 1)
                start = int(a) if a else 1
                end = int(b) if b else total
            else:
                start = end = int(token)
        except ValueError as exc:
            raise PDFError(f"Invalid page token: '{token}'") from exc
        if not (1 <= start <= total and 1 <= end <= total):
            raise PDFError(f"Page range '{token}' is outside 1-{total}.")
        step = 1 if end >= start else -1
        out.extend(range(start - 1, end - 1 + step, step))
    if not out:
        raise PDFError("No pages selected.")
    return out


def zip_files(files: Iterable[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files:
            zf.writestr(name, content)
    return buf.getvalue()


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


# --------------------------------------------------------------------------- #
# Analysis & preview
# --------------------------------------------------------------------------- #
@dataclass
class PDFInfo:
    pages: int
    size_bytes: int
    encrypted: bool
    version: str
    title: str
    author: str
    subject: str
    producer: str
    creator: str
    created: str
    modified: str
    page_sizes: list[tuple[float, float]]
    words: int
    images: int
    has_text: bool
    has_forms: bool
    has_outline: bool


def analyze(data: bytes, password: str | None = None) -> PDFInfo:
    r = _reader(data, password)
    md = r.metadata or {}
    sizes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in r.pages]
    words, images = 0, 0
    for p in r.pages:
        try:
            words += len((p.extract_text() or "").split())
        except Exception:
            pass
        try:
            images += len(p.images)
        except Exception:
            pass
    try:
        has_forms = bool(r.get_fields())
    except Exception:
        has_forms = False
    try:
        has_outline = bool(r.outline)
    except Exception:
        has_outline = False
    g = lambda k: str(md.get(k, "") or "")
    return PDFInfo(
        pages=len(r.pages), size_bytes=len(data), encrypted=r.is_encrypted,
        version=(r.pdf_header or "").replace("%PDF-", ""),
        title=g("/Title"), author=g("/Author"), subject=g("/Subject"),
        producer=g("/Producer"), creator=g("/Creator"),
        created=g("/CreationDate"), modified=g("/ModDate"),
        page_sizes=sizes, words=words, images=images, has_text=words > 0,
        has_forms=has_forms, has_outline=has_outline,
    )


def render_pages(data: bytes, pages: Sequence[int] | None = None, dpi: int = 100,
                 password: str | None = None) -> list[Image.Image]:
    """Render pages (0-based) to PIL images using PDFium."""
    try:
        pdf = pdfium.PdfDocument(data, password=password)
    except Exception as exc:
        raise PDFError(f"Could not render PDF: {exc}") from exc
    idx = list(range(len(pdf))) if pages is None else list(pages)
    out = []
    for i in idx:
        out.append(pdf[i].render(scale=dpi / 72).to_pil().convert("RGB"))
    pdf.close()
    return out


def thumbnails(data: bytes, limit: int = 60, width: int = 220) -> list[bytes]:
    imgs = render_pages(data, pages=range(min(limit, page_count(data))), dpi=50)
    res = []
    for im in imgs:
        ratio = width / im.width
        im = im.resize((width, int(im.height * ratio)))
        b = io.BytesIO()
        im.save(b, "PNG")
        res.append(b.getvalue())
    return res


# --------------------------------------------------------------------------- #
# Organize: merge / split / reorder / rotate / crop
# --------------------------------------------------------------------------- #
def merge(files: Sequence[tuple[bytes, str]], add_bookmarks: bool = True,
          names: Sequence[str] | None = None) -> bytes:
    """files: sequence of (pdf_bytes, page_spec). Pages follow the spec."""
    if len(files) < 2:
        raise PDFError("Add at least two PDFs to merge.")
    w = PdfWriter()
    for n, (data, spec) in enumerate(files):
        r = _reader(data)
        idx = parse_ranges(spec, len(r.pages))
        first = len(w.pages)
        for i in idx:
            w.add_page(r.pages[i])
        if add_bookmarks and names:
            w.add_outline_item(names[n], first)
    return _to_bytes(w)


def extract_pages(data: bytes, spec: str, password: str | None = None) -> bytes:
    r = _reader(data, password)
    w = PdfWriter()
    for i in parse_ranges(spec, len(r.pages)):
        w.add_page(r.pages[i])
    return _to_bytes(w)


def split(data: bytes, mode: str, value: str | int, base: str = "split") -> list[tuple[str, bytes]]:
    """mode: 'each' | 'every' | 'ranges'. Returns [(filename, bytes)]."""
    r = _reader(data)
    n = len(r.pages)
    groups: list[list[int]] = []
    if mode == "each":
        groups = [[i] for i in range(n)]
    elif mode == "every":
        k = max(1, int(value))
        groups = [list(range(i, min(i + k, n))) for i in range(0, n, k)]
    elif mode == "ranges":
        for part in str(value).split(";"):
            if part.strip():
                groups.append(parse_ranges(part, n))
        if not groups:
            raise PDFError("Enter at least one range (separate parts with ';').")
    else:
        raise PDFError("Unknown split mode.")
    out = []
    for gi, g in enumerate(groups, 1):
        w = PdfWriter()
        for i in g:
            w.add_page(r.pages[i])
        label = f"p{g[0] + 1}" if len(g) == 1 else f"p{g[0] + 1}-{g[-1] + 1}"
        out.append((f"{base}_{gi:02d}_{label}.pdf", _to_bytes(w)))
    return out


def reorganize(data: bytes, order: Sequence[int], rotations: dict[int, int] | None = None) -> bytes:
    """order: 0-based page indices in final order (omit = delete). rotations: {orig_idx: degrees}."""
    r = _reader(data)
    if not order:
        raise PDFError("The result would have no pages.")
    w = PdfWriter()
    for i in order:
        page = w.add_page(r.pages[i])
        deg = (rotations or {}).get(i, 0)
        if deg:
            page.rotate(deg)
    return _to_bytes(w)


def rotate(data: bytes, angle: int, spec: str = "all") -> bytes:
    r = _reader(data)
    targets = set(parse_ranges(spec, len(r.pages)))
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        pg = w.add_page(p)
        if i in targets:
            pg.rotate(angle)
    return _to_bytes(w)


def crop(data: bytes, top: float, right: float, bottom: float, left: float,
         spec: str = "all") -> bytes:
    """Margins in millimetres to trim from each side."""
    r = _reader(data)
    targets = set(parse_ranges(spec, len(r.pages)))
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        pg = w.add_page(p)
        if i in targets:
            box = pg.mediabox
            l, b = float(box.left) + left * mm, float(box.bottom) + bottom * mm
            rt, t = float(box.right) - right * mm, float(box.top) - top * mm
            if rt <= l or t <= b:
                raise PDFError("Crop margins are larger than the page.")
            rect = RectangleObject((l, b, rt, t))
            pg.mediabox = rect
            pg.cropbox = rect
    return _to_bytes(w)


# --------------------------------------------------------------------------- #
# Content extraction
# --------------------------------------------------------------------------- #
def extract_text(data: bytes, spec: str = "all", layout: bool = False,
                 password: str | None = None) -> str:
    r = _reader(data, password)
    idx = parse_ranges(spec, len(r.pages))
    chunks = []
    with pdfplumber.open(io.BytesIO(data), password=password) as pdf:
        for i in idx:
            page = pdf.pages[i]
            txt = page.extract_text(layout=layout) or ""
            chunks.append(f"--- Page {i + 1} ---\n{txt.strip()}")
    return "\n\n".join(chunks)


def extract_tables(data: bytes, spec: str = "all"):
    """Returns list of (page_number, table_number, DataFrame)."""
    import pandas as pd

    r = _reader(data)
    idx = parse_ranges(spec, len(r.pages))
    found = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i in idx:
            for t_i, table in enumerate(pdf.pages[i].extract_tables(), 1):
                if not table or len(table) < 2:
                    continue
                header = [(h or f"col_{c + 1}").strip() or f"col_{c + 1}" for c, h in enumerate(table[0])]
                seen: dict[str, int] = {}
                for c, h in enumerate(header):  # de-duplicate headers
                    seen[h] = seen.get(h, 0) + 1
                    if seen[h] > 1:
                        header[c] = f"{h}_{seen[h]}"
                found.append((i + 1, t_i, pd.DataFrame(table[1:], columns=header)))
    return found


def tables_to_xlsx(tables) -> bytes:
    import pandas as pd

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for page, n, df in tables:
            df.to_excel(xw, sheet_name=f"p{page}_t{n}"[:31], index=False)
    return buf.getvalue()


def text_to_docx(text: str) -> bytes:
    from docx import Document

    doc = Document()
    for block in text.split("\n"):
        if block.startswith("--- Page"):
            doc.add_heading(block.strip("- "), level=2)
        elif block.strip():
            doc.add_paragraph(block)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pdf_to_images(data: bytes, spec: str = "all", dpi: int = 150, fmt: str = "PNG",
                  quality: int = 85, base: str = "page") -> list[tuple[str, bytes]]:
    n = page_count(data)
    idx = parse_ranges(spec, n)
    out = []
    for i, im in zip(idx, render_pages(data, idx, dpi)):
        b = io.BytesIO()
        if fmt.upper() == "JPEG":
            im.save(b, "JPEG", quality=quality, optimize=True)
        else:
            im.save(b, fmt.upper())
        out.append((f"{base}_{i + 1:03d}.{fmt.lower().replace('jpeg', 'jpg')}", b.getvalue()))
    return out


def extract_embedded_images(data: bytes, spec: str = "all", base: str = "img"):
    r = _reader(data)
    out = []
    for i in parse_ranges(spec, len(r.pages)):
        try:
            for k, im in enumerate(r.pages[i].images, 1):
                ext = (im.name.rsplit(".", 1)[-1] if "." in im.name else "png")
                out.append((f"{base}_p{i + 1}_{k}.{ext}", im.data))
        except Exception:
            continue
    return out


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def images_to_pdf(images: Sequence[bytes], page_size: str = "A4", landscape: bool = False,
                  margin_mm: float = 10, fit: str = "fit") -> bytes:
    """page_size: A4/Letter/... or 'Original'. fit: 'fit' | 'fill' (crop-free stretch avoided)."""
    if not images:
        raise PDFError("Add at least one image.")
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for raw in images:
        im = Image.open(io.BytesIO(raw))
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, "white")
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        if page_size == "Original":
            pw, ph = im.width * 0.75, im.height * 0.75
            m = 0
        else:
            pw, ph = PAGE_SIZES[page_size]
            if landscape:
                pw, ph = ph, pw
            m = margin_mm * mm
        c.setPageSize((pw, ph))
        aw, ah = pw - 2 * m, ph - 2 * m
        scale = min(aw / im.width, ah / im.height)
        w, h = im.width * scale, im.height * scale
        c.drawImage(ImageReader(im), (pw - w) / 2, (ph - h) / 2, w, h)
        c.showPage()
    c.save()
    return buf.getvalue()


def text_to_pdf(text: str, title: str = "", page_size: str = "A4", font: str = "Auto",
                size: int = 11, margin_mm: float = 20, line_spacing: float = 1.35) -> bytes:
    """font: 'Auto' (detects scripts), a standard font, or a discovered Unicode font name."""
    if not text.strip():
        raise PDFError("Enter some text first.")
    if font == "Auto" and not needs_unicode(text + title):
        font = "Helvetica"
    fname, _ = resolve_font(text + "\n" + title, font)
    is_ttf = fname.startswith("TH_")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=PAGE_SIZES[page_size], leftMargin=margin_mm * mm,
                            rightMargin=margin_mm * mm, topMargin=margin_mm * mm,
                            bottomMargin=margin_mm * mm, title=title or "Document")
    styles = getSampleStyleSheet()
    shaping = 1 if (is_ttf and SHAPING) else 0
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=fname, fontSize=size,
                          leading=size * line_spacing, spaceAfter=size * 0.6, shaping=shaping)
    head = ParagraphStyle("head", parent=styles["Title"], fontName=fname if is_ttf else
                          ("Helvetica-Bold" if fname == "Helvetica" else fname), shaping=shaping)
    story = []
    if title:
        story += [Paragraph(escape(title), head), Spacer(1, 10)]
    for para in text.replace("\r", "").split("\n\n"):
        if para.strip():
            story.append(Paragraph(escape(para).replace("\n", "<br/>"), body))
    doc.build(story)
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Stamp: watermark & page numbers
# --------------------------------------------------------------------------- #
def _overlay(width: float, height: float, draw) -> PdfReader:
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=(width, height))
    draw(c)
    c.save()
    b.seek(0)
    return PdfReader(b)


def watermark_text(data: bytes, text: str, size: int = 60, opacity: float = 0.2,
                   angle: int = 45, color: str = "#888888", spec: str = "all",
                   tile: bool = False, font: str = "Helvetica-Bold") -> bytes:
    if not text.strip():
        raise PDFError("Watermark text is empty.")
    r = _reader(data)
    targets = set(parse_ranges(spec, len(r.pages)))
    if needs_unicode(text):
        font, _ = resolve_font(text, "Auto")
    shaped = _shape(text, font, size)
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i in targets:
            pw, ph = float(p.mediabox.width), float(p.mediabox.height)

            def draw(c, pw=pw, ph=ph):
                c.setFillColor(HexColor(color), alpha=opacity)
                c.setFont(font, size)
                if tile:
                    step_x, step_y = size * len(text) * 0.7 + 60, size * 3
                    rows = int(ph / step_y) + 3
                    cols = int(pw / step_x) + 3
                    c.saveState()
                    c.translate(pw / 2, ph / 2)
                    c.rotate(angle)
                    for ry in range(-rows, rows):
                        for cx in range(-cols, cols):
                            c.drawCentredString(cx * step_x, ry * step_y, shaped)
                    c.restoreState()
                else:
                    c.saveState()
                    c.translate(pw / 2, ph / 2)
                    c.rotate(angle)
                    c.drawCentredString(0, -size / 3, shaped)
                    c.restoreState()

            p.merge_page(_overlay(pw, ph, draw).pages[0])
        w.add_page(p)
    return _to_bytes(w)


def add_page_numbers(data: bytes, position: str = "bottom-center", fmt: str = "Page {n} of {total}",
                     start: int = 1, size: int = 10, color: str = "#333333",
                     spec: str = "all", margin_mm: float = 10) -> bytes:
    r = _reader(data)
    total = len(r.pages)
    targets = parse_ranges(spec, total)
    numbering = {pi: start + k for k, pi in enumerate(targets)}
    lfont = resolve_font(fmt, "Auto")[0] if needs_unicode(fmt) else "Helvetica"
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i in numbering:
            pw, ph = float(p.mediabox.width), float(p.mediabox.height)
            label = _shape(fmt.replace("{n}", str(numbering[i])).replace("{total}", str(start + len(targets) - 1)),
                           lfont, size)

            def draw(c, pw=pw, ph=ph, label=label):
                c.setFillColor(HexColor(color))
                c.setFont(lfont, size)
                m = margin_mm * mm
                y = m if position.startswith("bottom") else ph - m - size
                if position.endswith("left"):
                    c.drawString(m, y, label)
                elif position.endswith("right"):
                    c.drawRightString(pw - m, y, label)
                else:
                    c.drawCentredString(pw / 2, y, label)

            p.merge_page(_overlay(pw, ph, draw).pages[0])
        w.add_page(p)
    return _to_bytes(w)


# --------------------------------------------------------------------------- #
# Security
# --------------------------------------------------------------------------- #
def protect(data: bytes, user_pw: str, owner_pw: str | None = None, allow_print: bool = True,
            allow_copy: bool = True, allow_modify: bool = False, aes256: bool = True) -> bytes:
    if not user_pw:
        raise PDFError("Enter a password.")
    from pypdf.constants import UserAccessPermissions as P

    r = _reader(data)
    w = PdfWriter(clone_from=r)
    perms = P(0)
    if allow_print:
        perms |= P.PRINT | P.PRINT_TO_REPRESENTATION
    if allow_copy:
        perms |= P.EXTRACT | P.EXTRACT_TEXT_AND_GRAPHICS
    if allow_modify:
        perms |= P.MODIFY | P.ADD_OR_MODIFY | P.FILL_FORM_FIELDS
    w.encrypt(user_password=user_pw, owner_password=owner_pw or user_pw,
              permissions_flag=perms, algorithm="AES-256" if aes256 else "AES-128")
    return _to_bytes(w)


def unlock(data: bytes, password: str) -> bytes:
    r = PdfReader(io.BytesIO(data))
    if not r.is_encrypted:
        raise PDFError("This PDF is not encrypted.")
    if not r.decrypt(password):
        raise PDFError("Incorrect password.")
    w = PdfWriter(clone_from=r)
    return _to_bytes(w)


# --------------------------------------------------------------------------- #
# Optimize: compress, metadata, OCR
# --------------------------------------------------------------------------- #
def compress(data: bytes, level: str = "balanced", jpeg_quality: int = 60,
             raster_dpi: int = 110) -> bytes:
    """
    level: 'lossless'  - recompress streams, dedupe objects (no visual change)
           'balanced'  - lossless + downsample embedded images to JPEG
           'maximum'   - rasterize every page to JPEG (smallest, loses selectable text)
    """
    if level == "maximum":
        imgs = render_pages(data, dpi=raster_dpi)
        raw = []
        for im in imgs:
            b = io.BytesIO()
            im.save(b, "JPEG", quality=jpeg_quality, optimize=True)
            raw.append(b.getvalue())
        return images_to_pdf(raw, page_size="Original")
    r = _reader(data)
    w = PdfWriter(clone_from=r)
    for p in w.pages:
        p.compress_content_streams()
        if level == "balanced":
            try:
                for img in p.images:
                    try:
                        pil = img.image
                        if pil is None:
                            continue
                        if max(pil.size) > 1800:
                            pil.thumbnail((1800, 1800))
                        if pil.mode not in ("RGB", "L"):
                            pil = pil.convert("RGB")
                        img.replace(pil, quality=jpeg_quality)
                    except Exception:
                        continue
            except Exception:
                pass
    w.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    out = _to_bytes(w)
    return out if len(out) < len(data) else data


def get_metadata(data: bytes) -> dict[str, str]:
    md = _reader(data).metadata or {}
    keys = ["/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/Producer"]
    return {k.strip("/"): str(md.get(k, "") or "") for k in keys}


def set_metadata(data: bytes, meta: dict[str, str], strip_all: bool = False) -> bytes:
    r = _reader(data)
    w = PdfWriter(clone_from=r)
    if strip_all:
        w.metadata = None
        w.add_metadata({"/Producer": "PDF ToolHub"})
    else:
        w.add_metadata({f"/{k}": v for k, v in meta.items() if v is not None})
    return _to_bytes(w)


def ocr_pdf(data: bytes, lang: str = "eng", dpi: int = 200) -> bytes:
    """Make a scanned PDF searchable (needs Tesseract installed)."""
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise PDFError("Tesseract OCR is not installed on this machine.") from exc
    w = PdfWriter()
    for im in render_pages(data, dpi=dpi):
        page_pdf = pytesseract.image_to_pdf_or_hocr(im, extension="pdf", lang=lang)
        w.add_page(PdfReader(io.BytesIO(page_pdf)).pages[0])
    return _to_bytes(w)


def ocr_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False
