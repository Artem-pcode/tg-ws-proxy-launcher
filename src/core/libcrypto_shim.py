"""Подсказка для _aes.py: где искать libcrypto на Android.

Ядро использует `cryptography`, а при её отсутствии - ctypes-обёртку над
libcrypto (proxy/_aes.py). В APK мы не тянем `cryptography` (на Android её
сборка требует Rust и часто ломается), поэтому используем fallback ядра.
Но ядро ищет библиотеки по именам libcrypto.so.3 / libcrypto.so.1.1, а
python-for-android кладёт OpenSSL в APK под другими именами
(libcrypto1.1.so, libcrypto3.so).

libcrypto уже загружена в процесс вместе с модулем ssl, поэтому находим её
путь в /proc/self/maps и подменяем ctypes.util.find_library("crypto").
Ядро при этом не модифицируется - обновления с GitHub продолжают работать.
"""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger("tgwsp.libcrypto")


def _find_loaded_libcrypto() -> str | None:
    candidates: list[str] = []
    try:
        with open("/proc/self/maps", "r") as fh:
            for line in fh:
                m = re.search(r"(/\S*libcrypto[^\s/]*\.so[^\s/]*)\s*$", line)
                if m and m.group(1) not in candidates:
                    candidates.append(m.group(1))
    except OSError:
        return None
    # предпочитаем библиотеку из каталога приложения, а не системную
    for path in candidates:
        if path.startswith("/data/") and os.path.exists(path):
            return path
    for path in candidates:
        if os.path.exists(path):
            return path
    # библиотека смонтирована прямо из APK (путь вида base.apk!/lib/...) - она уже
    # загружена в процесс, dlopen найдёт её по короткому имени
    for path in candidates:
        if not path.startswith(("/system/", "/apex/", "/vendor/")):
            return os.path.basename(path)
    return None


def install() -> str | None:
    """Вызывать ДО импорта пакета proxy. Безопасно на любой платформе."""
    try:
        import cryptography  # noqa: F401
        return None            # настоящая cryptography доступна - ничего не делаем
    except ImportError:
        pass
    try:
        import ssl  # noqa: F401  (гарантирует загрузку libcrypto в процесс)
    except ImportError:
        pass
    path = _find_loaded_libcrypto()
    if not path:
        log.warning("libcrypto не найдена в /proc/self/maps")
        return None
    import ctypes.util
    original = ctypes.util.find_library

    def patched(name):
        if name == "crypto":
            return path
        return original(name)

    ctypes.util.find_library = patched
    log.info("libcrypto для AES: %s", path)
    return path
