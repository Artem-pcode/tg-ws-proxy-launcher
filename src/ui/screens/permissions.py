"""Экран «Система»: разрешения и оптимизация батареи."""
from __future__ import annotations

from kivy.clock import Clock
from kivy.metrics import dp, sp

from ...core import android_utils as au
from ...core.i18n import tr
from ..theme import Theme
from ..widgets import AppButton, Card, SectionTitle, WrapLabel
from .base import BaseScreen


class PermissionsScreen(BaseScreen):
    def build(self):
        self._ev = None
        card = Card()
        card.add_widget(SectionTitle(tr("sys_title")))
        card.add_widget(WrapLabel(text=tr("sys_hint"), color=Theme.get("muted"), font_size=sp(13)))
        self.body.add_widget(card)

        self.rows = {}
        rows = Card()
        for key in ("perm_internet", "perm_notifications", "perm_battery"):
            lbl = WrapLabel(text="", font_size=sp(15))
            self.rows[key] = lbl
            rows.add_widget(lbl)
        self.body.add_widget(rows)

        btns = Card()
        btns.add_widget(AppButton(text=tr("perm_notifications") + ": " + tr("btn_request"),
                                  kind="secondary", on_press_cb=self._req_notifications))
        btns.add_widget(AppButton(text=tr("btn_battery"), on_press_cb=au.request_ignore_battery_optimizations))
        btns.add_widget(AppButton(text=tr("btn_autostart"), kind="secondary",
                                  on_press_cb=au.open_autostart_settings))
        btns.add_widget(AppButton(text=tr("btn_app_settings"), kind="secondary",
                                  on_press_cb=au.open_app_settings))
        self.body.add_widget(btns)
        self.refresh()

    def on_show(self):
        self.refresh()
        # пользователь возвращается из системных настроек - обновляем статусы
        self._ev = Clock.schedule_interval(lambda dt: self.refresh(), 2.0)

    def on_hide(self):
        if self._ev:
            self._ev.cancel()
            self._ev = None

    def refresh(self):
        values = {
            "perm_internet": True,
            "perm_notifications": au.has_permission(au.POST_NOTIFICATIONS),
            "perm_battery": au.is_ignoring_battery_optimizations(),
        }
        for key, ok in values.items():
            lbl = self.rows[key]
            lbl.text = f"{tr(key)}: {tr('granted') if ok else tr('not_granted')}"
            lbl.color = Theme.get("ok") if ok else Theme.get("warn")

    def _req_notifications(self):
        au.request_permissions([au.POST_NOTIFICATIONS], lambda *a: self.refresh())
