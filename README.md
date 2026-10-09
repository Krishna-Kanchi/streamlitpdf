# 📑 PDF ToolHub

A premium, all-in-one PDF workspace built with Streamlit. 17 tools, processed entirely in memory.

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
OCR needs the Tesseract binary (`apt install tesseract-ocr` / `brew install tesseract`; add language packs as needed).

## Tools
| Group | Tools |
|---|---|
| Organize | Merge · Split · Organize pages (thumbnails, reorder, rotate, delete) · Rotate & Crop |
| Convert | Extract text (TXT/DOCX) · Extract tables (XLSX/CSV) · PDF → Images |
| Create | Images → PDF · Text → PDF |
| Enhance | Watermark (diagonal/tiled) · Page numbers · OCR |
| Secure | Protect (AES-256, permissions) · Unlock · Metadata editor/scrubber |
| Optimize | Compress (3 levels) · Extract embedded images · Inspector |

## Structure
- `engine.py` – UI-independent processing functions (bytes in, bytes out; easy to test or reuse in an API)
- `app.py` – Streamlit interface, theming, navigation, session stats
- Page-range syntax everywhere: `all`, `1-3,5`, `4-`, `odd`, `even`, `5-1` (reverse)

## Non-English text (Telugu, Hindi, Tamil, Cyrillic…)
Text → PDF, Watermark and Page numbers auto-select a Unicode font that covers your text. Free Noto fonts
(fonts.google.com/noto) dropped into the `fonts/` folder are used first, e.g. `NotoSansTelugu-Regular.ttf`.
Install `uharfbuzz` (in requirements.txt) so Indic letters join correctly. Arabic/Hebrew are not laid out right-to-left.

## Notes
- Files are never written to disk or stored; closing the tab discards them.
- "Maximum" compression rasterizes pages, so text becomes non-selectable (run OCR afterwards if needed).
- Password recovery is not supported - only removal with a known password.
