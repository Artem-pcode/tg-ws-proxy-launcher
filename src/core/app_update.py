"""Обновление самого приложения со страницы релизов GitHub (APK).

Без Kivy. Сеть - через update_manager._open (только HTTPS, подменяется в тестах).
Установка - системным установщиком пакетов (см. java/.../ApkInstaller.java);
APK должен быть подписан тем же ключом, что и установленное приложение.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import zipfile
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from . import paths, update_manager as um
from .update_manager import UpdateError, version_gt

log = logging.getLogger("tgwsp.appupdate")

REPO = "Artem-pcode/tg-ws-proxy-launcher"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
MAX_APK_BYTES = 150 * 1024 * 1024


def local_version() -> str:
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "APP_VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "0"
    except OSError:
        return "0"


def update_dir() -> str:
    d = os.path.join(paths.data_dir(), "app_update")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_name(name: str) -> bool:
    return bool(name) and name.lower().endswith(".apk") and "/" not in name and "\\" not in name \
        and ".." not in name and all(c.isalnum() or c in "._-" for c in name)


def pick_apk(assets) -> Optional[Dict[str, Any]]:
    """Выбрать APK-ассет релиза (с безопасным именем и адресом из нашего репозитория)."""
    for a in assets or []:
        name = str(a.get("name") or "")
        url = str(a.get("browser_download_url") or "")
        if _safe_name(name) and url.startswith(DOWNLOAD_PREFIX):
            return {"name": name, "url": url, "size": int(a.get("size") or 0)}
    return None


def check_latest() -> Dict[str, Any]:
    """-> dict(tag, local, newer, notes, html_url, apk_name, apk_url, apk_size)."""
    try:
        with um._open(API_LATEST, "application/vnd.github+json") as resp:
            data = json.load(resp)
    except UpdateError:
        raise
    except urllib.error.HTTPError as exc:
        raise UpdateError("github_http", str(exc.code)) from exc
    except Exception as exc:                       # noqa: BLE001
        raise UpdateError("github_unreachable", repr(exc)) from exc
    tag = str(data.get("tag_name") or "").strip()
    if not tag or not all(c.isalnum() or c in "._-" for c in tag):
        raise UpdateError("github_bad_response", "tag")
    apk = pick_apk(data.get("assets"))
    local = local_version()
    return {
        "tag": tag, "local": local, "newer": version_gt(tag, local),
        "notes": str(data.get("body") or ""),
        "html_url": str(data.get("html_url") or RELEASES_URL),
        "apk_name": apk["name"] if apk else "", "apk_url": apk["url"] if apk else "",
        "apk_size": apk["size"] if apk else 0,
    }


def _check_apk_file(path: str, expected_size: int) -> None:
    size = os.path.getsize(path)
    if expected_size and size != expected_size:
        raise UpdateError("apk_bad", f"size {size} != {expected_size}")
    try:
        with zipfile.ZipFile(path) as zf:
            if "AndroidManifest.xml" not in zf.namelist():
                raise UpdateError("apk_bad", "no AndroidManifest.xml")
    except zipfile.BadZipFile as exc:
        raise UpdateError("apk_bad", str(exc)) from exc


def download(info: Dict[str, Any], progress: Optional[Callable[[float], None]] = None) -> str:
    """Скачать APK во внутреннюю папку приложения -> имя файла."""
    name, url = info.get("apk_name", ""), info.get("apk_url", "")
    if not _safe_name(name) or not url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError("no_apk")
    d = update_dir()
    for old in os.listdir(d):                      # чистим прошлые загрузки
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    dest, tmp = os.path.join(d, name), os.path.join(d, name + ".part")
    try:
        with um._open(url, "application/vnd.android.package-archive", timeout=30) as resp:
            length = resp.headers.get("Content-Length")
            total = int(length) if length else int(info.get("apk_size") or 0)
            if total > MAX_APK_BYTES:
                raise UpdateError("too_big", str(total))
            got = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_APK_BYTES:
                        raise UpdateError("too_big", str(got))
                    fh.write(chunk)
                    if progress and total:
                        progress(min(1.0, got / total))
        _check_apk_file(tmp, int(info.get("apk_size") or 0))
        os.replace(tmp, dest)
    except UpdateError:
        _rm(tmp)
        raise
    except urllib.error.HTTPError as exc:
        _rm(tmp)
        raise UpdateError("github_http", str(exc.code)) from exc
    except Exception as exc:                       # noqa: BLE001
        _rm(tmp)
        raise UpdateError("github_unreachable", repr(exc)) from exc
    return name


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
