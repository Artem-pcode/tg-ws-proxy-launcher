"""Обновление прокси-ядра с GitHub без переустановки APK (ТЗ 4.5, 10).

Схема каталогов (в app-specific storage):
    proxy_core/current/{proxy/, version.json}   активная версия
    proxy_core/backup/                          предыдущая (для отката)
Без зависимостей от Kivy; вся сеть - только HTTPS с проверкой сертификатов.
"""
from __future__ import annotations

import ast
import datetime
import io
import json
import logging
import os
import shutil
import ssl
import sys
import urllib.error
import urllib.request
import zipfile
from itertools import zip_longest
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from . import core_loader, paths

log = logging.getLogger("tgwsp.update")

REPO = "Flowseal/tg-ws-proxy"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ARCHIVE_URL = f"https://github.com/{REPO}/archive/refs/tags/{{tag}}.zip"

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_UNPACKED_BYTES = 150 * 1024 * 1024
MAX_FILES = 3000
TIMEOUT = 20.0

# Сторонние модули, которые есть в APK (см. buildozer.spec -> requirements).
BUNDLED_THIRD_PARTY = {
    "certifi", "httpx", "httpcore", "h11", "h2", "hpack", "hyperframe", "anyio",
    "sniffio", "idna", "typing_extensions", "cryptography", "proxy",
}


