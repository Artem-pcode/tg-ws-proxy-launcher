"""Экран «Статус»: состояние, старт/стоп, статистика, Telegram, ярлык."""
from __future__ import annotations

import logging
import os
import threading

from kivy.clock import Clock, mainthread
from kivy.metrics import dp, sp

from ...core import (android_utils as au, config_store, service_controller,
                     shortcut_helper, status_reader, telegram_helper)
from ...core.i18n import tr
from ..theme import Theme, state_color
from ..widgets import (AppButton, Card, SectionTitle, Toast, WrapLabel,
                       message_dialog)
from .base import BaseScreen

log = logging.getLogger("tgwsp.ui.status")


def _hb(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class StatusScreen(BaseScreen):
    def build(self):
        self._busy = False
        self._event = None

        card = Card()
        self.state_lbl = WrapLabel(text="", font_size=sp(28), bold=True)
        self.detail_lbl = WrapLabel(text="", color=Theme.get("muted"), font_size=sp(13))
        self.paused_lbl = WrapLabel(text="", color=Theme.get("warn"), font_size=sp(13),
                                    collapse_empty=True)
        self.error_lbl = WrapLabel(text="", color=Theme.get("danger"), font_size=sp(14),
                                   collapse_empty=True)
        self.note_lbl = WrapLabel(text="", color=Theme.get("warn"), font_size=sp(13),
                                  collapse_empty=True)
        for w in (self.state_lbl, self.detail_lbl, self.paused_lbl, self.error_lbl, self.note_lbl):
            card.add_widget(w)
        self.body.add_widget(card)

        self.main_btn = AppButton(text=tr("btn_start"), on_press_cb=self._toggle, height=dp(56))
        self.restart_btn = AppButton(text=tr("btn_restart"), kind="secondary",
                                     on_press_cb=self._restart)
        self.body.add_widget(self.main_btn)
        self.body.add_widget(self.restart_btn)

        stats = Card()
        stats.add_widget(SectionTitle(tr("summary")))
        self.stats_lbl = WrapLabel(text="—", font_size=sp(14))
        stats.add_widget(self.stats_lbl)
        self.summary_lbl = WrapLabel(text="", color=Theme.get("muted"), font_size=sp(11),
                                     collapse_empty=True)
        stats.add_widget(self.summary_lbl)
        self.body.add_widget(stats)

        tg = Card()
        tg.add_widget(WrapLabel(text=tr("hint_tg_once"), color=Theme.get("muted"), font_size=sp(13)))
        tg.add_widget(AppButton(text=tr("btn_tg_setup"), on_press_cb=self._tg_setup))
        tg.add_widget(AppButton(text=tr("btn_shortcut"), kind="secondary", on_press_cb=self._shortcut))
        self.body.add_widget(tg)

        tile = Card()
        tile.add_widget(WrapLabel(text=tr("tile_hint"), color=Theme.get("muted"), font_size=sp(13)))
        tile.add_widget(AppButton(text=tr("btn_add_tile"), kind="secondary", on_press_cb=self._add_tile))
        self.body.add_widget(tile)
        self.refresh()

    # --- обновление раз в секунду, пока экран открыт
    def on_show(self):
        self.refresh()
        self._event = Clock.schedule_interval(lambda dt: self.refresh(), 1.0)

    def on_hide(self):
        if self._event:
            self._event.cancel()
            self._event = None

    def refresh(self):
        st = status_reader.read()
        state = st.get("state", "stopped")
        self.state_lbl.text = tr(f"state_{state}")
        self.state_lbl.color = state_color(state)

        cfg = self.app.cfg
        lines = [f"{tr('listen')}: {cfg.get('host')}:{cfg.get('port')}"]
        ver = st.get("core_version") or ""
        if ver:
            src = tr("core_src_github") if st.get("core_source") == "github" else tr("core_src_builtin")
            lines.append(f"{tr('core_ver')}: {ver} ({src})")
        self.detail_lbl.text = "\n".join(lines)

        self.error_lbl.text = self._error_text(st)
        self.note_lbl.text = tr("note_rolled_back") if st.get("note") == "rolled_back" else ""

        alive = bool(st.get("alive"))
        if self._busy:
            pass
        else:
            self.main_btn.text = tr("btn_stop") if alive else tr("btn_start")
            self.main_btn.kind = "danger" if alive else "primary"
        paused = state == "paused"
        self.paused_lbl.text = tr("paused_hint") if paused else ""
        self.restart_btn.text = tr("btn_resume") if paused else tr("btn_restart")
        self.restart_btn.enabled = alive and not self._busy
        self.restart_btn.opacity = 1 if alive else 0.4

        if alive or st.get("total"):
            self.stats_lbl.text = (
                f"{tr('active_conn')}: {st.get('active', 0)}\n"
                f"{tr('total_conn')}: {st.get('total', 0)}\n"
                f"{tr('traffic')}: up {_hb(st.get('bytes_up'))} / down {_hb(st.get('bytes_down'))}\n"
                f"{tr('errors')}: {st.get('ws_errors', 0)}"
                + (f"\n{tr('restarts')}: {st.get('restarts')}" if st.get("restarts") else ""))
            self.summary_lbl.text = st.get("summary", "")
        else:
            self.stats_lbl.text = "—"
            self.summary_lbl.text = ""

    @staticmethod
    def _error_text(st) -> str:
        err = str(st.get("error") or "")
        if not err or st.get("state") != "error":
            return ""
        code, _, detail = err.partition(":")
        if code == "port_busy":
            return tr("err_port_busy", port=detail)
        if code == "port_denied":
            return tr("err_port_denied", port=detail)
        if code == "crash_loop":
            return tr("err_crash_loop", detail=detail)
        return tr("err_generic", detail=err)

    # --- действия
    def _toggle(self):
        if self._busy:
            return
        if status_reader.is_alive():
            self._run_bg(tr("stopping_wait"), service_controller.stop)
        else:
            if config_store.validate(self.app.cfg):
                Toast.show(tr("err_start_invalid"))
                self.app.show_tab("settings")
                return
            self.app.ensure_first_run_permissions()
            self._run_bg(tr("starting_wait"), lambda: service_controller.start(self.app.cfg),
                         after=self._after_start)

    def _restart(self):
        if status_reader.read().get("state") == "paused":
            service_controller.resume()
            Toast.show(tr("starting_wait"))
            return
        if config_store.validate(self.app.cfg):
            Toast.show(tr("err_start_invalid"))
            return
        service_controller.restart(self.app.cfg)
        Toast.show(tr("starting_wait"))

    def _after_start(self, result):
        ok, reason = result if isinstance(result, tuple) else (True, "")
        if not ok:
            Toast.show(tr("err_start_invalid") if reason == "invalid_config"
                       else tr("err_start_failed"))

    def _run_bg(self, label, fn, after=None):
        self._busy = True
        self.main_btn.text = label
        self.main_btn.enabled = False

        def work():
            try:
                res = fn()
            except Exception:                         # noqa: BLE001
                log.exception("bg action")
                res = None
            self._bg_done(res, after)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _bg_done(self, res, after):
        self._busy = False
        self.main_btn.enabled = True
        if after:
            after(res)
        self.refresh()

    def _tg_setup(self):
        if not telegram_helper.resolve_package(self.app.cfg) and au.available():
            self._telegram_missing()
            return
        if config_store.validate(self.app.cfg):
            Toast.show(tr("err_start_invalid"))
            self.app.show_tab("settings")
            return
        if telegram_helper.open_proxy_link(self.app.cfg):
            Toast.show(tr("tg_link_opened"))
        else:
            Toast.show(tr("tg_link_failed"))

    def _telegram_missing(self):
        message_dialog(tr("tg_missing_title"), tr("tg_missing_text"), [
            (tr("btn_play_store"), "primary", telegram_helper.open_store),
            (tr("btn_tg_site"), "secondary", telegram_helper.open_download_page),
            (tr("btn_cancel"), "secondary", None),
        ])

    def _add_tile(self):
        if au.request_add_tile():
            Toast.show(tr("tile_requested"), 4)
        else:
            message_dialog(tr("btn_add_tile"), tr("tile_manual"), [(tr("btn_ok"), "primary", None)])

    def _shortcut(self):
        if au.available() and not telegram_helper.resolve_package(self.app.cfg):
            self._telegram_missing()
            return
        if not shortcut_helper.is_supported():
            message_dialog(tr("btn_shortcut"), tr("shortcut_unsupported"),
                           [(tr("btn_ok"), "primary", None)])
            return
        icon = os.path.join(self.app.app_dir, "assets", "icons", "shortcut.png")
        if shortcut_helper.create(tr("shortcut_label"), tr("shortcut_long"), icon):
            Toast.show(tr("shortcut_requested"), 4)
        else:
            Toast.show(tr("shortcut_failed"))
