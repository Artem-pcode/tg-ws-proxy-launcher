"""Экран «Ядро»: проверка/загрузка обновления с GitHub, откат."""
from __future__ import annotations

import logging
import threading

from kivy.clock import mainthread
from kivy.metrics import dp, sp

from ...core import service_controller, status_reader, update_manager as um
from ...core.i18n import tr
from ..theme import Theme
from ..widgets import (AppButton, Card, ProgressLine, SectionTitle, Toast,
                       WrapLabel)
from .base import BaseScreen

log = logging.getLogger("tgwsp.ui.update")


def error_text(exc: Exception) -> str:
    if isinstance(exc, um.UpdateError):
        key = "upd_" + exc.code
        text = tr(key, detail=exc.detail)
        if text != key:
            return text
        return tr("upd_other", detail=str(exc))
    return tr("upd_other", detail=repr(exc))


class UpdateScreen(BaseScreen):
    def build(self):
        self._busy = False
        self._latest = None

        info = Card()
        info.add_widget(SectionTitle(tr("core_title")))
        self.info_lbl = WrapLabel(text="", font_size=sp(14))
        info.add_widget(self.info_lbl)
        self.body.add_widget(info)

        act = Card()
        self.check_btn = AppButton(text=tr("btn_check"), on_press_cb=self._check)
        self.update_btn = AppButton(text="", on_press_cb=self._update)
        self.update_btn.opacity = 0
        self.update_btn.enabled = False
        self.update_btn.height = 0
        self.progress = ProgressLine()
        self.progress.opacity = 0
        self.msg_lbl = WrapLabel(text="", color=Theme.get("muted"), font_size=sp(14),
                                 collapse_empty=True)
        self.rollback_btn = AppButton(text=tr("btn_rollback"), kind="secondary",
                                      on_press_cb=self._rollback)
        for w in (self.check_btn, self.msg_lbl, self.progress, self.update_btn, self.rollback_btn):
            act.add_widget(w)
        self.body.add_widget(act)

        self.log_card = Card()
        self.log_card.add_widget(SectionTitle(tr("changelog")))
        self.changelog = WrapLabel(text="", font_size=sp(13), color=Theme.get("muted"))
        self.log_card.add_widget(self.changelog)
        self.log_card.opacity = 0
        self.log_card.height = 0
        self.log_card.size_hint_y = None
        self.body.add_widget(self.log_card)
        self.refresh_info()

    def on_show(self):
        self.refresh_info()

    def refresh_info(self):
        i = um.core_info()
        src = tr("core_src_github") if i["source"] == "github" else tr("core_src_builtin")
        lines = [f"{tr('core_current')}: {i['version']} ({src})",
                 f"{tr('core_bundled')}: {i['bundled_version']}"]
        if i.get("has_backup"):
            lines.append(f"{tr('core_backup')}: {i.get('backup_version') or '?'}")
        else:
            lines.append(f"{tr('core_backup')}: {tr('core_none')}")
        self.info_lbl.text = "\n".join(lines)
        self.rollback_btn.enabled = bool(i["can_rollback"]) and not self._busy
        self.rollback_btn.opacity = 1 if i["can_rollback"] else 0.4

    def _set_busy(self, busy, msg=""):
        self._busy = busy
        self.check_btn.enabled = not busy
        self.msg_lbl.text = msg
        self.refresh_info()

    # --- проверка
    def _check(self):
        if self._busy:
            return
        self._set_busy(True, tr("checking"))

        def work():
            try:
                self._checked(um.check_latest(), None)
            except Exception as exc:                      # noqa: BLE001
                log.warning("check failed: %r", exc)
                self._checked(None, exc)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _checked(self, result, exc):
        self._set_busy(False)
        if exc is not None:
            self.msg_lbl.text = error_text(exc)
            self.msg_lbl.color = Theme.get("danger")
            return
        self._latest = result
        self.msg_lbl.color = Theme.get("muted")
        if result["newer"]:
            self.msg_lbl.text = tr("update_available", tag=result["tag"], ver=result["local"])
            self.update_btn.text = tr("btn_update", tag=result["tag"])
            self.update_btn.height = dp(48)
            self.update_btn.opacity = 1
            self.update_btn.enabled = True
            body = (result["changelog"] or "").strip()
            self.changelog.text = body[:4000] or "—"
            self.log_card.size_hint_y = None
            self.log_card.opacity = 1
            self.log_card.height = self.log_card.minimum_height
        else:
            self.msg_lbl.text = tr("up_to_date", ver=result["local"])
            self.update_btn.opacity = 0
            self.update_btn.enabled = False
            self.update_btn.height = 0

    # --- загрузка и применение
    def _update(self):
        if self._busy or not self._latest:
            return
        tag = self._latest["tag"]
        self._set_busy(True, tr("downloading"))
        self.progress.value = 0.02
        self.progress.opacity = 1

        def prog(v):
            self._progress(v)

        def work():
            try:
                um.download_and_apply(tag, prog)
                self._applied(tag, None)
            except Exception as exc:                      # noqa: BLE001
                log.warning("update failed: %r", exc)
                self._applied(tag, exc)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _progress(self, v):
        self.progress.value = v

    @mainthread
    def _applied(self, tag, exc):
        self._set_busy(False)
        self.progress.opacity = 0
        if exc is not None:
            self.msg_lbl.text = error_text(exc)
            self.msg_lbl.color = Theme.get("danger")
            return
        self.update_btn.opacity = 0
        self.update_btn.enabled = False
        self.update_btn.height = 0
        self.log_card.opacity = 0
        self.log_card.height = 0
        self.msg_lbl.color = Theme.get("ok")
        if status_reader.is_alive():
            service_controller.reload()          # reload.signal: сервис перечитает ядро
            self.msg_lbl.text = tr("updated_restart", tag=tag)
        else:
            self.msg_lbl.text = tr("updated_to", tag=tag)
        Toast.show(tr("updated_to", tag=tag))
        self.refresh_info()

    # --- откат
    def _rollback(self):
        if self._busy:
            return
        if um.rollback_manual():
            if status_reader.is_alive():
                service_controller.reload()
            self.msg_lbl.color = Theme.get("ok")
            self.msg_lbl.text = tr("rolled_back", ver=um.local_version())
        else:
            self.msg_lbl.color = Theme.get("muted")
            self.msg_lbl.text = tr("nothing_to_rollback")
        self.refresh_info()
