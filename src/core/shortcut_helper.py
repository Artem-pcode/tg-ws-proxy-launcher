"""Ярлык на рабочем столе (pinned shortcut) через framework ShortcutManager.

minSdk = 26, поэтому androidx (ShortcutManagerCompat) не нужен.
Клик по ярлыку открывает PythonActivity с действием <package>.LAUNCH_FROM_SHORTCUT.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from . import android_utils as au
from . import paths

log = logging.getLogger("tgwsp.shortcut")

SHORTCUT_ID = "launch_proxy_tg"
PYTHON_ACTIVITY = "org.kivy.android.PythonActivity"


def action_name() -> str:
    return au.package_name() + "." + paths.SHORTCUT_ACTION_SUFFIX if au.available() \
        else paths.SHORTCUT_ACTION_SUFFIX


def is_shortcut_action(action: Optional[str]) -> bool:
    return bool(action) and str(action).endswith(paths.SHORTCUT_ACTION_SUFFIX)


def _manager():
    from jnius import autoclass, cast  # type: ignore
    Context = autoclass("android.content.Context")
    return cast("android.content.pm.ShortcutManager",
                au.activity().getSystemService(Context.SHORTCUT_SERVICE))


def is_supported() -> bool:
    if not au.available():
        return False
    try:
        return bool(_manager().isRequestPinShortcutSupported())
    except Exception:                                  # noqa: BLE001
        log.exception("isRequestPinShortcutSupported")
        return False


def _icon(icon_path: str):
    from jnius import autoclass  # type: ignore
    Icon = autoclass("android.graphics.drawable.Icon")
    if icon_path and os.path.isfile(icon_path):
        BitmapFactory = autoclass("android.graphics.BitmapFactory")
        bmp = BitmapFactory.decodeFile(icon_path)
        if bmp is not None:
            return Icon.createWithAdaptiveBitmap(bmp)
    ctx = au.activity()
    return Icon.createWithResource(ctx, ctx.getApplicationInfo().icon)


def create(short_label: str, long_label: str, icon_path: str) -> bool:
    """Запросить создание ярлыка (пользователь подтверждает сам)."""
    if not au.available():
        log.info("[desktop] create shortcut %r", short_label)
        return True
    try:
        from jnius import autoclass  # type: ignore
        ctx = au.activity()
        Intent = autoclass("android.content.Intent")
        intent = Intent()
        intent.setClassName(ctx.getPackageName(), PYTHON_ACTIVITY)
        intent.setAction(action_name())
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP)

        ShortcutInfoBuilder = autoclass("android.content.pm.ShortcutInfo$Builder")
        info = (ShortcutInfoBuilder(ctx, SHORTCUT_ID)
                .setShortLabel(short_label)
                .setLongLabel(long_label)
                .setIcon(_icon(icon_path))
                .setIntent(intent)
                .build())
        return bool(_manager().requestPinShortcut(info, None))
    except Exception:                                  # noqa: BLE001
        log.exception("requestPinShortcut")
        return False
