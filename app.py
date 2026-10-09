"""
PDF ToolHub - a premium all-in-one PDF workspace built with Streamlit.

Run:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime

import pandas as pd
import streamlit as st

import engine as E
from engine import PDFError

st.set_page_config(page_title="PDF ToolHub", page_icon="📑", layout="wide",
                   initial_sidebar_state="expanded")

PDF = "application/pdf"
ZIP = "application/zip"
MAX_MB = 100

# --------------------------------------------------------------------------- #
# Styling
# --------------------------------------------------------------------------- #
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', system-ui, sans-serif; }
.block-container { padding-top: 1.6rem; max-width: 1180px; }
#MainMenu, footer { visibility: hidden; }

.hero {
  background: linear-gradient(120deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%);
  border-radius: 22px; padding: 2.2rem 2.4rem; color: #fff; margin-bottom: 1.4rem;
  box-shadow: 0 18px 40px -18px rgba(79,70,229,.55);
}
.hero h1 { margin: 0; font-size: 2.3rem; font-weight: 800; letter-spacing: -.02em; color:#fff; }
.hero p  { margin: .5rem 0 0; font-size: 1.05rem; opacity: .92; max-width: 680px; }
.badges span {
  display:inline-block; margin: .9rem .45rem 0 0; padding: .25rem .75rem; font-size: .78rem;
  background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.3);
  border-radius: 999px; backdrop-filter: blur(6px);
}
.page-title { display:flex; align-items:center; gap:.8rem; margin-bottom:.2rem; }
.page-title .ico { font-size:1.9rem; background:linear-gradient(135deg,#4f46e5,#db2777);
  border-radius:14px; width:52px; height:52px; display:flex; align-items:center; justify-content:center; }
.page-title h2 { margin:0; font-weight:800; letter-spacing:-.01em; }
.page-sub { opacity:.7; margin-bottom:1.1rem; }

.tool-card {
  border: 1px solid rgba(128,128,128,.25); border-radius: 16px; padding: 1rem 1.1rem .4rem;
  min-height: 112px; transition: all .18s ease; background: rgba(128,128,128,.045);
}
.tool-card:hover { transform: translateY(-3px); border-color:#7c3aed; box-shadow:0 12px 26px -14px rgba(124,58,237,.6); }
.tool-card .t { font-weight:700; font-size:1.02rem; }
.tool-card .d { font-size:.84rem; opacity:.72; margin:.25rem 0 .55rem; }
.cat { font-size:.74rem; letter-spacing:.14em; text-transform:uppercase; opacity:.55; font-weight:700; margin:1.4rem 0 .6rem; }

.chip { display:inline-block; padding:.18rem .65rem; margin-right:.4rem; border-radius:999px; font-size:.8rem;
  border:1px solid rgba(128,128,128,.3); background: rgba(124,58,237,.1); }
[data-testid="stMetric"] { border:1px solid rgba(128,128,128,.22); border-radius:14px; padding:.7rem 1rem;
  background: rgba(128,128,128,.04); }
.stButton > button, .stDownloadButton > button { border-radius: 12px; font-weight: 600; padding: .55rem 1.2rem; }
.stDownloadButton > button[kind="primary"], .stButton > button[kind="primary"] {
  background: linear-gradient(120deg,#4f46e5,#7c3aed); border: 0; color:#fff; }
[data-testid="stFileUploader"] section { border-radius: 14px; border: 2px dashed rgba(124,58,237,.45); }
[data-testid="stSidebar"] { border-right: 1px solid rgba(128,128,128,.2); }
.brand { font-weight:800; font-size:1.25rem; letter-spacing:-.01em; }
.brand small { display:block; font-weight:500; font-size:.75rem; opacity:.6; }
.hist { font-size:.8rem; opacity:.8; padding:.25rem 0; border-bottom:1px dashed rgba(128,128,128,.25); }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
# Shared UI helpers
# --------------------------------------------------------------------------- #
st.session_state.setdefault("history", [])
st.session_state.setdefault("stats", {"ops": 0, "bytes_saved": 0})


def header(icon: str, title: str, sub: str):
    st.markdown(f'<div class="page-title"><div class="ico">{icon}</div><h2>{title}</h2></div>'
                f'<div class="page-sub">{sub}</div>', unsafe_allow_html=True)


@st.cache_data(show_spinner=False, max_entries=8)
def _thumbs(data: bytes, limit: int):
    return E.thumbnails(data, limit=limit)


@st.cache_data(show_spinner=False, max_entries=8)
def _info(data: bytes):
    return E.analyze(data)


def pick_pdf(key: str, label: str = "Drop a PDF here", multiple: bool = False,
             allow_encrypted: bool = False):
    f = st.file_uploader(label, type=["pdf"], key=key, accept_multiple_files=multiple,
                         help=f"Files are processed in memory and never stored. Max {MAX_MB} MB each.")
    items = f if multiple else ([f] if f else [])
    out = []
    for x in items:
        data = x.getvalue()
        if len(data) > MAX_MB * 1024 * 1024:
            st.error(f"{x.name} exceeds {MAX_MB} MB.")
            continue
        out.append((x.name, data))
    if multiple:
        return out
    if not out:
        return None
    name, data = out[0]
    try:
        n = E.page_count(data)
        st.markdown(f'<span class="chip">📄 {name}</span><span class="chip">{n} pages</span>'
                    f'<span class="chip">{E.human_size(len(data))}</span>', unsafe_allow_html=True)
    except PDFError as ex:
        if not allow_encrypted:
            st.error(str(ex))
            return None
        st.markdown(f'<span class="chip">🔒 {name}</span><span class="chip">{E.human_size(len(data))}</span>',
                    unsafe_allow_html=True)
    return name, data


def preview(data: bytes, n: int = 3, dpi: int = 60):
    with st.expander("👁️ Preview", expanded=False):
        try:
            total = E.page_count(data)
            imgs = E.render_pages(data, range(min(n, total)), dpi=dpi + 20)
            cols = st.columns(len(imgs))
            for c, im in zip(cols, imgs):
                c.image(im, use_container_width=True)
            if total > n:
                st.caption(f"Showing first {n} of {total} pages.")
        except Exception:
            st.caption("Preview unavailable.")


def stem(name: str) -> str:
    return name.rsplit(".", 1)[0]


def log(tool: str, filename: str, saved: int = 0):
    st.session_state.history.insert(0, {"t": datetime.now().strftime("%H:%M"), "tool": tool, "file": filename})
    st.session_state.history = st.session_state.history[:8]
    st.session_state.stats["ops"] += 1
    st.session_state.stats["bytes_saved"] += max(0, saved)


def deliver(data: bytes, filename: str, tool: str, mime: str = PDF, original: int | None = None,
            show_preview: bool = True):
    saved = (original - len(data)) if original else 0
    log(tool, filename, saved)
    st.success(f"✅ Done — **{filename}** is ready.")
    cols = st.columns(3 if original else 2)
    cols[0].metric("Output size", E.human_size(len(data)))
    if mime == PDF:
        try:
            cols[1].metric("Pages", E.page_count(data))
        except Exception:
            pass
    if original:
        pct = (1 - len(data) / original) * 100
        cols[-1].metric("Size change", f"{-pct:+.0f}%", delta=f"{E.human_size(abs(saved))} "
                        f"{'saved' if saved >= 0 else 'larger'}", delta_color="normal" if saved >= 0 else "inverse")
    st.download_button("⬇️ Download", data, filename, mime, type="primary",
                       key=f"dl_{hashlib.md5(filename.encode() + data[:64]).hexdigest()}")
    if mime == PDF and show_preview:
        preview(data)


def deliver_many(files: list[tuple[str, bytes]], zip_name: str, tool: str):
    zipped = E.zip_files(files)
    log(tool, zip_name)
    st.success(f"✅ Created **{len(files)}** file(s).")
    st.download_button("⬇️ Download all (ZIP)", zipped, zip_name, ZIP, type="primary",
                       key=f"dlz_{hashlib.md5(zip_name.encode() + zipped[:64]).hexdigest()}")
    with st.expander(f"Individual files ({len(files)})"):
        for i, (n, b) in enumerate(files[:60]):
            c1, c2 = st.columns([4, 1])
            c1.write(f"{n} · {E.human_size(len(b))}")
            c2.download_button("Get", b, n, key=f"ind_{zip_name}_{i}")


def run(label: str, fn, *args, **kwargs):
    """Execute an engine call with spinner + friendly error handling. Returns result or None."""
    try:
        with st.spinner(label):
            return fn(*args, **kwargs)
    except PDFError as ex:
        st.error(f"⚠️ {ex}")
    except Exception as ex:  # noqa: BLE001
        st.error(f"Unexpected error: {ex}")
    return None


def page_spec_input(key: str, label="Pages", default="all", help_text=None):
    return st.text_input(label, default, key=key,
                         help=help_text or "Examples: all · 1-3,5 · 4- (to end) · odd · even · 5-1 (reverse)")


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def tool_merge():
    header("🧩", "Merge PDFs", "Combine documents, pick page ranges and set the order.")
    files = pick_pdf("merge", "Drop two or more PDFs", multiple=True)
    if len(files) < 2:
        st.info("Upload at least two PDFs to begin.")
        return
    rows = []
    for i, (n, d) in enumerate(files, 1):
        try:
            rows.append({"Order": i, "File": n, "Pages": E.page_count(d), "Page range": "all"})
        except PDFError as ex:
            st.error(f"{n}: {ex}")
            return
    st.caption("Edit **Order** to rearrange and **Page range** to include only some pages (e.g. `1-3,7`).")
    df = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True, key="merge_tbl",
                        disabled=["File", "Pages"],
                        column_config={"Order": st.column_config.NumberColumn(min_value=1, step=1, width="small")})
    bookmarks = st.checkbox("Add a bookmark for each source file", True)
    if st.button("Merge PDFs", type="primary"):
        df = df.sort_values("Order", kind="stable")
        seq = [(files[i][1], str(row["Page range"])) for i, row in df.iterrows()]
        res = run("Merging…", E.merge, seq, bookmarks, [stem(files[i][0]) for i in df.index])
        if res:
            deliver(res, "merged.pdf", "Merge")


def tool_split():
    header("✂️", "Split PDF", "Break a document apart by range, size or page.")
    f = pick_pdf("split")
    if not f:
        return
    name, data = f
    mode = st.radio("Split mode", ["Custom ranges", "Every N pages", "Every page"], horizontal=True)
    value, m = "", "each"
    if mode == "Custom ranges":
        m = "ranges"
        value = st.text_input("Ranges (separate output files with `;`)", "1-3;4-6",
                              help="`1-3;4-6;8` creates three files. Within one file you can use `1-3,7`.")
    elif mode == "Every N pages":
        m = "every"
        value = st.number_input("Pages per file", 1, 500, 5)
    if st.button("Split", type="primary"):
        res = run("Splitting…", E.split, data, m, value, stem(name))
        if res:
            deliver_many(res, f"{stem(name)}_split.zip", "Split")


def tool_organize():
    header("🗂️", "Organize Pages", "Reorder, rotate or delete pages visually.")
    f = pick_pdf("org")
    if not f:
        return
    name, data = f
    n = E.page_count(data)
    if n <= 60:
        with st.expander("🖼️ Page thumbnails", expanded=True):
            th = _thumbs(data, 60)
            cols = st.columns(6)
            for i, t in enumerate(th):
                cols[i % 6].image(t, caption=f"Page {i + 1}", use_container_width=True)
    else:
        st.caption("Thumbnails are hidden for documents over 60 pages.")
    df = pd.DataFrame({"Page": range(1, n + 1), "Keep": True, "Rotate": 0, "Position": range(1, n + 1)})
    st.caption("Uncheck **Keep** to delete, set **Rotate** (0/90/180/270) and change **Position** to reorder.")
    ed = st.data_editor(df, hide_index=True, use_container_width=True, disabled=["Page"], key="org_tbl",
                        column_config={"Rotate": st.column_config.SelectboxColumn(options=[0, 90, 180, 270]),
                                       "Position": st.column_config.NumberColumn(min_value=1, step=1)})
    if st.button("Apply changes", type="primary"):
        kept = ed[ed["Keep"]].sort_values("Position", kind="stable")
        order = [int(p) - 1 for p in kept["Page"]]
        rots = {int(r.Page) - 1: int(r.Rotate) for r in kept.itertuples() if r.Rotate}
        res = run("Rebuilding…", E.reorganize, data, order, rots)
        if res:
            deliver(res, f"{stem(name)}_organized.pdf", "Organize")


def tool_rotate_crop():
    header("🔄", "Rotate & Crop", "Fix orientation or trim margins on selected pages.")
    f = pick_pdf("rc")
    if not f:
        return
    name, data = f
    t1, t2 = st.tabs(["Rotate", "Crop margins"])
    with t1:
        angle = st.select_slider("Rotation (clockwise)", [90, 180, 270], 90, format_func=lambda a: f"{a}°")
        spec = page_spec_input("rot_spec")
        if st.button("Rotate", type="primary"):
            res = run("Rotating…", E.rotate, data, angle, spec)
            if res:
                deliver(res, f"{stem(name)}_rotated.pdf", "Rotate")
    with t2:
        c = st.columns(4)
        top, right, bottom, left = (c[0].number_input("Top mm", 0.0, 200.0, 10.0),
                                    c[1].number_input("Right mm", 0.0, 200.0, 10.0),
                                    c[2].number_input("Bottom mm", 0.0, 200.0, 10.0),
                                    c[3].number_input("Left mm", 0.0, 200.0, 10.0))
        spec = page_spec_input("crop_spec")
        if st.button("Crop", type="primary"):
            res = run("Cropping…", E.crop, data, top, right, bottom, left, spec)
            if res:
                deliver(res, f"{stem(name)}_cropped.pdf", "Crop")


def tool_extract_text():
    header("📝", "Extract Text", "Pull text from a PDF as TXT or Word.")
    f = pick_pdf("txt")
    if not f:
        return
    name, data = f
    c1, c2 = st.columns([2, 1])
    spec = page_spec_input("txt_spec")
    layout = c2.checkbox("Preserve layout", False)
    if st.button("Extract", type="primary"):
        text = run("Reading text…", E.extract_text, data, spec, layout)
        if text is not None:
            if len(text.replace("-", "").split()) < 5:
                st.warning("Very little text found — this may be a scan. Try the **OCR** tool.")
            st.session_state["txt_out"] = (text, name)
    if "txt_out" in st.session_state and st.session_state["txt_out"][1] == name:
        text = st.session_state["txt_out"][0]
        m = st.columns(3)
        m[0].metric("Words", f"{len(text.split()):,}")
        m[1].metric("Characters", f"{len(text):,}")
        st.text_area("Result", text, height=300)
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ TXT", text.encode(), f"{stem(name)}.txt", "text/plain", type="primary")
        d2.download_button("⬇️ Word (.docx)", E.text_to_docx(text), f"{stem(name)}.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def tool_extract_tables():
    header("📊", "Extract Tables", "Detect tables and export them to Excel or CSV.")
    f = pick_pdf("tbl")
    if not f:
        return
    name, data = f
    spec = page_spec_input("tbl_spec")
    if st.button("Find tables", type="primary"):
        res = run("Detecting tables…", E.extract_tables, data, spec)
        st.session_state["tbl_out"] = (res, name) if res is not None else None
    out = st.session_state.get("tbl_out")
    if out and out[1] == name:
        tables = out[0]
        if not tables:
            st.warning("No tables detected. Tables must have visible rows/columns; scans need OCR first.")
            return
        st.success(f"Found **{len(tables)}** table(s).")
        st.download_button("⬇️ All tables (.xlsx)", E.tables_to_xlsx(tables), f"{stem(name)}_tables.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        for page, k, df in tables:
            with st.expander(f"Page {page} · Table {k} · {df.shape[0]}×{df.shape[1]}"):
                st.dataframe(df, use_container_width=True)
                st.download_button("CSV", df.to_csv(index=False).encode(), f"{stem(name)}_p{page}_t{k}.csv",
                                   "text/csv", key=f"csv_{page}_{k}")


def tool_to_images():
    header("🖼️", "PDF → Images", "Render pages as high-quality PNG or JPEG.")
    f = pick_pdf("p2i")
    if not f:
        return
    name, data = f
    c = st.columns(3)
    fmt = c[0].selectbox("Format", ["PNG", "JPEG"])
    dpi = c[1].select_slider("Resolution (DPI)", [72, 100, 150, 200, 300], 150)
    q = c[2].slider("JPEG quality", 40, 100, 85, disabled=fmt != "JPEG")
    spec = page_spec_input("p2i_spec")
    if st.button("Convert", type="primary"):
        res = run("Rendering pages…", E.pdf_to_images, data, spec, dpi, fmt, q, stem(name))
        if res:
            if len(res) == 1:
                deliver(res[0][1], res[0][0], "PDF→Image", mime=f"image/{fmt.lower()}", show_preview=False)
                st.image(res[0][1], use_container_width=True)
            else:
                deliver_many(res, f"{stem(name)}_images.zip", "PDF→Images")
                st.image([b for _, b in res[:4]], width=200)


def tool_images_to_pdf():
    header("🧷", "Images → PDF", "Turn photos and scans into one tidy PDF.")
    ups = st.file_uploader("Drop images", type=["png", "jpg", "jpeg", "webp", "bmp", "tiff"],
                           accept_multiple_files=True, key="i2p")
    if not ups:
        return
    c = st.columns(4)
    size = c[0].selectbox("Page size", ["A4", "Letter", "A3", "A5", "Legal", "Original"])
    land = c[1].checkbox("Landscape", False, disabled=size == "Original")
    margin = c[2].slider("Margin (mm)", 0, 40, 10, disabled=size == "Original")
    c[3].caption(f"{len(ups)} image(s)")
    order = st.multiselect("Order (remove or re-add to reorder)", [u.name for u in ups],
                           default=[u.name for u in ups])
    st.image([u.getvalue() for u in ups if u.name in order][:8], width=110)
    if st.button("Create PDF", type="primary"):
        by = {u.name: u.getvalue() for u in ups}
        res = run("Building PDF…", E.images_to_pdf, [by[n] for n in order], size, land, margin)
        if res:
            deliver(res, "images.pdf", "Images→PDF")


def tool_text_to_pdf():
    header("✍️", "Text → PDF", "Write or paste text and publish a clean PDF — English, Telugu, Hindi and more.")
    c = st.columns(4)
    title = c[0].text_input("Title (optional)")
    size = c[1].selectbox("Page size", ["A4", "Letter", "A5", "Legal"])
    fonts = ["Auto (recommended)"] + E.STANDARD_FONTS + E.unicode_font_choices()
    font = c[2].selectbox("Font", fonts, help="Auto picks a font that covers every script in your text. "
                          "Add your own .ttf files to the 'fonts' folder.")
    fs = c[3].slider("Font size", 8, 20, 11)
    text = st.text_area("Content", height=280, placeholder="Separate paragraphs with a blank line…")
    font_arg = "Auto" if font.startswith("Auto") else font
    if text.strip():
        scripts = E.detect_scripts(text + title)
        if scripts:
            st.caption("Detected: " + ", ".join(scripts))
        try:
            _, warns = E.resolve_font(text + "\n" + title, font_arg if E.needs_unicode(text + title) else "Auto")
            for w in warns:
                st.warning(w)
        except PDFError as ex:
            st.error(f"⚠️ {ex}")
    if st.button("Create PDF", type="primary"):
        res = run("Typesetting…", E.text_to_pdf, text, title, size, font_arg, fs)
        if res:
            deliver(res, f"{(title or 'document').replace(' ', '_')}.pdf", "Text→PDF")


def tool_watermark():
    header("💧", "Watermark", "Stamp text across your pages — diagonal or tiled.")
    f = pick_pdf("wm")
    if not f:
        return
    name, data = f
    c = st.columns(3)
    text = c[0].text_input("Text", "CONFIDENTIAL", help="Non-Latin text (Telugu, Hindi, …) is supported via the fonts folder.")
    size = c[1].slider("Font size", 20, 160, 64)
    opacity = c[2].slider("Opacity", 0.05, 1.0, 0.2)
    c = st.columns(4)
    angle = c[0].slider("Angle", -90, 90, 45)
    color = c[1].color_picker("Colour", "#7c3aed")
    tile = c[2].checkbox("Tile across page", False)
    spec = c[3].text_input("Pages", "all")
    if st.button("Apply watermark", type="primary"):
        res = run("Stamping…", E.watermark_text, data, text, size, opacity, angle, color, spec, tile)
        if res:
            deliver(res, f"{stem(name)}_watermarked.pdf", "Watermark")


def tool_page_numbers():
    header("🔢", "Page Numbers", "Add numbering with custom format and position.")
    f = pick_pdf("pn")
    if not f:
        return
    name, data = f
    c = st.columns(3)
    pos = c[0].selectbox("Position", ["bottom-center", "bottom-right", "bottom-left",
                                      "top-center", "top-right", "top-left"])
    fmt = c[1].selectbox("Format", ["{n}", "Page {n}", "Page {n} of {total}", "- {n} -"], index=2)
    start = c[2].number_input("Start at", 1, 9999, 1)
    c = st.columns(3)
    size = c[0].slider("Font size", 7, 20, 10)
    color = c[1].color_picker("Colour", "#333333")
    spec = c[2].text_input("Pages", "all")
    if st.button("Add numbers", type="primary"):
        res = run("Numbering…", E.add_page_numbers, data, pos, fmt, int(start), size, color, spec)
        if res:
            deliver(res, f"{stem(name)}_numbered.pdf", "Page numbers")


def tool_protect():
    header("🔐", "Protect & Unlock", "Encrypt with AES or remove a known password.")
    t1, t2 = st.tabs(["Protect", "Unlock"])
    with t1:
        f = pick_pdf("prot")
        if f:
            name, data = f
            c = st.columns(2)
            pw = c[0].text_input("Open password", type="password")
            pw2 = c[1].text_input("Confirm password", type="password")
            with st.expander("Permissions & strength"):
                a, b, m = st.columns(3)
                pr = a.checkbox("Allow printing", True)
                cp = b.checkbox("Allow copying text", True)
                md = m.checkbox("Allow editing", False)
                aes = st.radio("Encryption", ["AES-256", "AES-128"], horizontal=True) == "AES-256"
            if st.button("Encrypt", type="primary"):
                if pw != pw2:
                    st.error("Passwords don't match.")
                else:
                    res = run("Encrypting…", E.protect, data, pw, None, pr, cp, md, aes)
                    if res:
                        deliver(res, f"{stem(name)}_protected.pdf", "Protect", show_preview=False)
                        st.warning("Keep this password safe — it cannot be recovered.")
    with t2:
        f = pick_pdf("unl", allow_encrypted=True)
        if f:
            name, data = f
            pw = st.text_input("Current password", type="password", key="unl_pw")
            if st.button("Remove password", type="primary"):
                res = run("Decrypting…", E.unlock, data, pw)
                if res:
                    deliver(res, f"{stem(name)}_unlocked.pdf", "Unlock")


def tool_compress():
    header("🗜️", "Compress PDF", "Shrink file size while keeping what matters.")
    f = pick_pdf("cmp")
    if not f:
        return
    name, data = f
    lvl = st.radio("Level", ["Lossless", "Balanced", "Maximum"], horizontal=True, index=1,
                   captions=["Recompress streams only", "Downsample embedded images",
                             "Rasterize pages (text no longer selectable)"])
    q, dpi = 60, 110
    if lvl != "Lossless":
        c = st.columns(2)
        q = c[0].slider("JPEG quality", 20, 95, 60)
        dpi = c[1].slider("Raster DPI (Maximum only)", 72, 200, 110, disabled=lvl != "Maximum")
    if st.button("Compress", type="primary"):
        res = run("Optimizing…", E.compress, data, lvl.lower(), q, dpi)
        if res:
            if len(res) >= len(data):
                st.info("This file is already well optimized — no further savings possible.")
            deliver(res, f"{stem(name)}_compressed.pdf", "Compress", original=len(data))


def tool_metadata():
    header("🏷️", "Metadata Editor", "Edit document properties or scrub them for privacy.")
    f = pick_pdf("meta")
    if not f:
        return
    name, data = f
    md = E.get_metadata(data)
    c = st.columns(2)
    vals = {}
    for i, k in enumerate(md):
        vals[k] = c[i % 2].text_input(k, md[k], key=f"md_{k}_{name}")
    strip = st.checkbox("🧹 Remove ALL metadata instead (privacy mode)")
    if st.button("Save metadata", type="primary"):
        res = run("Writing…", E.set_metadata, data, vals, strip)
        if res:
            deliver(res, f"{stem(name)}_meta.pdf", "Metadata", show_preview=False)


def tool_ocr():
    header("🔍", "OCR — Make Searchable", "Turn scanned PDFs into selectable, searchable documents.")
    if not E.ocr_available():
        st.error("Tesseract OCR isn't installed. Install it (e.g. `apt install tesseract-ocr` / "
                 "`brew install tesseract`) and restart the app.")
        return
    f = pick_pdf("ocr")
    if not f:
        return
    name, data = f
    c = st.columns(2)
    lang = c[0].text_input("Language code(s)", "eng", help="e.g. eng, tel, hin, eng+hin (needs language packs)")
    dpi = c[1].select_slider("Scan DPI", [150, 200, 300], 200)
    n = E.page_count(data)
    if n > 30:
        st.warning(f"{n} pages may take a while.")
    if st.button("Run OCR", type="primary"):
        res = run(f"Recognizing text on {n} page(s)…", E.ocr_pdf, data, lang, dpi)
        if res:
            deliver(res, f"{stem(name)}_ocr.pdf", "OCR")


def tool_extract_images():
    header("📸", "Extract Embedded Images", "Save the original pictures inside a PDF.")
    f = pick_pdf("eimg")
    if not f:
        return
    name, data = f
    spec = page_spec_input("eimg_spec")
    if st.button("Extract", type="primary"):
        res = run("Scanning…", E.extract_embedded_images, data, spec, stem(name))
        if res is not None:
            if not res:
                st.warning("No embedded raster images found.")
            else:
                deliver_many(res, f"{stem(name)}_images.zip", "Extract images")
                st.image([b for _, b in res[:6]], width=150)


def tool_inspector():
    header("🧪", "PDF Inspector", "Instant health-check and document anatomy.")
    f = pick_pdf("info", allow_encrypted=True)
    if not f:
        return
    name, data = f
    pw = None
    try:
        info = _info(data)
    except PDFError:
        pw = st.text_input("Password", type="password")
        if not pw:
            return
        info = run("Analyzing…", E.analyze, data, pw)
        if not info:
            return
    c = st.columns(4)
    c[0].metric("Pages", info.pages)
    c[1].metric("Size", E.human_size(info.size_bytes))
    c[2].metric("Words", f"{info.words:,}")
    c[3].metric("Images", info.images)
    flags = [("Text layer", info.has_text), ("Encrypted", info.encrypted), ("Form fields", info.has_forms),
             ("Bookmarks", info.has_outline)]
    st.markdown("".join(f'<span class="chip">{"✅" if v else "➖"} {k}</span>' for k, v in flags),
                unsafe_allow_html=True)
    if not info.has_text:
        st.info("No text layer detected — this looks like a scan. Use **OCR** to make it searchable.")
    a, b = st.columns(2)
    with a:
        st.subheader("Properties")
        st.table(pd.DataFrame({"Property": ["PDF version", "Title", "Author", "Subject", "Creator", "Producer",
                                            "Created", "Modified"],
                               "Value": [info.version, info.title, info.author, info.subject, info.creator,
                                         info.producer, info.created, info.modified]}).set_index("Property"))
    with b:
        st.subheader("Page sizes")
        names = {(595, 842): "A4", (612, 792): "Letter", (842, 1191): "A3", (420, 595): "A5", (612, 1008): "Legal"}

        def label(w, h):
            for (a_, b_), nm in names.items():
                if (abs(w - a_) < 3 and abs(h - b_) < 3):
                    return nm
                if (abs(w - b_) < 3 and abs(h - a_) < 3):
                    return f"{nm} (landscape)"
            return "Custom"

        sizes = pd.Series([f"{w / 72 * 25.4:.0f}×{h / 72 * 25.4:.0f} mm · {label(w, h)}"
                           for w, h in info.page_sizes]).value_counts().rename_axis("Size").reset_index(name="Pages")
        st.dataframe(sizes, hide_index=True, use_container_width=True)
    if pw is None:
        preview(data, n=4)


# --------------------------------------------------------------------------- #
# Registry & navigation
# --------------------------------------------------------------------------- #
TOOLS = [
    ("merge", "🧩", "Merge", "Combine PDFs with page ranges", "Organize", tool_merge),
    ("split", "✂️", "Split", "Ranges, every N pages or each page", "Organize", tool_split),
    ("organize", "🗂️", "Organize Pages", "Reorder, rotate and delete visually", "Organize", tool_organize),
    ("rotcrop", "🔄", "Rotate & Crop", "Fix orientation, trim margins", "Organize", tool_rotate_crop),
    ("text", "📝", "Extract Text", "Export to TXT or Word", "Convert", tool_extract_text),
    ("tables", "📊", "Extract Tables", "Tables to Excel / CSV", "Convert", tool_extract_tables),
    ("toimg", "🖼️", "PDF → Images", "PNG or JPEG up to 300 DPI", "Convert", tool_to_images),
    ("fromimg", "🧷", "Images → PDF", "Photos and scans to one PDF", "Create", tool_images_to_pdf),
    ("fromtxt", "✍️", "Text → PDF", "Typeset text into a clean PDF", "Create", tool_text_to_pdf),
    ("watermark", "💧", "Watermark", "Diagonal or tiled text stamps", "Enhance", tool_watermark),
    ("numbers", "🔢", "Page Numbers", "Custom format and position", "Enhance", tool_page_numbers),
    ("ocr", "🔍", "OCR", "Make scans searchable", "Enhance", tool_ocr),
    ("protect", "🔐", "Protect & Unlock", "AES-256 encryption", "Secure", tool_protect),
    ("meta", "🏷️", "Metadata", "Edit or scrub properties", "Secure", tool_metadata),
    ("compress", "🗜️", "Compress", "Three smart levels", "Optimize", tool_compress),
    ("eimg", "📸", "Extract Images", "Pull out embedded pictures", "Optimize", tool_extract_images),
    ("inspect", "🧪", "Inspector", "Health-check any PDF", "Optimize", tool_inspector),
]
REG = {t[0]: t for t in TOOLS}
st.session_state.setdefault("nav", "home")


def go(tool_id: str):
    st.session_state["nav"] = tool_id


def home():
    st.markdown("""