class UpdateError(Exception):
    """Ошибка обновления с кодом для локализации (code) и подробностью (detail)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# -------------------------------------------------------------------- версии

def parse_version(s: str) -> tuple:
    parts = []
    for part in (s or "").strip().lstrip("vV").split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def version_gt(a: str, b: str) -> bool:
    for x, y in zip_longest(parse_version(a), parse_version(b), fillvalue=0):
        if x != y:
            return x > y
    return False


def local_version() -> str:
    return core_loader.active_version()


def core_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "version": core_loader.active_version(),
        "source": core_loader.active_source(),
        "bundled_version": core_loader.bundled_version(),
        "has_backup": core_loader.has_backup(),
        "can_rollback": core_loader.has_downloaded_core(),
    }
    meta = paths.read_json(os.path.join(paths.core_current(), "version.json"), None)
    if isinstance(meta, dict):
        info["tag"] = meta.get("tag")
        info["downloaded_at"] = meta.get("downloaded_at")
    if core_loader.has_backup():
        bmeta = paths.read_json(os.path.join(paths.core_backup(), "version.json"), None)
        info["backup_version"] = core_loader.read_version(
            os.path.join(paths.core_backup(), "proxy"))
        info["backup_tag"] = bmeta.get("tag") if isinstance(bmeta, dict) else None
    return info


# ----------------------------------------------------------------- сеть

class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise UpdateError("insecure_redirect", newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl_context() -> ssl.SSLContext:
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _open(url: str, accept: str = "*/*", timeout: float = TIMEOUT):
    """Единственная точка сетевого доступа (в тестах подменяется)."""
    if urlparse(url).scheme != "https":
        raise UpdateError("insecure_url", url)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=_ssl_context()),
        _HttpsOnlyRedirect())
    req = urllib.request.Request(url, headers={
        "User-Agent": "tg-ws-proxy-launcher", "Accept": accept})
    return opener.open(req, timeout=timeout)


def check_latest() -> Dict[str, Any]:
    """Запросить последний релиз. -> dict(tag, changelog, newer, html_url, local)."""
    try:
        with _open(API_LATEST, "application/vnd.github+json") as resp:
            data = json.load(resp)
    except UpdateError:
        raise
    except urllib.error.HTTPError as exc:
        raise UpdateError("github_http", str(exc.code)) from exc
    except Exception as exc:                       # noqa: BLE001
        raise UpdateError("github_unreachable", repr(exc)) from exc
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise UpdateError("github_bad_response")
    if not all(c.isalnum() or c in "._-" for c in tag):
        raise UpdateError("github_bad_response", "tag")
    local = local_version()
    return {
        "tag": tag,
        "changelog": str(data.get("body") or ""),
        "html_url": data.get("html_url") or "",
        "local": local,
        "newer": version_gt(tag, local),
    }


def _download(url: str, dest: str, progress: Optional[Callable[[float], None]]) -> None:
    try:
        with _open(url, "application/zip", timeout=30) as resp:
            length = resp.headers.get("Content-Length")
            if length and int(length) > MAX_ZIP_BYTES:
                raise UpdateError("too_big", length)
            total = int(length) if length else 0
            got = 0
            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_ZIP_BYTES:
                        raise UpdateError("too_big", str(got))
                    fh.write(chunk)
                    if progress and total:
                        progress(min(0.6, 0.6 * got / total))
    except UpdateError:
        raise
    except urllib.error.HTTPError as exc:
        raise UpdateError("github_http", str(exc.code)) from exc
    except Exception as exc:                       # noqa: BLE001
        raise UpdateError("github_unreachable", repr(exc)) from exc


# ------------------------------------------------------ распаковка/проверка

def _safe_extract_proxy(zip_path: str, dest_dir: str) -> str:
    """Распаковать только <root>/proxy/** в dest_dir/proxy. Вернуть путь к proxy/."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UpdateError("bad_zip", str(exc)) from exc
    with zf:
        bad = zf.testzip()
        if bad:
            raise UpdateError("bad_zip", f"CRC: {bad}")
        infos = zf.infolist()
        if len(infos) > MAX_FILES:
            raise UpdateError("bad_zip", "слишком много файлов")
        if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise UpdateError("too_big", "распакованный размер")

        root = None
        for info in infos:
            parts = info.filename.split("/")
            if len(parts) == 3 and parts[1] == "proxy" and parts[2] == "__init__.py":
                root = parts[0]
                break
        if root is None:
            raise UpdateError("no_proxy_pkg")

        target_root = os.path.realpath(os.path.join(dest_dir, "proxy"))
        os.makedirs(target_root, exist_ok=True)
        prefix = root + "/proxy/"
        extracted = 0
        for info in infos:
            name = info.filename
            if not name.startswith(prefix):
                continue
            rel = name[len(prefix):]
            if not rel:
                continue
            # защита от path traversal / абсолютных путей / симлинков
            if (".." in rel.split("/") or rel.startswith("/") or "\\" in rel
                    or ":" in rel.split("/")[0]):
                raise UpdateError("unsafe_zip", name)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError("unsafe_zip", f"symlink {name}")
            out = os.path.realpath(os.path.join(target_root, rel))
            if out != target_root and not out.startswith(target_root + os.sep):
                raise UpdateError("unsafe_zip", name)
            if info.is_dir():
                os.makedirs(out, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted += 1
        if not extracted:
            raise UpdateError("no_proxy_pkg")
    return target_root


def _stdlib_names() -> set:
    names = set(getattr(sys, "stdlib_module_names", ()))
    if not names:       # Python < 3.10
        names = {"__future__", "argparse", "asyncio", "base64", "collections",
                 "contextlib", "ctypes", "dataclasses", "functools", "hashlib",
                 "hmac", "http", "itertools", "json", "logging", "os", "random",
                 "re", "signal", "socket", "ssl", "string", "struct", "sys",
                 "threading", "time", "typing", "urllib", "zlib", "errno",
                 "ipaddress", "select", "selectors", "traceback", "weakref"}
    return names


def _module_level_imports(tree: ast.AST) -> List[str]:
    """Абсолютные импорты на уровне модуля (вкл. try/if, без тел функций)."""
    found: List[str] = []

    def visit(nodes):
        for node in nodes:
            if isinstance(node, ast.Import):
                found.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.append(node.module.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef, ast.Lambda)):
                continue
            else:
                for field in ("body", "orelse", "finalbody", "handlers"):
                    child = getattr(node, field, None)
                    if isinstance(child, list):
                        visit(child)

    visit(getattr(tree, "body", []))
    return found


def validate_core(proxy_dir: str) -> str:
    """Проверить распакованный proxy/. Вернуть версию. Бросает UpdateError."""
    version = core_loader.read_version(proxy_dir)
    if not version:
        raise UpdateError("bad_version")
    stdlib = _stdlib_names()
    missing: set = set()
    for dirpath, _dirs, files in os.walk(proxy_dir):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), full)
            except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
                raise UpdateError("bad_source", f"{fn}: {exc}") from exc
            for mod in _module_level_imports(tree):
                if mod not in stdlib and mod not in BUNDLED_THIRD_PARTY:
                    missing.add(mod)
    if missing:
        raise UpdateError("needs_new_deps", ", ".join(sorted(missing)))
    return version


# -------------------------------------------------------------- применение

def apply_zip(zip_path: str, tag: str, progress: Optional[Callable[[float], None]] = None,
              source: str = "github") -> str:
    """Распаковать, проверить и атомарно активировать ядро из zip."""
    cache = paths.cache_dir()
    staging = os.path.join(cache, "update_extracted")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    try:
        proxy_dir = _safe_extract_proxy(zip_path, os.path.join(staging, "new"))
        if progress:
            progress(0.75)
        version = validate_core(proxy_dir)
        if progress:
            progress(0.85)

        new_dir = os.path.join(staging, "new")
        paths.write_json_atomic(os.path.join(new_dir, "version.json"), {
            "tag": tag,
            "version": version,
            "source": source,
            "downloaded_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

        cur, bak = paths.core_current(), paths.core_backup()
        shutil.rmtree(bak, ignore_errors=True)
        had_current = os.path.isdir(cur)
        try:
            if had_current:
                os.replace(cur, bak)
            os.replace(new_dir, cur)
        except OSError as exc:
            # вернуть как было
            if had_current and os.path.isdir(bak) and not os.path.isdir(cur):
                os.replace(bak, cur)
            raise UpdateError("apply_failed", repr(exc)) from exc
        if progress:
            progress(1.0)
        return version
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def download_and_apply(tag: str, progress: Optional[Callable[[float], None]] = None) -> str:
    """Скачать архив релиза и применить. Вернуть установленную версию."""
    if not all(c.isalnum() or c in "._-" for c in tag):
        raise UpdateError("github_bad_response", "tag")
    zip_path = os.path.join(paths.cache_dir(), "update.zip")
    paths.remove_quiet(zip_path)
    try:
        _download(ARCHIVE_URL.format(tag=tag), zip_path, progress)
        version = apply_zip(zip_path, tag, progress)
    finally:
        paths.remove_quiet(zip_path)
    log.info("Ядро обновлено до %s (%s)", version, tag)
    return version


def rollback_manual() -> bool:
    """Откат из UI: backup/ -> current/ (или возврат к встроенному ядру)."""
    ok = core_loader.rollback("ручной откат")
    if ok:
        log.info("Ручной откат выполнен, активна версия %s", core_loader.active_version())
    return ok
