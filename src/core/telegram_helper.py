"""Telegram: поиск установленного клиента, tg://proxy, запуск."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import android_utils as au
from . import config_store

log = logging.getLogger("tgwsp.telegram")

# (пакет, название) - порядок = приоритет при автоопределении
KNOWN_PACKAGES = [
    ("org.telegram.messenger", "Telegram"),
    ("org.telegram.messenger.web", "Telegram (web / APK)"),
    ("org.thunderdog.challegram", "Telegram X"),
    ("org.telegram.plus", "Plus Messenger"),
    ("nekox.messenger", "NekoX"),
    ("tw.nekomimi.nekogram", "Nekogram"),
    ("org.forkclient.messenger", "Forkgram"),
]


def installed() -> List[tuple]:
    return [(p, n) for p, n in KNOWN_PACKAGES if au.is_package_installed(p)]


def resolve_package(cfg: Dict[str, Any]) -> Optional[str]:
    """Пакет из настройки (если установлен) либо первый найденный."""
    wanted = cfg.get("telegram_package", "auto")
    if wanted and wanted != "auto" and au.is_package_installed(wanted):
        return wanted
    found = installed()
    return found[0][0] if found else None


def open_proxy_link(cfg: Dict[str, Any]) -> bool:
    """Открыть tg://proxy?... - Telegram предложит добавить прокси."""
    uri = config_store.build_tg_uri(cfg)
    pkg = resolve_package(cfg)
    return au.view_uri(uri, package=pkg)


def launch(cfg: Dict[str, Any]) -> bool:
    pkg = resolve_package(cfg)
    if not pkg:
        return False
    return au.launch_package(pkg)


def open_store(package: str = "org.telegram.messenger") -> bool:
    if au.view_uri(f"market://details?id={package}"):
        return True
    return au.view_uri(f"https://play.google.com/store/apps/details?id={package}")


def open_download_page() -> bool:
    return au.view_uri("https://telegram.org/android")
