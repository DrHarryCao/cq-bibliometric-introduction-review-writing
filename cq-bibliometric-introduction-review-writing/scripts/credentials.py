#!/usr/bin/env python3
"""Secure credential dialogs and OS-backed storage; never persist plaintext in tasks."""
from __future__ import annotations

import getpass
import hashlib
import os
import platform
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from typing import Any


SERVICE_PREFIX = "com.drharryc.cq-bibliometric-introduction-review-writing"
LEGACY_PREFIX = "com.drharryc.map-research-and-write-review"
SERVICES = {
    "OPENALEX_API_KEY": f"{SERVICE_PREFIX}.openalex-api-key",
    "UNPAYWALL_EMAIL": f"{SERVICE_PREFIX}.unpaywall-email",
    "CROSSREF_EMAIL": f"{SERVICE_PREFIX}.crossref-email",
    "S2_API_KEY": f"{SERVICE_PREFIX}.semantic-scholar-api-key",
}
SESSION_CREDENTIALS: dict[str, str] = {}
LAST_BACKEND_ERROR = ""
LEGACY_SERVICES = {name: service.replace(SERVICE_PREFIX, LEGACY_PREFIX) for name, service in SERVICES.items()}
LABELS = {
    "OPENALEX_API_KEY": "OpenAlex API key",
    "UNPAYWALL_EMAIL": "Unpaywall email",
    "CROSSREF_EMAIL": "Crossref email",
    "S2_API_KEY": "Semantic Scholar API key",
}


def _account() -> str:
    return getpass.getuser() or "default"


def _macos_get(service: str) -> str:
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-a", _account(), "-s", service, "-w"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _macos_set(service: str, value: str) -> None:
    result = subprocess.run(
        ["/usr/bin/security", "add-generic-password", "-U", "-a", _account(), "-s", service, "-w", value],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法写入 macOS 钥匙串：{result.stderr.strip() or 'unknown error'}")


def _macos_delete(service: str) -> None:
    subprocess.run(["/usr/bin/security", "delete-generic-password", "-a", _account(), "-s", service], capture_output=True, text=True, timeout=10, check=False)


def _keyring_get(service: str) -> str:
    global LAST_BACKEND_ERROR
    try:
        import keyring
        return keyring.get_password(service, _account()) or ""
    except Exception as exc:
        LAST_BACKEND_ERROR = f"{type(exc).__name__}: {exc}"
        return ""


def _keyring_set(service: str, value: str) -> None:
    global LAST_BACKEND_ERROR
    try:
        import keyring
        keyring.set_password(service, _account(), value)
    except Exception as exc:
        LAST_BACKEND_ERROR = f"{type(exc).__name__}: {exc}"
        raise RuntimeError("系统安全凭据库不可用；凭据只能在本次进程中临时使用。") from exc


def _keyring_delete(service: str) -> None:
    try:
        import keyring
        keyring.delete_password(service, _account())
    except Exception:
        pass


def _stored_value(name: str) -> tuple[str, str]:
    if SESSION_CREDENTIALS.get(name): return SESSION_CREDENTIALS[name], "session-only"
    getter = _macos_get if platform.system() == "Darwin" else _keyring_get
    current = getter(SERVICES[name])
    if current: return current, "keychain" if platform.system() == "Darwin" else "keyring"
    legacy = getter(LEGACY_SERVICES[name])
    return (legacy, "legacy-keychain" if platform.system() == "Darwin" else "legacy-keyring") if legacy else ("", "missing")


def credential_value(name: str) -> str:
    """Environment variables override stored credentials without exposing either."""
    value = os.getenv(name, "").strip()
    if value: return value
    if name not in SERVICES: return ""
    return _stored_value(name)[0]


def store_credential(name: str, value: str, allow_session_fallback: bool = True) -> str:
    service = SERVICES.get(name)
    if not service: raise ValueError(f"Unsupported credential: {name}")
    value = str(value or "").strip()
    if not value: raise ValueError(f"Credential cannot be empty: {name}")
    try:
        if platform.system() == "Darwin": _macos_set(service, value)
        else: _keyring_set(service, value)
        return "keychain" if platform.system() == "Darwin" else "keyring"
    except Exception:
        if not allow_session_fallback: raise
        SESSION_CREDENTIALS[name] = value
        return "session-only"


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8] if value else ""


def credential_status() -> dict[str, Any]:
    items = {}
    for name in SERVICES:
        env = os.getenv(name, "").strip()
        stored, stored_source = _stored_value(name)
        value = env or stored
        items[name] = {
            "label": LABELS[name], "configured": bool(value),
            "source": "environment" if env else stored_source,
            "fingerprint": _fingerprint(value),
            "environment_overrides_secure_store": bool(env and stored),
        }
    return {"configured": bool(items["OPENALEX_API_KEY"]["configured"]), "credentials": items, "backend_error": LAST_BACKEND_ERROR, "secrets_exposed": False}


def delete_credentials(names: list[str]) -> dict[str, Any]:
    deleted, shadowed = [], []
    for name in names:
        if name not in SERVICES: raise ValueError(f"Unsupported credential: {name}")
        if platform.system() == "Darwin":
            _macos_delete(SERVICES[name]); _macos_delete(LEGACY_SERVICES[name])
        else:
            _keyring_delete(SERVICES[name]); _keyring_delete(LEGACY_SERVICES[name])
        deleted.append(name)
        if os.getenv(name, "").strip(): shadowed.append(name)
    return {"deleted": deleted, "still_set_by_environment": shadowed, "secrets_exposed": False}


