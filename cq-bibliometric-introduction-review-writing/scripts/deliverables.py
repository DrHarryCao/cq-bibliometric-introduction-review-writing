#!/usr/bin/env python3
"""Create clean Markdown, offline HTML with on-demand Word export, and citation-matched RIS."""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from common import load_jsonl
from evidence import cited_records, punctuation_errors, split_embedded_references, sync_references

COPYRIGHT = "JWC💗XQ@Rednote drharry"


def clean_audit_markers(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    token = r"(?:R[0-9a-f]{14}|C\d{4}|SCTX-\d{3,})"
    text = re.sub(r"\s*\\?\[\s*C\d{4}\s*[–—-]\s*C\d{4}\s*\\?\]", "", text, flags=re.I)
    # Remove the complete legacy audit container before removing individual IDs;
    # otherwise strings such as “（R…，page:1）” turn into “（，）”.
    text = re.sub(r"[\(（]\s*(?:R[0-9a-f]{14}|C\d{4})(?:\s*[,;，；]\s*(?:R[0-9a-f]{14}|C\d{4}|page:\d+|paragraph:\d+))*\s*[\)）]", "", text, flags=re.I)
    text = re.sub(rf"\s*\\?\[(?:cite:)?\s*{token}(?:\s*[,;，；]\s*{token})*\s*\\?\]", "", text, flags=re.I)
    text = re.sub(r"\s*R[0-9a-f]{14}\b", "", text)
    text = re.sub(r"\s*SCTX-\d{3,}\b", "", text)
    text = re.sub(r"\s*page:\d+\b", "", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"[\(（]\s*[;；,，]\s*[\)）]", "", text)
    text = re.sub(r"[；;]{2,}", "；", text)
    text = re.sub(r"[，,]\s*[；;]", "；", text)
    text = re.sub(r"[；;]\s*[，,]", "；", text)
    text = re.sub(r"\[\s*[,;，；–—-]+\s*\]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _inline(text: str) -> str:
    safe = html.escape(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"\*(.+?)\*", r"<em>\1</em>", safe)
    safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
    safe = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', safe)
    return safe


def markdown_body(text: str) -> tuple[str, list[tuple[str, str]]]:
    out, toc, paragraph, in_code, code = [], [], [], False, []
    def flush():
        if paragraph:
            out.append("<p>" + _inline(" ".join(paragraph)) + "</p>"); paragraph.clear()
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            flush()
            if in_code: out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>"); code = []
            in_code = not in_code; continue
        if in_code: code.append(line); continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush(); level, title = len(heading.group(1)), heading.group(2).strip(); anchor = f"h{len(toc)+1}"
            toc.append((anchor, title)); out.append(f'<h{level} id="{anchor}">{_inline(title)}</h{level}>'); continue
        if re.match(r"^[-*+]\s+", line):
            flush(); out.append("<ul><li>" + _inline(re.sub(r"^[-*+]\s+", "", line)) + "</li></ul>"); continue
        if re.match(r"^\d+[.)]\s+", line):
            flush(); out.append("<ol><li>" + _inline(re.sub(r"^\d+[.)]\s+", "", line)) + "</li></ol>"); continue
        if line.startswith(">"):
            flush(); out.append("<blockquote>" + _inline(line.lstrip("> ")) + "</blockquote>"); continue
        if not line: flush()
        else: paragraph.append(line)
    flush(); return "\n".join(out), toc


WORD_EXPORT_JS = r"""
function cqXml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));}
function cqU16(n){return new Uint8Array([n&255,(n>>>8)&255]);}
function cqU32(n){return new Uint8Array([n&255,(n>>>8)&255,(n>>>16)&255,(n>>>24)&255]);}
function cqJoin(parts){let n=parts.reduce((s,p)=>s+p.length,0),o=new Uint8Array(n),i=0;for(const p of parts){o.set(p,i);i+=p.length;}return o;}
const cqCrcTable=(()=>{let t=[];for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=(c&1)?0xedb88320^(c>>>1):c>>>1;t[n]=c>>>0;}return t;})();
function cqCrc(bytes){let c=0xffffffff;for(const b of bytes)c=cqCrcTable[(c^b)&255]^(c>>>8);return (c^0xffffffff)>>>0;}
function cqZip(files){const enc=new TextEncoder(),locals=[],centrals=[];let offset=0;for(const [name,dataText] of Object.entries(files)){const nameBytes=enc.encode(name),data=enc.encode(dataText),crc=cqCrc(data);const local=cqJoin([cqU32(0x04034b50),cqU16(20),cqU16(0x0800),cqU16(0),cqU16(0),cqU16(0),cqU32(crc),cqU32(data.length),cqU32(data.length),cqU16(nameBytes.length),cqU16(0),nameBytes,data]);locals.push(local);centrals.push(cqJoin([cqU32(0x02014b50),cqU16(20),cqU16(20),cqU16(0x0800),cqU16(0),cqU16(0),cqU16(0),cqU32(crc),cqU32(data.length),cqU32(data.length),cqU16(nameBytes.length),cqU16(0),cqU16(0),cqU16(0),cqU16(0),cqU32(0),cqU32(offset),nameBytes]));offset+=local.length;}const central=cqJoin(centrals),end=cqJoin([cqU32(0x06054b50),cqU16(0),cqU16(0),cqU16(centrals.length),cqU16(centrals.length),cqU32(central.length),cqU32(offset),cqU16(0)]);return new Blob([cqJoin([...locals,central,end])],{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});}
function cqParagraph(el){const tag=el.tagName.toLowerCase(),style=tag==='h1'?'Title':tag==='h2'?'Heading1':tag==='h3'?'Heading2':'Normal';const text=cqXml(el.innerText.trim());if(!text)return '';return `<w:p><w:pPr><w:pStyle w:val="${style}"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="SimSun"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr><w:t xml:space="preserve">${text}</w:t></w:r></w:p>`;}
function exportWord(){const article=document.querySelector('article'),nodes=[...article.querySelectorAll('h1,h2,h3,p,li')],paras=nodes.map(cqParagraph).join('');const copyright='JWC💗XQ@Rednote drharry';const files={
'[Content_Types].xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>`,
'_rels/.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`,
'word/_rels/document.xml.rels':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>`,
'word/styles.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="SimSun"/><w:sz w:val="22"/><w:lang w:val="en-US" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:line="360" w:lineRule="auto"/><w:ind w:firstLine="480"/><w:jc w:val="both"/></w:pPr></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:spacing w:before="240" w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:spacing w:before="200" w:after="100"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style></w:styles>`,
'word/footer1.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:t>${cqXml(copyright)}</w:t></w:r></w:p></w:ftr>`,
'word/document.xml':`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>${paras}<w:sectPr><w:footerReference w:type="default" r:id="rId1"/><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1361" w:bottom="1361" w:left="1474" w:header="720" w:footer="720"/></w:sectPr></w:body></w:document>`};const blob=cqZip(files),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=(document.title||'CQ-academic-deliverable')+'.docx';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);}
"""


def build_html(title: str, markdown: str) -> str:
    body, toc = markdown_body(markdown)
    toc_html = "".join(f'<a href="#{a}">{html.escape(t)}</a>' for a, t in toc)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
@page{{size:A4;margin:25mm 24mm 24mm}}*{{box-sizing:border-box}}body{{margin:0;background:#eef1f4;color:#20242a;font-family:"Times New Roman","Songti SC",SimSun,serif;line-height:1.75}}.toolbar{{position:sticky;top:0;z-index:5;padding:10px 5vw;background:#17324d;color:white;display:flex;gap:10px;align-items:center}}button,a.export{{border:0;border-radius:5px;padding:8px 14px;background:#fff;color:#17324d;text-decoration:none;cursor:pointer;font:inherit}}.layout{{max-width:1180px;margin:24px auto;display:grid;grid-template-columns:240px minmax(0,780px);gap:24px}}nav{{position:sticky;top:70px;align-self:start;background:white;padding:18px;border-radius:8px;max-height:80vh;overflow:auto}}nav a{{display:block;color:#315a7d;text-decoration:none;margin:7px 0;font-size:14px}}article{{background:white;padding:28mm 25mm;box-shadow:0 2px 16px #0001;min-height:297mm}}h1{{font-size:24px;text-align:center}}h2{{font-size:20px;border-bottom:1px solid #ccd5df;padding-bottom:6px}}h3{{font-size:17px}}p{{text-align:justify;text-indent:2em;margin:.55em 0}}blockquote{{background:#f5f7f9;border-left:4px solid #6e8daa;padding:10px 14px}}footer{{text-align:center;color:#667;padding:18px}}@media(max-width:850px){{.layout{{display:block;margin:0}}nav{{position:relative;top:0}}article{{padding:24px;box-shadow:none}}}}@media print{{body{{background:white}}.toolbar,nav{{display:none}}.layout{{display:block;margin:0;max-width:none}}article{{box-shadow:none;padding:0;min-height:auto}}footer{{position:fixed;bottom:0;width:100%;font-size:9pt}}a{{color:inherit;text-decoration:none}}}}
</style></head><body><div class="toolbar"><strong>CQ Academic Deliverable</strong><button onclick="exportWord()">导出Word</button><button onclick="window.print()">导出PDF</button></div><div class="layout"><nav><strong>目录</strong>{toc_html}</nav><article>{body}</article></div><footer>{COPYRIGHT}</footer><script>{WORD_EXPORT_JS}</script></body></html>"""


def _ris_escape(value: Any) -> str:
    return re.sub(r"[\r\n]+", " ", str(value or "")).strip()


def record_to_ris(record: dict[str, Any]) -> str:
    raw = next(iter((record.get("raw") or {}).values()), {})
    lines = ["TY  - JOUR", f"ID  - {record['record_id']}", f"TI  - {_ris_escape(record.get('title'))}"]
    for author in record.get("authors") or []: lines.append(f"AU  - {_ris_escape(author.get('name') if isinstance(author, dict) else author)}")
    if record.get("year"): lines.append(f"PY  - {record['year']}")
    if record.get("publication_date"): lines.append(f"Y1  - {_ris_escape(record['publication_date'])}")
    if record.get("venue"): lines.append(f"JO  - {_ris_escape(record['venue'])}")
    for tag, keys in (("VL", ("volume", "VL")), ("IS", ("issue", "IS")), ("SP", ("page", "SP"))):
        value = next((raw.get(k) for k in keys if isinstance(raw, dict) and raw.get(k)), "")
        if value: lines.append(f"{tag}  - {_ris_escape(value)}")
    doi = (record.get("ids") or {}).get("doi")
    if doi: lines.append(f"DO  - {doi}")
    if record.get("abstract"): lines.append(f"AB  - {_ris_escape(record['abstract'])}")
    for keyword in record.get("keywords") or []: lines.append(f"KW  - {_ris_escape(keyword)}")
    for source, count in (record.get("citation_counts") or {}).items(): lines.append(f"N1  - Times cited ({source}): {count}")
    for ref in record.get("references") or []: lines.append(f"CR  - {_ris_escape(ref)}")
    lines.append("ER  -"); return "\n".join(lines)


def social_source_to_ris(row: dict[str, Any], index: int) -> str:
    source_id = row.get("source_id") or f"SCTX-{index:03d}"
    year = str(row.get("publication_date") or "")[:4]
    lines = ["TY  - ELEC", f"ID  - {source_id}", f"TI  - {_ris_escape(row.get('title') or '网络资料')}"]
    if row.get("source_name"): lines.append(f"AU  - {_ris_escape(row['source_name'])}")
    if year: lines.append(f"PY  - {year}")
    if row.get("publication_date"): lines.append(f"Y1  - {_ris_escape(row['publication_date'])}")
    if row.get("url"): lines.append(f"UR  - {_ris_escape(row['url'])}")
    if row.get("retrieved_at"): lines.append(f"Y2  - {_ris_escape(row['retrieved_at'])}")
    lines.append("ER  -"); return "\n".join(lines)


def export_deliverables(root: Path, document: str) -> dict[str, Any]:
    if document == "review":
        source = root / "06_review/review_draft.md"; audit_name = "review_audit.md"; clean_name = "review.md"; title = "系统综述"
    else:
        source = root / "06_review/ssci_introduction_audit.md"; audit_name = "introduction_audit.md"; clean_name = "introduction.md"; title = "SSCI漏斗型绪论"
    if not source.exists(): raise RuntimeError(f"缺少已完成的 {document} 审计稿：{source}")
    sync_references(root, document, source)
    audit = source.read_text(encoding="utf-8"); body, _ = split_embedded_references(audit)
    clean = clean_audit_markers(audit)
    defects = punctuation_errors(clean, document)
    if re.search(r"\b(?:R[0-9a-f]{14}|C\d{4}|SCTX-\d{3,})\b", clean):
        defects.append(f"{document}仍含内部审计ID")
    if defects: raise RuntimeError("交付前标点审计失败：" + "；".join(defects))
    out = root / "06_review/deliverables"; out.mkdir(parents=True, exist_ok=True)
    (out / audit_name).write_text(audit, encoding="utf-8"); (out / clean_name).write_text(clean, encoding="utf-8")
    # The generated deliverables directory is HTML-centred; remove legacy Word
    # outputs and Word lock files left by earlier skill versions.
    for stale_docx in out.glob("*.docx"):
        stale_docx.unlink()
    html_path = out / f"{document}.html"; html_path.write_text(build_html(title, clean), encoding="utf-8")
    ledger = load_jsonl(root / "05_evidence/claim_ledger.jsonl"); ids = cited_records(body, ledger)
    records = {r["record_id"]: r for r in load_jsonl(root / "02_corpus/corpus.jsonl")}; missing = sorted(ids - records.keys())
    if missing: raise RuntimeError(f"RIS导出缺少记录：{missing}")
    ris_blocks = [record_to_ris(records[rid]) for rid in sorted(ids)]
    social_rows = load_jsonl(root / "06_review/social_context_sources.jsonl") if document == "introduction" else []
    ris_blocks.extend(social_source_to_ris(row, index) for index, row in enumerate(social_rows, 1))
    ris = out / f"{document}_references.ris"; ris.write_text("\n\n".join(ris_blocks) + "\n", encoding="utf-8")
    index = out / "index.html"
    items = []
    for kind in ("review", "introduction"):
        if (out / f"{kind}.html").exists(): items.append(f'<li><a href="{kind}.html">{kind}</a> · HTML内导出Word/PDF · <a href="{kind}_references.ris">RIS</a></li>')
    index.write_text(f"<!doctype html><meta charset='utf-8'><title>CQ Deliverables</title><style>body{{max-width:760px;margin:60px auto;font:18px/1.7 sans-serif}}</style><h1>CQ Academic Deliverables</h1><ul>{''.join(items)}</ul><footer>{COPYRIGHT}</footer>", encoding="utf-8")
    return {"document": document, "audit_md": str(out / audit_name), "clean_md": str(out / clean_name), "html": str(html_path), "word_export": "browser-generated-docx", "ris": str(ris), "cited_records": len(ids), "social_sources": len(social_rows), "index": str(index)}
