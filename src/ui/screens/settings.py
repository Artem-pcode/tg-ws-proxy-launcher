"""Экран «Настройки»: все параметры CLI, валидация на лету, автосохранение."""
from __future__ import annotations

from typing import Callable, Dict, Optional

from kivy.clock import Clock
from kivy.metrics import dp, sp

from ...core import config_store as cs
from ...core import android_utils as au
from ...core import status_reader, telegram_helper
from ...core.i18n import tr
from ..theme import Theme
from ..widgets import (AppButton, Card, Field, SectionTitle, SwitchRow, Toast,
                       WrapLabel)
from .base import BaseScreen

HEX_CHARS = "0123456789abcdefABCDEF"


def _hex_filter(substring: str, from_undo: bool) -> str:
    return "".join(c for c in substring if c in HEX_CHARS)


def _digits_filter(substring: str, from_undo: bool) -> str:
    return "".join(c for c in substring if c.isdigit())


class SettingsScreen(BaseScreen):
    def build(self):
        self._loading = False
        self._ready = False
        self._save_ev = None
        self.fields: Dict[str, Field] = {}
        self.switches: Dict[str, SwitchRow] = {}
        cfg = self.app.cfg

        self.apply_hint = WrapLabel(text="", color=Theme.get("warn"), font_size=sp(13),
                                    collapse_empty=True)
        self.body.add_widget(self.apply_hint)

        card = Card()
        card.add_widget(SectionTitle(tr("set_proxy")))
        err = lambda code: tr(code)

        def add_field(key, label, validator_key, **kw):
            f = Field(label, validator=lambda t, k=key: self._validate_one(k),
                      error_text=err, on_change=self._changed, **kw)
            self.fields[key] = f
            card.add_widget(f)
            return f

        add_field("port", tr("f_port"), "port", input_filter=_digits_filter)
        add_field("host", tr("f_host"), "host")

        add_field("secret", tr("f_secret"), "secret", input_filter=_hex_filter)
        card.add_widget(AppButton(text=tr("btn_generate"), kind="secondary",
                                  height=dp(40), on_press_cb=self._generate))

        add_field("dc_ip", tr("f_dc"), "dc_ip", multiline=True, rows=3)
        add_field("buf_kb", tr("f_buf"), "buf_kb", input_filter=_digits_filter)
        add_field("pool_size", tr("f_pool"), "pool_size", input_filter=_digits_filter)
        add_field("cfproxy_domains", tr("f_cf_domains"), "cfproxy_domains", multiline=True, rows=3)
        add_field("cfproxy_worker_domains", tr("f_cf_workers"), "cfproxy_worker_domains",
                  multiline=True, rows=3)
        add_field("fake_tls_domain", tr("f_fake_tls"), "fake_tls_domain")

        for key, label in (("no_h2", "f_no_h2"), ("no_cfproxy", "f_no_cf"),
                           ("no_secure", "f_no_secure"), ("force_test_dc", "f_force_test"),
                           ("proxy_protocol", "f_proxy_proto"), ("verbose", "f_verbose")):
            row = SwitchRow(tr(label), on_change=lambda v, k=key: self._switch(k, v))
            self.switches[key] = row
            card.add_widget(row)
        self.body.add_widget(card)

        saver = Card()
        saver.add_widget(SectionTitle(tr("set_saver")))
        saver.add_widget(WrapLabel(text=tr("saver_hint"), color=Theme.get("muted"), font_size=sp(12)))
        row = SwitchRow(tr("f_saver"), on_change=lambda v: self._saver_switch("battery_saver", v))
        self.switches["battery_saver"] = row
        saver.add_widget(row)
        tf = Field(tr("f_saver_timeout"), validator=lambda t: self._validate_one("saver_timeout_min"),
                   error_text=err, on_change=self._changed, input_filter="float")
        self.fields["saver_timeout_min"] = tf
        saver.add_widget(tf)
        drow = SwitchRow(tr("f_saver_debug"), on_change=lambda v: self._switch("saver_debug", v))
        self.switches["saver_debug"] = drow
        saver.add_widget(drow)
        self.access_lbl = WrapLabel(text="", font_size=sp(13))
        saver.add_widget(self.access_lbl)
        saver.add_widget(AppButton(text=tr("btn_usage_access"), kind="secondary",
                                   height=dp(44), on_press_cb=au.open_usage_access_settings))
        self.body.add_widget(saver)

        btns = Card()
        btns.add_widget(AppButton(text=tr("btn_save"), on_press_cb=self._save_clicked))
        btns.add_widget(AppButton(text=tr("btn_reset"), kind="secondary", on_press_cb=self._reset))
        self.body.add_widget(btns)

        app_card = Card()
        app_card.add_widget(SectionTitle(tr("set_app")))
        self.tg_btn = AppButton(text="", kind="secondary", height=dp(44), on_press_cb=self._cycle_tg)
        self.lang_btn = AppButton(text="", kind="secondary", height=dp(44), on_press_cb=self._cycle_lang)
        self.theme_btn = AppButton(text="", kind="secondary", height=dp(44), on_press_cb=self._cycle_theme)
        for b in (self.tg_btn, self.lang_btn, self.theme_btn):
            app_card.add_widget(b)
        self.body.add_widget(app_card)

        self._ready = True
        self.load_from_cfg(cfg)
        self._refresh_access()

    # --- значения <-> конфиг
    def load_from_cfg(self, cfg):
        self._loading = True
        try:
            f = self.fields
            f["port"].text = str(cfg["port"])
            f["host"].text = cfg["host"]
            f["secret"].text = cfg["secret"]
            f["dc_ip"].text = "\n".join(cfg["dc_ip"])
            f["buf_kb"].text = str(cfg["buf_kb"])
            f["pool_size"].text = str(cfg["pool_size"])
            f["cfproxy_domains"].text = "\n".join(cfg["cfproxy_domains"])
            f["cfproxy_worker_domains"].text = "\n".join(cfg["cfproxy_worker_domains"])
            f["fake_tls_domain"].text = cfg["fake_tls_domain"]
            f["saver_timeout_min"].text = f"{cfg['saver_timeout_min']:g}"
            for k, row in self.switches.items():
                row.active = bool(cfg[k])
        finally:
            self._loading = False
        for fld in self.fields.values():
            fld.validate()
        self._refresh_app_buttons()

    def _collect(self) -> dict:
        cfg = dict(self.app.cfg)
        f = self.fields
        cfg.update(
            port=f["port"].text, host=f["host"].text.strip(), secret=f["secret"].text.strip(),
            dc_ip=cs.split_lines(f["dc_ip"].text), buf_kb=f["buf_kb"].text,
            pool_size=f["pool_size"].text,
            cfproxy_domains=cs.split_domains(f["cfproxy_domains"].text),
            cfproxy_worker_domains=cs.split_domains(f["cfproxy_worker_domains"].text),
            fake_tls_domain=f["fake_tls_domain"].text.strip(),
            saver_timeout_min=f["saver_timeout_min"].text.strip(),
        )
        for k, row in self.switches.items():
            cfg[k] = row.active
        return cfg

    def _validate_one(self, key: str) -> Optional[str]:
        if not getattr(self, "_ready", False):
            return None                                 # поля ещё создаются
        return cs.validate(self._collect()).get(key)

    # --- события
    def _changed(self, _field=None):
        if self._loading:
            return
        if self._save_ev:
            self._save_ev.cancel()
        self._save_ev = Clock.schedule_once(lambda dt: self._autosave(), 0.6)

    def _saver_switch(self, key, value):
        if value and not self._loading and au.available() and not au.has_usage_access():
            Toast.show(tr("saver_access_no"), 4)
            au.open_usage_access_settings()
        self._switch(key, value)
        self._refresh_access()

    def _refresh_access(self):
        ok = au.has_usage_access() if au.available() else False
        self.access_lbl.text = tr("saver_access_ok") if ok else tr("saver_access_no")
        self.access_lbl.color = Theme.get("ok") if ok else Theme.get("warn")

    def _switch(self, key, value):
        if not self._loading:
            self._changed()

    def _autosave(self):
        self._save_ev = None
        cfg = self._collect()
        if cs.validate(cfg):
            return                                      # невалидное не сохраняем
        self._store(cfg)

    def _store(self, cfg):
        merged = cs.normalize(cfg)
        changed = any(merged.get(k) != self.app.cfg.get(k) for k in cs.PROXY_KEYS)
        self.app.cfg = merged
        cs.save(merged)
        self.apply_hint.text = tr("apply_hint") if changed and status_reader.is_alive() else ""

    def _save_clicked(self):
        for fld in self.fields.values():
            fld.validate()
        cfg = self._collect()
        errs = cs.validate(cfg)
        if errs:
            Toast.show(tr(next(iter(errs.values()))))
            return
        self._store(cfg)
        Toast.show(tr("saved"))

    def _generate(self):
        self.fields["secret"].text = cs.generate_secret()

    def _reset(self):
        cfg = cs.reset_proxy_settings(self.app.cfg)
        self._store(cfg)
        self.load_from_cfg(self.app.cfg)
        Toast.show(tr("reset_done"))

    # --- настройки приложения
    def _refresh_app_buttons(self):
        cfg = self.app.cfg
        pkg = cfg.get("telegram_package", "auto")
        name = tr("tg_auto")
        for p, n in telegram_helper.KNOWN_PACKAGES:
            if p == pkg:
                name = n
        self.tg_btn.text = f"{tr('f_tg_pkg')}: {name}"
        self.lang_btn.text = f"{tr('f_lang')}: {tr('lang_' + cfg.get('lang', 'auto'))}"
        self.theme_btn.text = f"{tr('f_theme')}: {tr('theme_' + cfg.get('theme', 'auto'))}"

    def _cycle_tg(self):
        options = ["auto"] + [p for p, _ in telegram_helper.installed()]
        cur = self.app.cfg.get("telegram_package", "auto")
        nxt = options[(options.index(cur) + 1) % len(options)] if cur in options else "auto"
        self.app.cfg["telegram_package"] = nxt
        cs.save(self.app.cfg)
        self._refresh_app_buttons()

    def _cycle_lang(self):
        order = ["auto", "ru", "en"]
        cur = self.app.cfg.get("lang", "auto")
        self.app.cfg["lang"] = order[(order.index(cur) + 1) % 3] if cur in order else "auto"
        cs.save(self.app.cfg)
        self.app.rebuild(tab="settings")

    def _cycle_theme(self):
        order = ["auto", "light", "dark"]
        cur = self.app.cfg.get("theme", "auto")
        self.app.cfg["theme"] = order[(order.index(cur) + 1) % 3] if cur in order else "auto"
        cs.save(self.app.cfg)
        self.app.rebuild(tab="settings")

    def on_show(self):
        self._refresh_app_buttons()
        self._refresh_access()
