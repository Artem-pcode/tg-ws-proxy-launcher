"""Выбор и подключение прокси-ядра: загруженное с GitHub или встроенное в APK.

Используется сервисом (подключение/откат) и менеджером обновлений.
Без зависимостей от Kivy.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import shutil
import sys
from typing import Optional

from . import paths

log = logging.getLogger("tgwsp.core_loader")

_VERSION_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")


def read_version(proxy_pkg_dir: str) -> Optional[str]:
    """Прочитать __version__ из <dir>/__init__.py, не импортируя модуль."""
    try:
        with open(os.path.join(proxy_pkg_dir, "__init__.py"), "r",
                  encoding="utf-8") as fh:
            m = _VERSION_RE.search(fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


def current_proxy_dir() -> str:
    return os.path.join(paths.core_current(), "proxy")


def bundled_proxy_dir() -> str:
    return os.path.join(paths.bundled_src_dir(), "proxy")


def has_downloaded_core() -> bool:
    return os.path.isfile(os.path.join(current_proxy_dir(), "__init__.py"))


def has_backup() -> bool:
    return os.path.isfile(os.path.join(paths.core_backup(), "proxy", "__init__.py"))


def bundled_version() -> str:
    """Версия встроенного ядра. Если .py недоступны (байткод-сборка) - из BUNDLED_CORE_VERSION."""
    v = read_version(bundled_proxy_dir())
    if v:
        return v
    try:
        with open(os.path.join(paths.bundled_src_dir(), "BUNDLED_CORE_VERSION"),
                  "r", encoding="utf-8") as fh:
            return fh.read().strip() or "?"
    except OSError:
        return "?"


def active_version() -> str:
    if has_downloaded_core():
        return read_version(current_proxy_dir()) or "?"
    return bundled_version()


def active_source() -> str:
    return "github" if has_downloaded_core() else "builtin"


def activate() -> str:
    """Расставить sys.path: current/ (если есть) раньше встроенной копии."""
    src = paths.bundled_src_dir()
    for p in list(sys.path):
        if p == paths.core_current():
            sys.path.remove(p)
    if src not in sys.path:
        sys.path.insert(0, src)
    if has_downloaded_core():
        sys.path.insert(0, paths.core_current())
        return "github"
    return "builtin"


def purge_modules() -> None:
    for name in list(sys.modules):
        if name == "proxy" or name.startswith("proxy."):
            del sys.modules[name]


def rollback(reason: str) -> bool:
    """current/ -> failed_<ts>/, backup/ -> current/.

    Если backup/ нет - просто убираем current/ (вернётся встроенное ядро).
    Возвращает True, если что-то было откачено.
    """
    cur, bak = paths.core_current(), paths.core_backup()
    if not os.path.isdir(cur):
        return False
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    failed = os.path.join(paths.core_root(), f"failed_{stamp}")
    log.error("Откат ядра (%s): %s -> %s", reason, cur, failed)
    try:
        os.replace(cur, failed)
    except OSError:
        shutil.rmtree(cur, ignore_errors=True)
    if os.path.isdir(bak):
        try:
            os.replace(bak, cur)
            log.warning("Восстановлено предыдущее ядро из backup/")
        except OSError as exc:
            log.error("Не удалось восстановить backup: %r", exc)
    else:
        log.warning("backup/ отсутствует - используется встроенное ядро")
    _prune_failed()
    return True


def _prune_failed(keep: int = 2) -> None:
    root = paths.core_root()
    try:
        items = sorted(d for d in os.listdir(root) if d.startswith("failed_"))
    except OSError:
        return
    for d in items[:-keep]:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
