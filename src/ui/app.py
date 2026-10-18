"""Главное приложение Kivy: навигация, темы, обработка клика по ярлыку."""
from __future__ import annotations

import logging
import threading

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager

from ..core import (android_utils as au, config_store, i18n, launch_flow, paths,
                    service_controller, shortcut_helper, telegram_helper)
from ..core.i18n import tr
from .screens.adb import AdbScreen
from .screens.logs import LogsScreen
from .screens.permissions import PermissionsScreen
from .screens.settings import SettingsScreen
from .screens.status import StatusScreen
from .screens.update import UpdateScreen
from .theme import Theme
from .widgets import AppButton, Toast, WrapLabel, message_dialog

log = logging.getLogger("tgwsp.ui")

TABS = [("status", "nav_status"), ("settings", "nav_settings"), ("core", "nav_core"),
        ("logs", "nav_logs"), ("system", "nav_system"), ("adb", "nav_adb")]


class _Bg(BoxLayout):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            self._c = Color(*Theme.get("bg"))
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size


class NavBar(BoxLayout):
    def __init__(self, on_select, current, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(56))
        super().__init__(**kw)
        with self.canvas.before:
            Color(*Theme.get("surface"))
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._u, size=self._u)
        self.buttons = {}
        for key, label in TABS:
            b = Label(text=tr(label), font_size=sp(11), bold=(key == current),
                      color=Theme.get("primary") if key == current else Theme.get("muted"))
            b.key = key
            b.bind(on_touch_down=lambda w, t, k=key: self._touch(w, t, k, on_select))
            self.buttons[key] = b
            self.add_widget(b)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size

    @staticmethod
    def _touch(w, touch, key, cb):
        if w.collide_point(*touch.pos):
            cb(key)
            return True
        return False

    def select(self, current):
        for key, b in self.buttons.items():
            b.color = Theme.get("primary") if key == current else Theme.get("muted")
            b.bold = key == current


class TgWsProxyApp(App):
    title = "TG WS Proxy"

    def build(self):
        self.app_dir = paths.app_dir()
        self.cfg = config_store.load()
        self._apply_prefs()
        Window.softinput_mode = "below_target"
        Window.bind(on_keyboard=self._on_key)
        self.current_tab = "status"
        self._launching = False
        self.container = BoxLayout()
        self._build_ui("status")
        return self.container

    # --- тема / язык
    def _apply_prefs(self):
        i18n.set_lang(self.cfg.get("lang", "auto"))
        theme = self.cfg.get("theme", "auto")
        Theme.set(au.is_night_mode() if theme == "auto" else theme == "dark")
        Window.clearcolor = Theme.get("bg")

    def rebuild(self, tab=None):
        self._apply_prefs()
        self._build_ui(tab or self.current_tab)

    def _build_ui(self, tab):
        self.container.clear_widgets()
        root = _Bg(orientation="vertical")
        self.sm = ScreenManager(transition=NoTransition())
        self.screens = {
            "status": StatusScreen(self, name="status"),
            "settings": SettingsScreen(self, name="settings"),
            "core": UpdateScreen(self, name="core"),
            "logs": LogsScreen(self, name="logs"),
            "system": PermissionsScreen(self, name="system"),
            "adb": AdbScreen(self, name="adb"),
        }
        for s in self.screens.values():
            self.sm.add_widget(s)
        self.launch_screen = Screen(name="launch")
        box = BoxLayout(orientation="vertical", padding=dp(32), spacing=dp(12))
        box.add_widget(Label())
        self.launch_lbl = Label(text=tr("launching"), font_size=sp(20), color=Theme.get("text"))
        box.add_widget(self.launch_lbl)
        box.add_widget(Label())
        self.launch_screen.add_widget(box)
        self.sm.add_widget(self.launch_screen)

        self.nav = NavBar(self.show_tab, tab)
        root.add_widget(self.sm)
        root.add_widget(self.nav)
        self.container.add_widget(root)
        self.sm.current = tab
        self.current_tab = tab

    def show_tab(self, key):
        self.current_tab = key
        self.sm.current = key
        self.nav.select(key)

    def _on_key(self, window, key, *args):
        if key == 27:                                   # кнопка «Назад»
            if self.sm.current == "launch":
                return True
            if self.current_tab != "status":
                self.show_tab("status")
            else:
                au.move_task_to_back()
            return True
        return False

    # --- жизненный цикл Android
    def on_start(self):
        service_controller.preload()        # классы приложения - только из главного потока
        if paths.is_android():
            try:
                from android import activity  # type: ignore
                activity.bind(on_new_intent=self._on_new_intent)
            except Exception:                           # noqa: BLE001
                log.exception("bind on_new_intent")
        Clock.schedule_once(lambda dt: self._handle_intent_action(au.get_intent_action()), 0.2)

    def on_resume(self):
        return True

    def on_pause(self):
        return True                                     # не выгружать приложение в фоне

    def _on_new_intent(self, intent):
        try:
            action = str(intent.getAction() or "")
        except Exception:                               # noqa: BLE001
            action = ""
        Clock.schedule_once(lambda dt: self._handle_intent_action(action), 0)

    # --- права при первом запуске
    def ensure_first_run_permissions(self):
        if self.cfg.get("first_run_done"):
            return
        self.cfg["first_run_done"] = True
        config_store.save(self.cfg)
        au.request_permissions([au.POST_NOTIFICATIONS])

    # --- клик по ярлыку
    def _handle_intent_action(self, action):
        if not shortcut_helper.is_shortcut_action(action) or self._launching:
            return
        self._launching = True
        au.clear_intent()
        self.sm.current = "launch"
        self.launch_lbl.text = tr("launching")
        cfg = dict(self.cfg)

        def state(s):
            self._launch_state(s)

        def work():
            ok, reason = launch_flow.run(cfg, state)
            self._launch_done(ok, reason)

        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _launch_state(self, s):
        self.launch_lbl.text = tr("launch_wait_tg") if s == "opening_telegram" else tr("launching")

    @mainthread
    def _launch_done(self, ok, reason):
        self._launching = False
        if ok:
            au.move_task_to_back()      # не убиваем задачу: на ряде прошивок это останавливает и сервис
            return
        self.sm.current = self.current_tab
        if reason == "no_telegram":
            message_dialog(tr("tg_missing_title"), tr("tg_missing_text"), [
                (tr("btn_play_store"), "primary", telegram_helper.open_store),
                (tr("btn_tg_site"), "secondary", telegram_helper.open_download_page),
                (tr("btn_cancel"), "secondary", None)])
        elif reason == "invalid_config":
            au.toast(tr("err_start_invalid"))
            self.show_tab("settings")
        elif reason == "tg_failed":
            au.toast(tr("tg_link_failed"))
            Toast.show(tr("tg_link_failed"))
        else:
            au.toast(tr("launch_failed"))
            Toast.show(tr("launch_failed"))
