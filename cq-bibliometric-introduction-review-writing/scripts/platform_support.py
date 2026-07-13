#!/usr/bin/env python3
"""Cross-platform environment, path, optional-tool and error helpers."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from typing import Any


WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
SUPPORTED_PYTHON = (3, 10) <= sys.version_info[:2] <= (3, 13)


def executable(name: str) -> str:
    candidates = [name]
    if name == "libreoffice": candidates += ["soffice", "soffice.exe", "libreoffice.exe"]
    if name == "tesseract": candidates += ["tesseract.exe"]
    found = next((value for value in (shutil.which(x) for x in candidates) if value), "")
    if found: return found
    known = {
        "libreoffice": [Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"), Path("C:/Program Files/LibreOffice/program/soffice.exe"), Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe")],
        "tesseract": [Path("C:/Program Files/Tesseract-OCR/tesseract.exe"), Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract")],
        "chrome": [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), Path("C:/Program Files/Google/Chrome/Application/chrome.exe")],
        "msedge": [Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"), Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe")],
        "firefox": [Path("/Applications/Firefox.app/Contents/MacOS/firefox"), Path("C:/Program Files/Mozilla Firefox/firefox.exe")],
        "safari": [Path("/Applications/Safari.app/Contents/MacOS/Safari")],
    }
    return next((str(path) for path in known.get(name, []) if path.exists()), "")


def path_issues(path: Path, projected_suffix: int = 96) -> list[dict[str, str]]:
    """Return actionable portability issues without modifying the path."""
    raw = str(path); windows_style = os.name == "nt" or bool(re.match(r"^[A-Za-z]:[\\/]", raw))
    path = Path(path).expanduser().absolute()
    issues: list[dict[str, str]] = []
    if windows_style:
        parts = PureWindowsPath(raw).parts if re.match(r"^[A-Za-z]:[\\/]", raw) else path.parts
        for index, part in enumerate(parts):
            if index == 0 and re.fullmatch(r"[A-Za-z]:\\?", part): continue
            stem = part.rstrip(" .").split(".", 1)[0].upper()
            if stem in WINDOWS_RESERVED:
                issues.append({"code": "windows-reserved-name", "message": f"Windows保留名不可用：{part}", "recovery": "更换任务目录名称"})
            if re.search(r'[<>:"|?*]', part):
                issues.append({"code": "windows-illegal-character", "message": f"Windows路径含非法字符：{part}", "recovery": "移除 < > : \" | ? *"})
        if len(str(path)) + projected_suffix >= 240:
            issues.append({"code": "windows-long-path-risk", "message": f"预计输出路径可能超过240字符：{path}", "recovery": "改用更短任务根目录，例如 C:\\reviews\\task"})
    parent = path.parent
    if parent.exists():
        collisions = [item.name for item in parent.iterdir() if item.name.casefold() == path.name.casefold() and item.name != path.name]
        if collisions: issues.append({"code": "case-collision", "message": f"路径与现有名称仅大小写不同：{collisions[0]}", "recovery": "使用不依赖大小写区分的唯一名称"})
    return issues


def optional_capability(name: str) -> dict[str, Any]:
    if name == "ocr":
        binary = executable("tesseract")
        return {"module": name, "status": "ready" if binary else "skipped-unavailable", "executable": binary, "reason": "" if binary else "Tesseract不在PATH", "recovery": "安装Tesseract并确保tesseract可执行文件在PATH"}
    if name == "legacy-doc":
        binary = executable("libreoffice")
        return {"module": name, "status": "ready" if binary else "skipped-unavailable", "executable": binary, "reason": "" if binary else "LibreOffice/soffice不在PATH", "recovery": "安装LibreOffice或将.doc另存为.docx"}
    raise ValueError(f"unknown optional capability: {name}")


def platform_report() -> dict[str, Any]:
    browsers = {name: executable(name) for name in ("chrome", "google-chrome", "chromium", "msedge", "firefox", "safari")}
    browser = next((value for value in browsers.values() if value), "")
    font_roots = [Path.home() / ".fonts", Path("/usr/share/fonts"), Path("/Library/Fonts"), Path("C:/Windows/Fonts")]
    fonts_available = any(path.exists() and any(path.rglob("*.ttf")) for path in font_roots)
    ocr_languages: list[str] = []
    tesseract = executable("tesseract")
    if tesseract:
        try:
            output = subprocess.run([tesseract, "--list-langs"], capture_output=True, text=True, timeout=10, check=False).stdout
            ocr_languages = [x.strip() for x in output.splitlines()[1:] if x.strip()]
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "python": platform.python_version(), "python_executable": sys.executable,
        "python_supported": SUPPORTED_PYTHON, "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown",
        "optional_capabilities": {name: optional_capability(name) for name in ("ocr", "legacy-doc")},
        "ocr_languages": ocr_languages, "browser": {"status": "ready" if browser else "skipped-unavailable", "executable": browser, "recovery": "安装Chrome、Edge或Firefox后使用HTML导出" if not browser else ""},
        "fonts": {"status": "ready" if fonts_available else "skipped-unavailable", "recovery": "安装中文字体与Times New Roman或兼容替代字体" if not fonts_available else ""},
    }


def failure(module: str, exc: Exception, completed: list[str] | None = None, recovery: str = "") -> dict[str, Any]:
    return {"valid": False, "status": "failed-recoverable" if recovery else "failed", "module": module,
            "error_type": type(exc).__name__, "reason": str(exc), "completed": completed or [],
            "recoverable": bool(recovery), "recovery_command": recovery, "platform": platform_report()}
