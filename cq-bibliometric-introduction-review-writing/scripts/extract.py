#!/usr/bin/env python3
"""Extract lawful local full text with stable page/paragraph anchors."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

from common import file_sha256, normalize_title, utc_stamp, write_json


SUPPORTED = {".pdf", ".docx", ".doc", ".txt", ".md", ".markdown"}
SECTION_PATTERNS = {
    "abstract": r"^(?:abstract|摘要)\b", "introduction": r"^(?:\d+[.\s]*)?(?:introduction|引言|绪论)\b",
    "methods": r"^(?:\d+[.\s]*)?(?:methods?|methodology|材料与方法|研究方法)\b",
    "results": r"^(?:\d+[.\s]*)?(?:results?|结果)\b", "discussion": r"^(?:\d+[.\s]*)?(?:discussion|讨论)\b",
    "limitations": r"^(?:\d+[.\s]*)?(?:limitations?|局限)\b", "references": r"^(?:references|bibliography|参考文献)\b",
}


def expand_documents(inputs: Iterable[Path]) -> list[Path]:
    files = []
    for value in inputs:
        path = value.expanduser()
        if path.is_dir(): files.extend(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
        elif path.is_file() and path.suffix.lower() in SUPPORTED: files.append(path)
    return sorted(set(p.resolve() for p in files))


def detect_sections(lines: list[str]) -> list[dict[str, Any]]:
    sections = []
    for idx, line in enumerate(lines, 1):
        clean = re.sub(r"[#*_]+", "", line).strip()
        if len(clean) > 100: continue
        for name, pattern in SECTION_PATTERNS.items():
            if re.match(pattern, clean, flags=re.I):
                sections.append({"name": name, "line": idx, "heading": clean}); break
    return sections


def extract_pdf(path: Path, ocr: bool = False) -> tuple[str, dict[str, Any]]:
    try: import fitz
    except ImportError as exc: raise RuntimeError("PDF 处理需要 PyMuPDF：pip install pymupdf") from exc
    doc = fitz.open(path); chunks, chars = [], 0
    ocr_pages = 0
    for page_no, page in enumerate(doc, 1):
        text = page.get_text("text").strip()
        if ocr and len(text) < 120:
            if not shutil.which("tesseract"): raise RuntimeError("已请求 OCR，但系统找不到 tesseract 可执行文件。")
            try:
                import pytesseract
                from PIL import Image
            except ImportError as exc: raise RuntimeError("OCR 需要 pytesseract 和 Pillow。") from exc
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            text = pytesseract.image_to_string(Image.frombytes("RGB", [pix.width, pix.height], pix.samples), lang="chi_sim+eng").strip()
            ocr_pages += 1
        chars += len(text)
        chunks += [f"<!-- page:{page_no} -->", f"## [page:{page_no}]", "", text, ""]
    pages = len(doc); doc.close()
    density = chars / max(pages, 1)
    return "\n".join(chunks), {"pages": pages, "characters": chars, "characters_per_page": round(density, 1), "needs_ocr": density < 120 and not ocr, "ocr_pages": ocr_pages}


def extract_docx(path: Path) -> tuple[str, dict[str, Any]]:
    try: from docx import Document
    except ImportError as exc: raise RuntimeError("DOCX 处理需要 python-docx：pip install python-docx") from exc
    doc = Document(path); chunks, count = [], 0
    for idx, para in enumerate(doc.paragraphs, 1):
        text = para.text.strip()
        if text:
            style = (para.style.name or "").lower() if para.style else ""
            prefix = "## " if "heading" in style or "标题" in style else ""
            chunks.append(f"<!-- paragraph:{idx} -->\n{prefix}[paragraph:{idx}] {text}\n"); count += 1
    for t_idx, table in enumerate(doc.tables, 1):
        chunks.append(f"\n## [table:{t_idx}]\n")
        for row in table.rows: chunks.append("| " + " | ".join(cell.text.replace("\n", " ").strip() for cell in row.cells) + " |")
    return "\n".join(chunks), {"paragraphs": count, "tables": len(doc.tables), "characters": sum(len(x) for x in chunks), "needs_ocr": False}


def convert_doc(path: Path) -> Path:
    libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not libreoffice: raise RuntimeError("旧版 .doc 需要 LibreOffice/soffice 转换；请安装或另存为 .docx。")
    temp = Path(tempfile.mkdtemp(prefix="review-doc-"))
    subprocess.run([libreoffice, "--headless", "--convert-to", "docx", "--outdir", str(temp), str(path)], check=True, capture_output=True)
    converted = temp / f"{path.stem}.docx"
    if not converted.exists(): raise RuntimeError(f"未生成转换文件：{path.name}")
    return converted


def extract_one(path: Path, ocr: bool = False) -> tuple[str, dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf": text, meta = extract_pdf(path, ocr=ocr)
    elif suffix == ".docx": text, meta = extract_docx(path)
    elif suffix == ".doc": text, meta = extract_docx(convert_doc(path)); meta["converted_from_doc"] = True
    else:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        lines = raw.splitlines(); text = "\n".join(f"<!-- line:{i} -->\n{line}" for i, line in enumerate(lines, 1))
        meta = {"lines": len(lines), "characters": len(raw), "needs_ocr": False}
    meta.update({"source": str(path), "sha256": file_sha256(path), "extracted_at": utc_stamp(), "sections": detect_sections(text.splitlines())})
    return text, meta


def reference_lines(text: str) -> list[dict[str, Any]]:
    marker = re.search(r"(?im)^#{0,3}\s*(?:\[[^]]+\]\s*)?(?:references|bibliography|参考文献)\s*$", text)
    tail = text[marker.end():] if marker else ""
    rows = []
    for line in tail.splitlines():
        clean = re.sub(r"^(?:<!--.*?-->|#+|\[?\d+\]?[.)]?\s*)", "", line).strip()
        if len(clean) < 20: continue
        doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", clean, flags=re.I)
        year = re.search(r"(?:19|20)\d{2}", clean)
        rows.append({"raw": clean, "doi": doi.group(0).rstrip(".,)") if doi else "", "year": int(year.group()) if year else None})
    return rows


def extract_documents(root: Path, inputs: Iterable[Path], ocr: bool = False) -> list[dict[str, Any]]:
    report = []
    original, out = root / "03_fulltext/original", root / "03_fulltext/extracted"
    original.mkdir(parents=True, exist_ok=True); out.mkdir(parents=True, exist_ok=True)
    for path in expand_documents(inputs):
        digest = file_sha256(path); stem = f"{digest[:12]}-{re.sub(r'[^0-9A-Za-z\u4e00-\u9fff-]+', '-', path.stem)[:70]}"
        target = original / f"{stem}{path.suffix.lower()}"
        if not target.exists(): shutil.copy2(path, target)
        try:
            text, meta = extract_one(path, ocr=ocr); refs = reference_lines(text); meta["reference_candidates"] = len(refs)
            md = f"# {path.stem}\n\n- source_sha256: `{digest}`\n- evidence_level: fulltext\n\n{text}"
            (out / f"{stem}.md").write_text(md, encoding="utf-8")
            write_json(out / f"{stem}.meta.json", meta); write_json(out / f"{stem}.references.json", refs)
            report.append({"file": str(path), "status": "ok", "output": str(out / f"{stem}.md"), **{k: meta.get(k) for k in ("characters", "pages", "paragraphs", "needs_ocr", "reference_candidates")}})
        except Exception as exc:
            report.append({"file": str(path), "status": "error", "error": str(exc)})
    write_json(root / "03_fulltext/extraction_report.json", report)
    return report
