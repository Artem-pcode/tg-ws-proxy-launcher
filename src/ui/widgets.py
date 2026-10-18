"""Небольшой набор виджетов Kivy: карточки, кнопки, поля с валидацией, переключатели."""
from __future__ import annotations

from typing import Callable, Optional

from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from .theme import Theme


class WrapLabel(Label):
    """Label, который переносит текст по ширине и сам подбирает высоту."""

    def __init__(self, **kw):
        kw.setdefault("color", Theme.get("text"))
        kw.setdefault("font_size", sp(15))
        kw.setdefault("halign", "left")
        kw.setdefault("valign", "middle")
        kw.setdefault("size_hint_y", None)
        self.collapse_empty = kw.pop("collapse_empty", False)
        super().__init__(**kw)
        self.bind(width=self._wrap, texture_size=self._fit, text=self._fit)
        self._wrap()
        self._fit()

    def _wrap(self, *_):
        self.text_size = (self.width, None)

    def _fit(self, *_):
        if self.collapse_empty and not self.text:
            self.height = 0
        else:
            self.height = max(self.texture_size[1], dp(20))


class Card(BoxLayout):
    bg = ListProperty([0, 0, 0, 0])

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("padding", dp(14))
        kw.setdefault("spacing", dp(10))
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self.bg = Theme.get("surface")
        with self.canvas.before:
            self._c = Color(*self.bg)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(pos=self._upd, size=self._upd, bg=self._upd)
        self.bind(minimum_height=self.setter("height"))

    def _upd(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        self._c.rgba = self.bg


class AppButton(ButtonBehavior, Label):
    """Скруглённая кнопка. kind: primary | secondary | danger."""

    kind = StringProperty("primary")
    enabled = BooleanProperty(True)

    def __init__(self, text="", kind="primary", on_press_cb: Optional[Callable] = None, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(48))
        kw.setdefault("font_size", sp(15))
        kw.setdefault("bold", True)
        kw.setdefault("halign", "center")
        kw.setdefault("valign", "middle")
        super().__init__(text=text, **kw)
        self.kind = kind
        self._cb = on_press_cb
        with self.canvas.before:
            self._c = Color(0, 0, 0, 1)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.bind(pos=self._upd, size=self._upd, kind=self._upd, enabled=self._upd,
                  state=self._upd, width=self._wrap)
        self._wrap()
        self._upd()

    def _wrap(self, *_):
        self.text_size = (self.width - dp(16), None)

    def _upd(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        if not self.enabled:
            self._c.rgba = Theme.get("surface2")
            self.color = Theme.get("muted")
            return
        pressed = self.state == "down"
        if self.kind == "primary":
            base, fg = Theme.get("primary"), Theme.get("on_primary")
        elif self.kind == "danger":
            base, fg = Theme.get("danger"), (1, 1, 1, 1)
        else:
            base, fg = Theme.get("surface2"), Theme.get("text")
        self._c.rgba = tuple(max(0.0, v - 0.12) for v in base[:3]) + (1,) if pressed else base
        self.color = fg

    def on_press(self):
        if self.enabled and self._cb:
            self._cb()

    def on_touch_down(self, touch):
        if not self.enabled and self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)


class Field(BoxLayout):
    """Подпись + поле ввода + строка ошибки. validator(text) -> код ошибки | None."""

    def __init__(self, label: str, value: str = "", multiline: bool = False,
                 validator: Optional[Callable[[str], Optional[str]]] = None,
                 error_text: Callable[[str], str] = lambda c: c,
                 on_change: Optional[Callable[["Field"], None]] = None,
                 input_filter=None, rows: int = 3, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("spacing", dp(4))
        super().__init__(**kw)
        self._validator, self._error_text, self._on_change = validator, error_text, on_change
        self.bind(minimum_height=self.setter("height"))

        self.label = WrapLabel(text=label, color=Theme.get("muted"), font_size=sp(12))
        self.add_widget(self.label)

        h = dp(48) if not multiline else dp(24 + 22 * rows)
        self.input = TextInput(
            text=value, multiline=multiline, size_hint_y=None, height=h,
            font_size=sp(15), padding=[dp(12), dp(12), dp(12), dp(12)],
            background_normal="", background_active="", background_color=Theme.get("input_bg"),
            foreground_color=Theme.get("text"), cursor_color=Theme.get("primary"),
            hint_text_color=Theme.get("muted"), input_filter=input_filter,
            write_tab=False,
        )
        self.input.bind(text=self._changed)
        self.add_widget(self.input)

        self.error = WrapLabel(text="", color=Theme.get("danger"), font_size=sp(12),
                               collapse_empty=True)
        self.error.opacity = 0
        self.add_widget(self.error)
        self.validate()

    @property
    def text(self) -> str:
        return self.input.text

    @text.setter
    def text(self, v: str) -> None:
        self.input.text = v

    def validate(self) -> Optional[str]:
        code = self._validator(self.input.text) if self._validator else None
        self.set_error(code)
        return code

    def set_error(self, code: Optional[str]) -> None:
        if code:
            self.error.text = self._error_text(code)
            self.error.opacity = 1
            self.error.size_hint_y = None
            self.input.background_color = _tint(Theme.get("danger"))
        else:
            self.error.text = ""
            self.error.opacity = 0
            self.input.background_color = Theme.get("input_bg")

    def _changed(self, *_):
        self.validate()
        if self._on_change:
            self._on_change(self)


def _tint(c):
    bg = Theme.get("input_bg")
    return tuple(bg[i] * 0.8 + c[i] * 0.2 for i in range(3)) + (1,)


class SwitchRow(BoxLayout):
    def __init__(self, label: str, value: bool = False,
                 on_change: Optional[Callable[[bool], None]] = None, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("spacing", dp(10))
        super().__init__(**kw)
        self._on_change = on_change
        self.lbl = WrapLabel(text=label, size_hint_x=1)
        self.sw = Switch(active=value, size_hint=(None, None), size=(dp(80), dp(40)))
        self.sw.bind(active=lambda _w, v: self._on_change and self._on_change(v))
        self.add_widget(self.lbl)
        self.add_widget(self.sw)
        self.lbl.bind(height=self._fit)
        self._fit()

    def _fit(self, *_):
        self.height = max(self.lbl.height, dp(44))

    @property
    def active(self) -> bool:
        return self.sw.active

    @active.setter
    def active(self, v: bool) -> None:
        self.sw.active = v


class SectionTitle(WrapLabel):
    def __init__(self, text: str, **kw):
        kw.setdefault("font_size", sp(13))
        kw.setdefault("bold", True)
        kw.setdefault("color", Theme.get("primary"))
        super().__init__(text=text.upper(), **kw)


class ProgressLine(Widget):
    value = NumericProperty(0.0)

    def __init__(self, **kw):
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(6))
        super().__init__(**kw)
        with self.canvas:
            Color(*Theme.get("surface2"))
            self._bg = RoundedRectangle(radius=[dp(3)])
            self._fgc = Color(*Theme.get("primary"))
            self._fg = RoundedRectangle(radius=[dp(3)])
        self.bind(pos=self._upd, size=self._upd, value=self._upd)

    def _upd(self, *_):
        self._bg.pos, self._bg.size = self.pos, self.size
        self._fg.pos = self.pos
        self._fg.size = (max(0, self.width * min(1.0, self.value)), self.height)


def vscroll(body: BoxLayout) -> ScrollView:
    sv = ScrollView(do_scroll_x=False, bar_width=dp(3), scroll_type=["bars", "content"])
    body.bind(minimum_height=body.setter("height"))
    sv.add_widget(body)
    return sv


def vbox(**kw) -> BoxLayout:
    kw.setdefault("orientation", "vertical")
    kw.setdefault("size_hint_y", None)
    kw.setdefault("spacing", dp(12))
    kw.setdefault("padding", [dp(14), dp(14), dp(14), dp(24)])
    box = BoxLayout(**kw)
    box.bind(minimum_height=box.setter("height"))
    return box


def message_dialog(title: str, text: str, buttons) -> ModalView:
    """buttons: [(label, kind, callback|None)] - диалог закрывается после нажатия."""
    view = ModalView(size_hint=(0.9, None), height=dp(300), auto_dismiss=True,
                     background="", background_color=(0, 0, 0, 0.6))
    card = Card()
    card.add_widget(WrapLabel(text=title, bold=True, font_size=sp(18)))
    card.add_widget(WrapLabel(text=text, color=Theme.get("muted")))
    for label, kind, cb in buttons:
        def make(cb=cb):
            def _press():
                view.dismiss()
                if cb:
                    cb()
            return _press
        card.add_widget(AppButton(text=label, kind=kind, on_press_cb=make()))
    view.add_widget(card)
    card.bind(height=lambda _w, h: setattr(view, "height", h + dp(2)))
    view.open()
    return view


class Toast(Label):
    """Всплывающее сообщение внизу экрана (внутри окна приложения)."""

    _active: Optional["Toast"] = None

    @classmethod
    def show(cls, text: str, seconds: float = 3.0) -> None:
        from kivy.core.window import Window
        if cls._active is not None:
            try:
                Window.remove_widget(cls._active)
            except Exception:
                pass
        t = cls(text=text, size_hint=(None, None), color=Theme.get("text"),
                font_size=sp(14), halign="center", valign="middle")
        t.text_size = (Window.width * 0.85, None)
        t.texture_update()
        t.size = (min(Window.width * 0.9, t.texture_size[0] + dp(32)), t.texture_size[1] + dp(22))
        t.pos = ((Window.width - t.width) / 2, dp(96))
        with t.canvas.before:
            Color(*Theme.get("surface2"))
            RoundedRectangle(pos=t.pos, size=t.size, radius=[dp(12)])
        Window.add_widget(t)
        cls._active = t

        def _rm(_dt):
            try:
                Window.remove_widget(t)
            except Exception:
                pass
            if cls._active is t:
                cls._active = None
        Clock.schedule_once(_rm, seconds)
