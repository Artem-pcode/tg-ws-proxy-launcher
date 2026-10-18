"""Экран «Логи»: просмотр хвоста proxy.log, поделиться, очистить."""
from __future__ import annotations

import os

from kivy.metrics import dp, sp

from ...core import android_utils as au
from ...core import paths
from ...core.i18n import tr
from ..theme import Theme
from ..widgets import AppButton, Card, SectionTitle, Toast, WrapLabel
from .base import BaseScreen

TAIL_BYTES = 24 * 1024          # показываем в приложении
SHARE_BYTES = 120 * 1024        # отправляем наружу (лимит Intent ~500 КБ)


def read_tail(limit: int, path: str = "") -> str:
    path = path or paths.log_path()
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
                fh.readline()                      # отбросить обрезанную строку
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


class LogsScreen(BaseScreen):
    def build(self):
        card = Card()
        card.add_widget(SectionTitle(tr("logs_title")))
        self.text_lbl = WrapLabel(text="", font_name="RobotoMono-Regular", font_size=sp(11),
                                  color=Theme.get("muted"))
        card.add_widget(self.text_lbl)
        self.body.add_widget(card)
        card2 = Card()
        card2.add_widget(SectionTitle(tr("launcher_log_title")))
        self.launcher_lbl = WrapLabel(text="", font_name="RobotoMono-Regular", font_size=sp(11),
                                      color=Theme.get("muted"))
        card2.add_widget(self.launcher_lbl)
        self.body.add_widget(card2)
        btns = Card()
        btns.add_widget(AppButton(text=tr("btn_refresh"), on_press_cb=self.refresh))
        btns.add_widget(AppButton(text=tr("btn_share_log"), kind="secondary", on_press_cb=self._share))
        btns.add_widget(AppButton(text=tr("btn_clear_log"), kind="secondary", on_press_cb=self._clear))
        self.body.add_widget(btns)

    def on_show(self):
        self.refresh()

    def refresh(self):
        text = read_tail(TAIL_BYTES)
        self.text_lbl.text = text.strip() or tr("log_empty")
        self.launcher_lbl.text = read_tail(8 * 1024, paths.launcher_log_path()).strip() or tr("log_empty")

    def _share(self):
        text = read_tail(SHARE_BYTES)
        extra = read_tail(16 * 1024, paths.launcher_log_path()).strip()
        if extra:
            text += "\n\n===== launcher.log =====\n" + extra
        if not text.strip():
            Toast.show(tr("log_empty"))
            return
        au.share_text(text, tr("log_share_title"))

    def _clear(self):
        try:
            with open(paths.log_path(), "w", encoding="utf-8"):
                pass
        except OSError:
            pass
        self.refresh()
        Toast.show(tr("log_cleared"))
