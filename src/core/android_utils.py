"""Тонкая обёртка над Android API через PyJNIus.

Все функции безопасны на десктопе (для отладки): там они пишут в лог и
возвращают нейтральные значения. jnius импортируется лениво.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from . import paths

log = logging.getLogger("tgwsp.android")

FLAG_ACTIVITY_NEW_TASK = 0x10000000

POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"

# (пакет, класс) - экраны автозапуска у разных производителей
AUTOSTART_INTENTS = [
    ("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),
    ("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
    ("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"),
    ("com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"),
    ("com.samsung.android.sm_cn", "com.samsung.android.sm.ui.ram.AutoRunActivity"),
    ("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
    ("com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"),
    ("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
    ("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"),
    ("com.asus.mobilemanager", "com.asus.mobilemanager.powersaver.PowerSaverSettings"),
    ("com.transsion.phonemaster", "com.cyin.himgr.autostart.AutoStartActivity"),
]


def available() -> bool:
    return paths.is_android()


def activity():
    from jnius import autoclass  # type: ignore
    return autoclass("org.kivy.android.PythonActivity").mActivity


def package_name() -> str:
    return activity().getPackageName()


def sdk_int() -> int:
    if not available():
        return 0
    from jnius import autoclass  # type: ignore
    return int(autoclass("android.os.Build$VERSION").SDK_INT)


def system_language() -> str:
    try:
        if available():
            from jnius import autoclass  # type: ignore
            return str(autoclass("java.util.Locale").getDefault().getLanguage())
        import locale
        return (locale.getdefaultlocale()[0] or "en")[:2]
    except Exception:                                  # noqa: BLE001
        return "en"


def is_night_mode() -> bool:
    if not available():
        return True
    try:
        ui_mode = activity().getResources().getConfiguration().uiMode
        return (int(ui_mode) & 0x30) == 0x20
    except Exception:                                  # noqa: BLE001
        return True


# ------------------------------------------------------------- разрешения

def has_permission(name: str) -> bool:
    if not available():
        return True
    if name == POST_NOTIFICATIONS and sdk_int() < 33:
        return True
    try:
        from android.permissions import check_permission  # type: ignore
        return bool(check_permission(name))
    except Exception:                                  # noqa: BLE001
        log.exception("check_permission")
        return False


def request_permissions(names: List[str],
                        callback: Optional[Callable] = None) -> None:
    if not available():
        return
    names = [n for n in names if not (n == POST_NOTIFICATIONS and sdk_int() < 33)]
    if not names:
        return
    try:
        from android.permissions import request_permissions as rp  # type: ignore
        rp(names, callback) if callback else rp(names)
    except Exception:                                  # noqa: BLE001
        log.exception("request_permissions")


# ----------------------------------------------------------------- intents

def _new_intent(action: Optional[str] = None):
    from jnius import autoclass  # type: ignore
    Intent = autoclass("android.content.Intent")
    return Intent(action) if action else Intent()


def view_uri(uri: str, package: Optional[str] = None) -> bool:
    if not available():
        log.info("[desktop] ACTION_VIEW %s (package=%s)", uri, package)
        return True
    try:
        from jnius import autoclass  # type: ignore
        Uri = autoclass("android.net.Uri")
        intent = _new_intent("android.intent.action.VIEW")
        intent.setData(Uri.parse(uri))
        if package:
            intent.setPackage(package)
        intent.addFlags(FLAG_ACTIVITY_NEW_TASK)
        activity().startActivity(intent)
        return True
    except Exception:                                  # noqa: BLE001
        log.exception("view_uri %s", uri)
        if package:                       # пакет мог не обработать ссылку
            return view_uri(uri, None)
        return False


def is_package_installed(package: str) -> bool:
    if not available():
        return False
    try:
        pm = activity().getPackageManager()
        return pm.getLaunchIntentForPackage(package) is not None
    except Exception:                                  # noqa: BLE001
        return False


def launch_package(package: str) -> bool:
    if not available():
        log.info("[desktop] launch %s", package)
        return True
    try:
        pm = activity().getPackageManager()
        intent = pm.getLaunchIntentForPackage(package)
        if intent is None:
            return False
        intent.addFlags(FLAG_ACTIVITY_NEW_TASK)
        activity().startActivity(intent)
        return True
    except Exception:                                  # noqa: BLE001
        log.exception("launch_package %s", package)
        return False


def share_text(text: str, title: str = "") -> bool:
    if not available():
        log.info("[desktop] share %d chars", len(text))
        return True
    try:
        from jnius import autoclass  # type: ignore
        Intent = autoclass("android.content.Intent")
        intent = _new_intent("android.intent.action.SEND")
        intent.setType("text/plain")
        intent.putExtra("android.intent.extra.TEXT", text)
        chooser = Intent.createChooser(intent, title or "Share")
        chooser.addFlags(FLAG_ACTIVITY_NEW_TASK)
        activity().startActivity(chooser)
        return True
    except Exception:                                  # noqa: BLE001
        log.exception("share_text")
        return False


def open_app_settings() -> bool:
    if not available():
        return True
    try:
        from jnius import autoclass  # type: ignore
        Uri = autoclass("android.net.Uri")
        intent = _new_intent("android.settings.APPLICATION_DETAILS_SETTINGS")
        intent.setData(Uri.fromParts("package", package_name(), None))
        activity().startActivity(intent)
        return True
    except Exception:                                  # noqa: BLE001
        log.exception("open_app_settings")
        return False


# --------------------------------------------------------------- батарея

def is_ignoring_battery_optimizations() -> bool:
    if not available():
        return True
    try:
        from jnius import autoclass, cast  # type: ignore
        Context = autoclass("android.content.Context")
        pm = cast("android.os.PowerManager",
                  activity().getSystemService(Context.POWER_SERVICE))
        return bool(pm.isIgnoringBatteryOptimizations(package_name()))
    except Exception:                                  # noqa: BLE001
        log.exception("isIgnoringBatteryOptimizations")
        return False


def request_ignore_battery_optimizations() -> bool:
    if not available():
        return True
    try:
        from jnius import autoclass  # type: ignore
        Uri = autoclass("android.net.Uri")
        intent = _new_intent("android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS")
        intent.setData(Uri.parse("package:" + package_name()))
        activity().startActivity(intent)
        return True
    except Exception:                                  # noqa: BLE001
        log.exception("request_ignore_battery_optimizations")
        # запасной вариант - общий список оптимизации батареи
        try:
            activity().startActivity(
                _new_intent("android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS"))
            return True
        except Exception:                                  # noqa: BLE001
            return False


def open_autostart_settings() -> bool:
    """Попробовать экран автозапуска производителя (MIUI/EMUI/OneUI/...)."""
    if not available():
        return True
    from jnius import autoclass  # type: ignore
    ComponentName = autoclass("android.content.ComponentName")
    for pkg, cls in AUTOSTART_INTENTS:
        try:
            intent = _new_intent()
            intent.setComponent(ComponentName(pkg, cls))
            intent.addFlags(FLAG_ACTIVITY_NEW_TASK)
            activity().startActivity(intent)
            return True
        except Exception:                                  # noqa: BLE001
            continue
    return open_app_settings()


# ------------------------------------------------------------ окно/активити

def toast(text: str) -> None:
    if not available():
        log.info("[toast] %s", text)
        return
    try:
        from android.runnable import run_on_ui_thread  # type: ignore
        from jnius import autoclass  # type: ignore
        Toast = autoclass("android.widget.Toast")
        String = autoclass("java.lang.String")

        @run_on_ui_thread
        def _show():
            Toast.makeText(activity(), String(text), Toast.LENGTH_LONG).show()

        _show()
    except Exception:                                  # noqa: BLE001
        log.exception("toast")


def get_intent_action() -> str:
    if not available():
        return ""
    try:
        intent = activity().getIntent()
        return str(intent.getAction() or "") if intent is not None else ""
    except Exception:                                  # noqa: BLE001
        return ""


def clear_intent() -> None:
    """Заменить стартовый Intent на пустой, чтобы действие не повторилось."""
    if not available():
        return
    try:
        activity().setIntent(_new_intent("android.intent.action.MAIN"))
    except Exception:                                  # noqa: BLE001
        log.exception("clear_intent")


def finish_task() -> None:
    if not available():
        return
    try:
        activity().finishAndRemoveTask()
    except Exception:                                  # noqa: BLE001
        try:
            activity().finish()
        except Exception:                              # noqa: BLE001
            log.exception("finish")


def move_task_to_back() -> None:
    if not available():
        return
    try:
        activity().moveTaskToBack(True)
    except Exception:                                  # noqa: BLE001
        log.exception("moveTaskToBack")


# --------------------------------------------- доступ «Данные об использовании»

def has_usage_access() -> bool:
    if not available():
        return False
    from . import saver
    return saver.usage_access_granted(activity())


def open_usage_access_settings() -> bool:
    if not available():
        return True
    try:
        from jnius import autoclass  # type: ignore
        intent = _new_intent("android.settings.USAGE_ACCESS_SETTINGS")
        try:
            intent.setData(autoclass("android.net.Uri").parse("package:" + package_name()))
        except Exception:                              # noqa: BLE001
            pass
        intent.addFlags(FLAG_ACTIVITY_NEW_TASK)
        activity().startActivity(intent)
        return True
    except Exception:                                  # noqa: BLE001
        log.exception("open_usage_access_settings")
        return False


# ------------------------------------------------- плитка быстрых настроек

def request_add_tile() -> bool:
    """Android 13+: системный диалог добавления плитки. False - нужно добавить вручную.

    Вызывать из главного потока (класс приложения резолвится его ClassLoader'ом).
    """
    if not available() or sdk_int() < 33:
        return False
    try:
        from jnius import autoclass  # type: ignore
        helper = autoclass(package_name() + ".TileHelper")
        return bool(helper.requestAdd(activity()))
    except Exception:                                  # noqa: BLE001
        log.exception("request_add_tile")
        return False
