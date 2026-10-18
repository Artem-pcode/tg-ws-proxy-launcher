"""Светлая/тёмная темы (цвета RGBA в диапазоне 0..1)."""
from __future__ import annotations

from typing import Dict, Tuple

Color = Tuple[float, float, float, float]


def _hex(h: str, a: float = 1.0) -> Color:
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


DARK: Dict[str, Color] = {
    "bg": _hex("#14161a"), "surface": _hex("#1e2127"), "surface2": _hex("#272b33"),
    "text": _hex("#e8eaed"), "muted": _hex("#9aa0a6"),
    "primary": _hex("#4aa3ff"), "on_primary": _hex("#06121f"),
    "danger": _hex("#ff6b6b"), "ok": _hex("#4cd18a"), "warn": _hex("#ffb74d"),
    "border": _hex("#3a3f48"), "input_bg": _hex("#171a1f"),
}
LIGHT: Dict[str, Color] = {
    "bg": _hex("#f3f5f8"), "surface": _hex("#ffffff"), "surface2": _hex("#e9edf3"),
    "text": _hex("#1b1f24"), "muted": _hex("#5f6770"),
    "primary": _hex("#1769d6"), "on_primary": _hex("#ffffff"),
    "danger": _hex("#c62828"), "ok": _hex("#1b8f55"), "warn": _hex("#b76e00"),
    "border": _hex("#cfd6df"), "input_bg": _hex("#f7f9fc"),
}


class Theme:
    dark = True
    c: Dict[str, Color] = DARK

    @classmethod
    def set(cls, dark: bool) -> None:
        cls.dark = dark
        cls.c = DARK if dark else LIGHT

    @classmethod
    def get(cls, name: str) -> Color:
        return cls.c[name]


def state_color(state: str) -> Color:
    return {
        "running": Theme.get("ok"), "starting": Theme.get("warn"),
        "error": Theme.get("danger"),
    }.get(state, Theme.get("muted"))
