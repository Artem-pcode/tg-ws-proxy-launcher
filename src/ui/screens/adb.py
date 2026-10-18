"""Вкладка «ADB»: краткий гайд по отключению убийства фоновых процессов + проверка статуса."""
from __future__ import annotations

from kivy.clock import Clock
from kivy.metrics import dp, sp

from ...core import android_utils as au, bg_status
from ...core.i18n import tr
from ..theme import Theme
from ..widgets import AppButton, Card, SectionTitle, Toast, WrapLabel
from .base import BaseScreen

_PKG_FALLBACK = "org.tgwsproxy.tgwsproxy"


def _copy(text: str) -> None:
    try:
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(text)
        Toast.show(tr("copied"))
    except Exception:                                  # noqa: BLE001
        pass


class AdbScreen(BaseScreen):
    def build(self):
        self._ev = None
        pkg = au.package_name() if au.available() else _PKG_FALLBACK
        self.cmds = bg_status.commands(pkg)

        guide = Card()
        guide.add_widget(SectionTitle(tr("adb_title")))
        guide.add_widget(WrapLabel(text=tr("adb_intro"), font_size=sp(14)))
        guide.add_widget(WrapLabel(text=tr("adb_need"), color=Theme.get("muted"), font_size=sp(13)))
        self.body.add_widget(guide)

        cmd_card = Card()
        cmd_card.add_widget(WrapLabel(text=tr("adb_steps"), font_size=sp(14)))
        for i, c in enumerate(self.cmds, 1):
            cmd_card.add_widget(WrapLabel(text=f"{i}. {c}", font_size=sp(12),
                                          font_name="RobotoMono-Regular"))
            cmd_card.add_widget(AppButton(text=tr("btn_copy") + f" {i}", kind="secondary",
                                          height=dp(36), on_press_cb=lambda c=c: _copy(c)))
        cmd_card.add_widget(AppButton(text=tr("btn_copy_all"),
                                      on_press_cb=lambda: _copy("\n".join(self.cmds))))
        cmd_card.add_widget(WrapLabel(text=tr("adb_after"), color=Theme.get("muted"), font_size=sp(12)))
        self.body.add_widget(cmd_card)

        st = Card()
        st.add_widget(SectionTitle(tr("adb_status")))
        self.status_lbl = WrapLabel(text="…", font_size=sp(16), bold=True)
        self.detail_lbl = WrapLabel(text="", color=Theme.get("muted"), font_size=sp(13))
        st.add_widget(self.status_lbl)
        st.add_widget(self.detail_lbl)
        st.add_widget(AppButton(text=tr("btn_recheck"), kind="secondary", on_press_cb=self.refresh))
        self.body.add_widget(st)

    def on_show(self):
        self.refresh()
        self._ev = Clock.schedule_interval(lambda dt: self.refresh(), 5.0)

    def on_hide(self):
        if self._ev:
            self._ev.cancel()
            self._ev = None

    def refresh(self):
        # jnius/Settings читаем в главном потоке (классы платформы, быстро)
        try:
            res = bg_status.check()
        except Exception:                              # noqa: BLE001
            res = {"overall": "unknown", "monitor": bg_status.UNKNOWN, "max": bg_status.UNKNOWN}
        overall = res["overall"]
        self.status_lbl.text = tr("adb_s_" + overall)
        color = {"applied": "ok", "not_needed": "ok", "not_applied": "danger"}.get(overall, "warn")
        self.status_lbl.color = Theme.get(color)
        if overall == "not_needed":
            self.detail_lbl.text = ""
        else:
            self.detail_lbl.text = (
                f"{tr('adb_i_monitor')}: {tr('adb_v_' + res['monitor'])}\n"
                f"{tr('adb_i_max')}: {tr('adb_v_' + res['max'])}")
