"""Чтение status.json, который пишет сервис (сторона UI)."""
from __future__ import annotations

import time
from typing import Any, Dict

from . import paths

# Статус считается "живым", если сервис обновлял файл не позже N секунд назад.
STALE_AFTER = 5.0

STOPPED, STARTING, RUNNING, ERROR, PAUSED = "stopped", "starting", "running", "error", "paused"
LIVE_STATES = (STARTING, RUNNING, PAUSED)


def read() -> Dict[str, Any]:
    """Вернуть статус с вычисленным полем `state` (с учётом протухания файла)."""
    data = paths.read_json(paths.status_path(), None)
    if not isinstance(data, dict):
        return {"state": STOPPED, "alive": False}
    state = data.get("state", STOPPED)
    age = time.time() - float(data.get("updated", 0) or 0)
    alive = state in LIVE_STATES and age <= STALE_AFTER
    if state in LIVE_STATES and not alive:
        # сервис не отвечает (убит системой / упал без записи статуса)
        data = dict(data)
        data["state"] = STOPPED
        data["note"] = data.get("note") or "stale"
        state = STOPPED
    data = dict(data)
    data["alive"] = alive
    data["state"] = state
    return data


def is_running() -> bool:
    return read().get("state") == RUNNING


def is_alive() -> bool:
    return bool(read().get("alive"))
