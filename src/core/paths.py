"""Пути и атомарные операции с файлами обмена между UI и сервисом.

Модуль не импортирует Kivy и не знает про UI - его используют оба процесса.

Файлы обмена лежат во внутреннем хранилище приложения (files/tgwsproxy/proxy).
Это надёжнее внешнего каталога: не нужны разрешения, нет проблем со scoped
storage, а оба процесса (UI и service) принадлежат одному UID.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any

SHORTCUT_ACTION_SUFFIX = "LAUNCH_FROM_SHORTCUT"


def is_android() -> bool:
    return bool(os.environ.get("ANDROID_ARGUMENT")
                or os.environ.get("ANDROID_PRIVATE"))


def data_dir() -> str:
    override = os.environ.get("TGWSP_HOME")
    if override:
        base = override
    elif os.environ.get("ANDROID_PRIVATE"):
        base = os.path.join(os.environ["ANDROID_PRIVATE"], "tgwsproxy")
    else:
        try:
            from android.storage import app_storage_path  # type: ignore
            base = os.path.join(app_storage_path(), "tgwsproxy")
        except Exception:
            base = os.path.join(os.path.expanduser("~"), ".tg-ws-proxy-launcher")
    os.makedirs(base, exist_ok=True)
    return base


def exchange_dir() -> str:
    d = os.path.join(data_dir(), "proxy")
    os.makedirs(d, exist_ok=True)
    return d


def exchange_path(name: str) -> str:
    return os.path.join(exchange_dir(), name)


CONFIG_FILE = "config.json"
STATUS_FILE = "status.json"
STOP_SIGNAL = "stop.signal"
RELOAD_SIGNAL = "reload.signal"
RESUME_SIGNAL = "resume.signal"
LAUNCHER_LOG_FILE = "launcher.log"
LOG_FILE = "proxy.log"


def config_path() -> str:
    return exchange_path(CONFIG_FILE)


def status_path() -> str:
    return exchange_path(STATUS_FILE)


def stop_signal_path() -> str:
    return exchange_path(STOP_SIGNAL)


def reload_signal_path() -> str:
    return exchange_path(RELOAD_SIGNAL)


def resume_signal_path() -> str:
    return exchange_path(RESUME_SIGNAL)


def launcher_log_path() -> str:
    return exchange_path(LAUNCHER_LOG_FILE)


def log_path() -> str:
    return exchange_path(LOG_FILE)


def core_root() -> str:
    d = os.path.join(data_dir(), "proxy_core")
    os.makedirs(d, exist_ok=True)
    return d


def core_current() -> str:
    return os.path.join(core_root(), "current")


def core_backup() -> str:
    return os.path.join(core_root(), "backup")


def cache_dir() -> str:
    d = os.path.join(data_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def app_dir() -> str:
    """Каталог приложения (тот, где лежат main.py и src/)."""
    here = os.path.dirname(os.path.abspath(__file__))          # .../src/core
    candidate = os.path.dirname(os.path.dirname(here))          # .../
    if os.path.isdir(os.path.join(candidate, "src", "proxy")):
        return candidate
    for env in ("ANDROID_APP_PATH", "ANDROID_ARGUMENT"):
        p = os.environ.get(env)
        if p and os.path.isdir(os.path.join(p, "src", "proxy")):
            return p
    return candidate


def bundled_src_dir() -> str:
    return os.path.join(app_dir(), "src")


def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json_atomic(path: str, obj: Any) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def touch(path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(os.getpid()))


def remove_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