<div class="hero"><h1>📑 PDF ToolHub</h1>
<p>Every PDF tool you need in one fast, private workspace. Merge, split, convert, secure and optimize —
all processed in memory, nothing is stored.</p>
<div class="badges"><span>⚡ 17 tools</span><span>🔒 Private by design</span><span>🧠 OCR ready</span>
<span>📦 Batch &amp; ZIP export</span></div></div>""", unsafe_allow_html=True)
    s = st.session_state.stats
    m = st.columns(3)
    m[0].metric("Operations this session", s["ops"])
    m[1].metric("Space saved", E.human_size(s["bytes_saved"]))
    m[2].metric("Tools available", len(TOOLS))
    cats: dict[str, list] = {}
    for t in TOOLS:
        cats.setdefault(t[4], []).append(t)
    for cat, items in cats.items():
        st.markdown(f'<div class="cat">{cat}</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        for i, (tid, ico, title, desc, _, _) in enumerate(items):
            with cols[i % 4]:
                st.markdown(f'<div class="tool-card"><div class="t">{ico} {title}</div>'
                            f'<div class="d">{desc}</div></div>', unsafe_allow_html=True)
                st.button("Open", key=f"open_{tid}", on_click=go, args=(tid,), use_container_width=True)


with st.sidebar:
    st.markdown('<div class="brand">📑 PDF ToolHub<small>Premium PDF workspace</small></div>', unsafe_allow_html=True)
    st.divider()
    st.radio("Navigate", ["home"] + [t[0] for t in TOOLS], key="nav", label_visibility="collapsed",
             format_func=lambda i: "🏠  Home" if i == "home" else f"{REG[i][1]}  {REG[i][2]}")
    st.divider()
    if st.session_state.history:
        st.caption("RECENT ACTIVITY")
        for h in st.session_state.history[:5]:
            st.markdown(f'<div class="hist">{h["t"]} · <b>{h["tool"]}</b><br>{h["file"]}</div>',
                        unsafe_allow_html=True)
        if st.button("Clear history", use_container_width=True):
            st.session_state.history = []
            st.rerun()
    st.caption("🔒 Files are processed in memory and discarded when you close the tab.")

if st.session_state["nav"] == "home":
    home()
else:
    REG[st.session_state["nav"]][5]()
