"""Карточка «Приложение»: проверка новой версии на GitHub Releases, скачивание и установка APK."""
from __future__ import annotations

import logging
import threading

from kivy.clock import mainthread
from kivy.metrics import dp, sp

from ...core import android_utils as au, app_update
from ...core.i18n import tr
from ...core.update_manager import UpdateError
from ..theme import Theme
from ..widgets import AppButton, Card, ProgressLine, SectionTitle, Toast, WrapLabel

log = logging.getLogger("tgwsp.ui.appupdate")


def _error_text(exc: Exception) -> str:
    if isinstance(exc, UpdateError):
        key = "upd_" + exc.code
        text = tr(key, detail=exc.detail)
        if text != key:
            return text
    return tr("upd_other", detail=str(exc))


class AppUpdateCard(Card):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self._busy = False
        self._info = None
        self.add_widget(SectionTitle(tr("app_upd_title")))
        self.ver_lbl = WrapLabel(text=tr("app_ver", ver=app_update.local_version()), font_size=sp(14))
        self.msg_lbl = WrapLabel(text="", color=Theme.get("muted"), font_size=sp(14), collapse_empty=True)
        self.notes_lbl = WrapLabel(text="", color=Theme.get("muted"), font_size=sp(12), collapse_empty=True)
        self.progress = ProgressLine()
        self.progress.opacity = 0
        self.check_btn = AppButton(text=tr("app_btn_check"), on_press_cb=self._check)
        self.install_btn = AppButton(text="", on_press_cb=self._install)
        self._show_install(False)
        self.page_btn = AppButton(text=tr("btn_open_release"), kind="secondary", height=dp(40),
                                  on_press_cb=lambda: au.view_uri(
                                      (self._info or {}).get("html_url") or app_update.RELEASES_URL))
        self.hint_lbl = WrapLabel(text=tr("app_sig_hint"), color=Theme.get("muted"), font_size=sp(11))
        for w in (self.ver_lbl, self.msg_lbl, self.notes_lbl, self.progress, self.check_btn,
                  self.install_btn, self.page_btn, self.hint_lbl):
            self.add_widget(w)
        pending = getattr(app, "app_update_info", None)
        if pending and pending.get("newer"):
            self._show_result(pending)

    def _show_install(self, show, text=""):
        self.install_btn.text = text
        self.install_btn.opacity = 1 if show else 0
        self.install_btn.enabled = show
        self.install_btn.height = dp(48) if show else 0

    def _set_busy(self, busy, msg=""):
        self._busy = busy
        self.check_btn.enabled = not busy
        self.msg_lbl.color = Theme.get("muted")
        self.msg_lbl.text = msg

    # --- проверка
    def _check(self):
        if self._busy:
            return
        self._set_busy(True, tr("checking"))

        def work():
            try:
                self._checked(app_update.check_latest(), None)
            except Exception as exc:                       # noqa: BLE001
                log.warning("app check failed: %r", exc)
                self._checked(None, exc)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _checked(self, info, exc):
        self._set_busy(False)
        if exc is not None:
            self.msg_lbl.text = _error_text(exc)
            self.msg_lbl.color = Theme.get("danger")
            return
        self.app.app_update_info = info
        self._show_result(info)

    def _show_result(self, info):
        self._info = info
        if not info["newer"]:
            self.msg_lbl.text = tr("app_up_to_date", ver=info["local"])
            self.msg_lbl.color = Theme.get("ok")
            self.notes_lbl.text = ""
            self._show_install(False)
            return
        self.msg_lbl.color = Theme.get("warn")
        self.notes_lbl.text = (info["notes"] or "").strip()[:1500]
        if info["apk_url"]:
            self.msg_lbl.text = tr("app_available", tag=info["tag"], ver=info["local"])
            self._show_install(True, tr("app_btn_download", tag=info["tag"]))
        else:
            self.msg_lbl.text = tr("app_available", tag=info["tag"], ver=info["local"]) + "\n" + tr("app_no_apk")
            self._show_install(False)

    # --- скачивание и установка
    def _install(self):
        if self._busy or not self._info or not self._info.get("apk_url"):
            return
        info = self._info
        self._set_busy(True, tr("app_downloading"))
        self.progress.value = 0.02
        self.progress.opacity = 1

        def work():
            try:
                name = app_update.download(info, self._progress)
                self._downloaded(name, None)
            except Exception as exc:                       # noqa: BLE001
                log.warning("app download failed: %r", exc)
                self._downloaded("", exc)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _progress(self, v):
        self.progress.value = v

    @mainthread
    def _downloaded(self, name, exc):
        self._set_busy(False)
        self.progress.opacity = 0
        if exc is not None:
            self.msg_lbl.text = _error_text(exc)
            self.msg_lbl.color = Theme.get("danger")
            return
        res = au.install_apk(name)           # главный поток: класс приложения резолвится его загрузчиком
        if res == 0:
            self.msg_lbl.text = tr("app_install_started")
            self.msg_lbl.color = Theme.get("ok")
        elif res == 1:
            self.msg_lbl.text = tr("app_need_perm")
            self.msg_lbl.color = Theme.get("warn")
        else:
            self.msg_lbl.text = tr("app_install_failed")
            self.msg_lbl.color = Theme.get("danger")
