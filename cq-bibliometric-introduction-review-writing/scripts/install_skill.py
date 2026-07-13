#!/usr/bin/env python3
"""Install the canonical skill for Codex and Claude without requiring symlink privileges."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
NAME = SKILL.name
MANIFEST = ".cq-install.json"
IGNORED = {MANIFEST, ".DS_Store", "__pycache__"}


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not any(x in IGNORED for x in p.parts)):
        digest.update(path.relative_to(root).as_posix().encode("utf-8")); digest.update(path.read_bytes())
    return digest.hexdigest()


def targets(host: str, scope: str) -> dict[str, Path]:
    root = SKILL.parent
    if scope == "project":
        values = {"codex": root / ".agents/skills" / NAME, "claude": root / ".claude/skills" / NAME}
    else:
        values = {
            "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills" / NAME,
            "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "skills" / NAME,
        }
    return values if host == "both" else {host: values[host]}


def _is_same_link(target: Path) -> bool:
    try: return target.is_symlink() and target.resolve() == SKILL
    except OSError: return False


def _is_same_junction(target: Path) -> bool:
    if os.name != "nt" or not target.exists() or target.is_symlink(): return False
    try: return os.path.samefile(target, SKILL)
    except OSError: return False


def _managed(target: Path) -> bool:
    return target.is_dir() and (target / MANIFEST).exists()


def _remove_managed(target: Path) -> None:
    if _is_same_link(target): target.unlink(); return
    if _is_same_junction(target): target.rmdir(); return
    if _managed(target): shutil.rmtree(target); return
    if target.exists(): raise RuntimeError(f"拒绝覆盖非受管入口：{target}")


def _junction(target: Path) -> bool:
    if os.name != "nt": return False
    result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(target), str(SKILL)], capture_output=True, text=True, check=False)
    return result.returncode == 0 and target.exists()


def install_one(host: str, target: Path, mode: str = "auto") -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    if _is_same_link(target): return {"host": host, "target": str(target), "mode": "symlink", "status": "ready", "hash": tree_hash(SKILL)}
    if _is_same_junction(target): return {"host": host, "target": str(target), "mode": "junction", "status": "ready", "hash": tree_hash(SKILL)}
    if _managed(target) and json.loads((target / MANIFEST).read_text(encoding="utf-8")).get("source_hash") == tree_hash(SKILL):
        return {"host": host, "target": str(target), "mode": "copy", "status": "ready", "hash": tree_hash(SKILL)}
    _remove_managed(target)
    errors = []
    if mode in {"auto", "link"}:
        try:
            target.symlink_to(SKILL, target_is_directory=True)
            return {"host": host, "target": str(target), "mode": "symlink", "status": "installed", "hash": tree_hash(SKILL)}
        except OSError as exc: errors.append(f"symlink: {exc}")
    if mode in {"auto", "junction"}:
        if _junction(target): return {"host": host, "target": str(target), "mode": "junction", "status": "installed", "hash": tree_hash(SKILL)}
        errors.append("junction unavailable")
    if mode not in {"auto", "copy"}: raise RuntimeError("; ".join(errors))
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", MANIFEST))
    info = {"schema_version": 1, "host": host, "source": str(SKILL), "source_hash": tree_hash(SKILL), "mode": "copy"}
    (target / MANIFEST).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"host": host, "target": str(target), "mode": "copy", "status": "installed", "hash": info["source_hash"], "fallback_reasons": errors}


def inspect_one(host: str, target: Path) -> dict:
    mode = "symlink" if _is_same_link(target) else "junction" if _is_same_junction(target) else "copy" if _managed(target) else "unmanaged-directory" if target.exists() else "missing"
    source_hash = tree_hash(SKILL); installed_hash = tree_hash(target) if target.exists() else ""
    return {"host": host, "target": str(target), "mode": mode, "status": "ready" if installed_hash == source_hash else "out-of-sync" if target.exists() else "missing", "source_hash": source_hash, "installed_hash": installed_hash}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CQ skill cross-platform installer")
    parser.add_argument("action", nargs="?", choices=["install", "status", "repair", "uninstall"], default="install")
    parser.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    parser.add_argument("--scope", choices=["project", "user"], default="project")
    parser.add_argument("--mode", choices=["auto", "link", "junction", "copy"], default="auto")
    args = parser.parse_args(argv); selected = targets(args.host, args.scope); rows = []
    try:
        for host, target in selected.items():
            if args.action == "status": rows.append(inspect_one(host, target))
            elif args.action in {"install", "repair"}: rows.append(install_one(host, target, args.mode))
            else:
                _remove_managed(target); rows.append({"host": host, "target": str(target), "status": "uninstalled"})
        print(json.dumps({"valid": all(x["status"] in {"ready", "installed", "uninstalled"} for x in rows), "action": args.action, "entries": rows}, ensure_ascii=False, indent=2)); return 0
    except Exception as exc:
        print(json.dumps({"valid": False, "action": args.action, "error_type": type(exc).__name__, "reason": str(exc), "recovery": "检查目标是否为受管入口，或使用 --mode copy"}, ensure_ascii=False, indent=2)); return 1


if __name__ == "__main__": raise SystemExit(main())