def credential_guide(open_browser: bool = False) -> dict[str, Any]:
    links = {
        "openalex_api_key": "https://openalex.org/settings/api",
        "openalex_usage": "https://openalex.org/settings/usage",
        "authentication_guide": "https://developers.openalex.org/guides/authentication",
    }
    if open_browser: webbrowser.open(links["openalex_api_key"])
    return {"steps": [
        "1. 打开 OpenAlex API 设置页并登录/注册免费账户。",
        "2. 复制 API key，不要粘贴到聊天或项目文件。",
        "3. 运行 credentials setup，在系统安全对话框中粘贴。",
        "4. 运行 credentials test 验证身份、网络和额度。",
        "5. 日后用 credentials update --name OPENALEX_API_KEY 替换，或用 credentials delete --name OPENALEX_API_KEY 删除。",
    ], "links": links, "required": ["OPENALEX_API_KEY"], "recommended": ["UNPAYWALL_EMAIL", "CROSSREF_EMAIL"], "optional": ["S2_API_KEY"]}


def test_credentials(timeout: int = 15) -> dict[str, Any]:
    key = credential_value("OPENALEX_API_KEY")
    if not key: return {"ok": False, "category": "missing", "message": "未配置 OpenAlex API key。", "secrets_exposed": False}
    url = "https://api.openalex.org/rate-limit?" + urllib.parse.urlencode({"api_key": key})
    request = urllib.request.Request(url, headers={"User-Agent": "cq-bibliometric-introduction-review-writing/8.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = __import__("json").loads(response.read().decode("utf-8"))
            return {"ok": True, "category": "valid", "checked_at": datetime.now(timezone.utc).isoformat(), "budget": {k: payload.get(k) for k in ("daily_limit", "daily_usage", "daily_remaining", "hourly_limit", "hourly_usage", "hourly_remaining") if k in payload}, "secrets_exposed": False}
    except urllib.error.HTTPError as exc:
        category = "invalid" if exc.code in (401, 403) else "rate-limited" if exc.code == 429 else "service-error"
        return {"ok": False, "category": category, "http_status": exc.code, "message": str(exc.reason), "secrets_exposed": False}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "category": "network", "message": str(getattr(exc, "reason", exc)), "secrets_exposed": False}


def _macos_dialog(prompt: str, title: str, hidden: bool) -> str | None:
    hidden_clause = " with hidden answer" if hidden else ""
    script = (
        f'set r to display dialog "{prompt}" with title "{title}" default answer ""'
        f'{hidden_clause} buttons {{"取消", "保存"}} default button "保存" cancel button "取消"\n'
        "return text returned of r"
    )
    result = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=300, check=False)
    if result.returncode == 0: return result.stdout.strip()
    if "-128" in result.stderr or "user canceled" in result.stderr.casefold(): return None
    raise RuntimeError(f"macOS凭据对话框不可用：{result.stderr.strip() or result.returncode}")


def _tk_dialog(prompt: str, title: str, hidden: bool) -> str | None:
    try:
        import tkinter as tk
        from tkinter import simpledialog
    except ImportError as exc:
        raise RuntimeError("无法打开凭据对话框：系统缺少 Tkinter。") from exc
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    try: return simpledialog.askstring(title, prompt, show="*" if hidden else None, parent=root)
    finally: root.destroy()


def _terminal_prompt(prompt: str, hidden: bool) -> str | None:
    try: return getpass.getpass(prompt + " ") if hidden else input(prompt + " ")
    except (EOFError, KeyboardInterrupt): return None


def prompt_value(prompt: str, title: str, hidden: bool = False, input_mode: str = "auto") -> str | None:
    if input_mode == "terminal": return _terminal_prompt(prompt, hidden)
    try:
        return _macos_dialog(prompt, title, hidden) if platform.system() == "Darwin" else _tk_dialog(prompt, title, hidden)
    except Exception:
        if input_mode == "gui": raise
        return _terminal_prompt(prompt, hidden)


def show_message(message: str, title: str = "文献综述技能") -> None:
    if platform.system() == "Darwin":
        script = f'display dialog "{message}" with title "{title}" buttons {{"好"}} default button "好"'
        subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=120, check=False)


def configure_dialog(include_semantic_scholar: bool = False, input_mode: str = "auto") -> dict[str, Any]:
    key = prompt_value("请输入 OpenAlex API Key（不会写入项目或聊天记录）：", "配置 OpenAlex", hidden=True, input_mode=input_mode)
    if key is None: return {"configured": False, "cancelled": True, "stored": []}
    if len(key.strip()) < 8: raise RuntimeError("OpenAlex API Key 为空或过短。")
    storage = {"OPENALEX_API_KEY": store_credential("OPENALEX_API_KEY", key)}
    stored = ["OPENALEX_API_KEY"]
    email = prompt_value("请输入用于 Unpaywall/Crossref 的联系邮箱（可跳过）：", "配置学术数据源", hidden=False, input_mode=input_mode)
    if email and "@" in email:
        storage["UNPAYWALL_EMAIL"] = store_credential("UNPAYWALL_EMAIL", email); storage["CROSSREF_EMAIL"] = store_credential("CROSSREF_EMAIL", email); stored += ["UNPAYWALL_EMAIL", "CROSSREF_EMAIL"]
    if include_semantic_scholar:
        s2 = prompt_value("请输入可选的 Semantic Scholar API Key（可跳过）：", "配置 Semantic Scholar", hidden=True, input_mode=input_mode)
        if s2: storage["S2_API_KEY"] = store_credential("S2_API_KEY", s2); stored.append("S2_API_KEY")
    # Keep reports serializable and never echo arbitrary backend objects.
    storage = {name: value if isinstance(value, str) else "secure-store" for name, value in storage.items()}
    show_message("凭据已安全保存。现在可以继续检索。")
    return {"configured": True, "cancelled": False, "stored": stored, "storage": storage, "persistent": all(value != "session-only" for value in storage.values()), "secrets_exposed": False}
