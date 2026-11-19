"""Экран «Логи»: короткий хвост proxy.log и launcher.log, окно «весь лог», поделиться, очистить."""
from __future__ import annotations

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView

from ...core import android_utils as au
from ...core import logview, paths
from ...core.i18n import tr
from ..theme import Theme
from ..widgets import AppButton, Card, SectionTitle, Toast, WrapLabel, vbox
from .base import BaseScreen

TAIL_LINES = 25                 # строк в предпросмотре на экране
TAIL_READ_BYTES = 64 * 1024     # сколько читать с конца файла для предпросмотра
SHARE_BYTES = 120 * 1024        # отправляем наружу (лимит Intent ~500 КБ)
PAGE_LINES = 150                # строк на странице в окне «весь лог»


def read_tail(limit: int, path: str = "") -> str:
    """Хвост файла как текст (для «Поделиться»)."""
    return "\n".join(logview.read_lines(path or paths.log_path(), limit))


class LogView(BoxLayout):
    """Текст лога, разбитый на небольшие Label'ы: одна огромная текстура рисуется чёрным квадратом."""

    def __init__(self, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("size_hint_y", None)
        super().__init__(**kw)
        self.bind(minimum_height=self.setter("height"))

    def set_lines(self, lines, clip=True):
        self.clear_widgets()
        if not lines:
            self.add_widget(WrapLabel(text=tr("log_empty"), color=Theme.get("muted"), font_size=sp(11)))
            return
        if clip:
            lines = [logview.clip(x) for x in lines]
        for block in logview.chunks(lines):
            self.add_widget(WrapLabel(text=block, font_name="RobotoMono-Regular", font_size=sp(11),
                                      color=Theme.get("muted")))


class FullLogView(ModalView):
    """Весь лог на весь экран: переключатель источника и постраничная навигация (новые строки сначала)."""

    def __init__(self, source="proxy", **kw):
        super().__init__(size_hint=(1, 1), auto_dismiss=False, background="",
                         background_color=Theme.get("bg"), **kw)
        self.source = source
        self.page_no = 0
        self.lines = []
        root = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        self.title_lbl = WrapLabel(text="", bold=True, font_size=sp(15))
        root.add_widget(self.title_lbl)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.btn_proxy = AppButton(text=tr("logs_title"), kind="secondary", height=dp(44),
                                   on_press_cb=lambda: self.set_source("proxy"))
        self.btn_app = AppButton(text=tr("log_src_app"), kind="secondary", height=dp(44),
                                 on_press_cb=lambda: self.set_source("app"))
        row.add_widget(self.btn_proxy)
        row.add_widget(self.btn_app)
        root.add_widget(row)
        self.view = LogView()
        self.scroll = ScrollView(do_scroll_x=False, bar_width=dp(4))
        self.scroll.add_widget(self.view)
        root.add_widget(self.scroll)
        nav = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        nav.add_widget(AppButton(text=tr("log_newer"), kind="secondary", height=dp(44),
                                 on_press_cb=lambda: self.go(-1)))
        nav.add_widget(AppButton(text=tr("log_older"), kind="secondary", height=dp(44),
                                 on_press_cb=lambda: self.go(1)))
        nav.add_widget(AppButton(text=tr("btn_close"), height=dp(44), on_press_cb=self.dismiss))
        root.add_widget(nav)
        self.add_widget(root)
        self.load()

    def _path(self):
        return paths.log_path() if self.source == "proxy" else paths.launcher_log_path()

    def set_source(self, src):
        self.source = src
        self.page_no = 0
        self.load()

    def load(self):
        self.lines = logview.read_lines(self._path())
        self.show()

    def go(self, delta):
        self.page_no += delta
        self.show()

    def show(self):
        lines, self.page_no, pages = logview.page(self.lines, self.page_no, PAGE_LINES)
        self.view.set_lines(lines, clip=False)
        name = tr("logs_title") if self.source == "proxy" else tr("log_src_app")
        self.title_lbl.text = tr("log_page_info", name=name, page=self.page_no + 1, pages=pages,
                                 total=len(self.lines))
        self.scroll.scroll_y = 0 if self.page_no == 0 else 1     # новая страница: к концу; старая: к началу


class LogsScreen(BaseScreen):
    def build(self):
        card = Card()
        card.add_widget(SectionTitle(tr("logs_title")))
        self.proxy_view = LogView()
        card.add_widget(self.proxy_view)
        self.body.add_widget(card)
        card2 = Card()
        card2.add_widget(SectionTitle(tr("launcher_log_title")))
        self.app_view = LogView()
        card2.add_widget(self.app_view)
        self.body.add_widget(card2)
        btns = Card()
        btns.add_widget(AppButton(text=tr("btn_open_full_log"), on_press_cb=self._open_full))
        btns.add_widget(AppButton(text=tr("btn_refresh"), kind="secondary", on_press_cb=self.refresh))
        btns.add_widget(AppButton(text=tr("btn_share_log"), kind="secondary", on_press_cb=self._share))
        btns.add_widget(AppButton(text=tr("btn_clear_log"), kind="secondary", on_press_cb=self._clear))
        self.body.add_widget(btns)

    def on_show(self):
        self.refresh()

    def refresh(self):
        self.proxy_view.set_lines(logview.tail_lines(
            logview.read_lines(paths.log_path(), TAIL_READ_BYTES), TAIL_LINES))
        self.app_view.set_lines(logview.tail_lines(
            logview.read_lines(paths.launcher_log_path(), 16 * 1024), 12))

    def _open_full(self):
        FullLogView("proxy").open()

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
