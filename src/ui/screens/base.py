from __future__ import annotations

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import Screen

from ..theme import Theme
from ..widgets import vbox, vscroll


class BaseScreen(Screen):
    """Экран с прокручиваемым телом. Подклассы переопределяют build()/on_show()/on_hide()."""

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.body = vbox()
        self.add_widget(vscroll(self.body))
        self.build()

    def build(self) -> None:           # pragma: no cover
        pass

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def on_enter(self, *a):
        self.on_show()

    def on_leave(self, *a):
        self.on_hide()
