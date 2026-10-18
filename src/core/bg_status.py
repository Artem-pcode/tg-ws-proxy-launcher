"""Проверка, отключён ли «убийца фоновых (phantom) процессов» Android 12+.

Применяется командами ADB (см. вкладку ADB). Читаем:
  * Settings.Global `settings_enable_monitor_phantom_procs` - читается любым приложением;
  * DeviceConfig activity_manager/max_phantom_processes - нужен READ_DEVICE_CONFIG,
    выдаваемый командой `pm grant` (без него честно говорим «не удалось проверить»).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from . import android_utils as au, paths

log = logging.getLogger("tgwsp.bg")

OK, NO, UNKNOWN, NA = "ok", "no", "unknown", "na"
BIG_LIMIT = 1000                 # по умолчанию система держит 32

MONITOR_KEY = "settings_enable_monitor_phantom_procs"


def commands(package: str) -> List[str]:
    return [
        'adb shell "settings put global %s false"' % MONITOR_KEY,
        'adb shell "device_config set_sync_disabled_for_tests persistent"',
        'adb shell "device_config put activity_manager max_phantom_processes 2147483647"',
        "adb shell pm grant %s android.permission.READ_DEVICE_CONFIG" % package,
    ]


def evaluate(sdk: int, monitor: Optional[str], max_phantom: Optional[str],
             max_readable: bool) -> Dict[str, str]:
    """Чистая логика -> {'monitor','max','overall'}; overall: not_needed/applied/partial/not_applied."""
    if sdk and sdk < 31:
        return {"monitor": NA, "max": NA, "overall": "not_needed"}
    # ключ monitor есть только с Android 12L (API 32+)
    if sdk and sdk < 32:
        mon = NA
    else:
        mon = OK if str(monitor).strip().lower() == "false" else NO
    if not max_readable:
        mx = UNKNOWN
    else:
        try:
            mx = OK if int(str(max_phantom).strip()) >= BIG_LIMIT else NO
        except (TypeError, ValueError):
            mx = NO
    good = {OK}
    if mon == NA:
        overall = "applied" if mx == OK else ("not_applied" if mx == NO else "unknown")
    elif mon in good and mx in (OK, UNKNOWN):
        overall = "applied"
    elif mon in good or mx == OK:
        overall = "partial"
    else:
        overall = "not_applied"
    return {"monitor": mon, "max": mx, "overall": overall}


def read_raw() -> Dict[str, object]:
    """Прочитать значения на устройстве (jnius). Вне Android -> пусто."""
    out: Dict[str, object] = {"monitor": None, "max": None, "max_readable": False}
    if not au.available():
        return out
    from jnius import autoclass  # type: ignore
    try:
        G = autoclass("android.provider.Settings$Global")
        out["monitor"] = G.getString(au.activity().getContentResolver(), MONITOR_KEY)
    except Exception:                                  # noqa: BLE001
        log.exception("read monitor flag")
    try:
        DC = autoclass("android.provider.DeviceConfig")
        out["max"] = DC.getProperty("activity_manager", "max_phantom_processes")
        out["max_readable"] = True
    except Exception:                                  # noqa: BLE001
        log.info("DeviceConfig недоступен (нет READ_DEVICE_CONFIG)")
    return out


def check() -> Dict[str, str]:
    raw = read_raw()
    return evaluate(au.sdk_int(), raw["monitor"], raw["max"], bool(raw["max_readable"]))  # type: ignore[arg-type]
