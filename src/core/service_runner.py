"""Логика foreground-сервиса: запуск прокси-ядра, сигналы, статус, откат.

Вызывается из services/proxy_service.py. Не импортирует Kivy.

Обмен с UI - только через файлы (см. paths.py):
  config.json   <- UI      полный конфиг
  stop.signal   <- UI      остановить
  reload.signal <- UI      перечитать конфиг + ядро и перезапустить прокси
  status.json   -> UI      состояние и статистика (раз в 2 с)
  proxy.log     -> UI      лог
"""
from __future__ import annotations

import asyncio
import errno
import importlib
import logging
import logging.handlers
import os
import threading
import time
import traceback
from typing import Any, Dict, Optional

from . import config_store, core_loader, libcrypto_shim, paths, saver

log = logging.getLogger("tgwsp.service")

STATUS_INTERVAL = 2.0
POLL_INTERVAL = 0.5
RESTART_DELAY = 5.0
MAX_CRASHES = 5               # не более N падений ...
CRASH_WINDOW = 300.0          # ... за это число секунд
EARLY_FAIL_SECONDS = 20.0     # падение раньше -> подозрение на плохое ядро
STOP_JOIN_TIMEOUT = 8.0


# ------------------------------------------------------------------ логи

def setup_logging(verbose: bool) -> logging.Handler:
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_tgwsp", False):
            root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(
        paths.log_path(), maxBytes=2 * 1024 * 1024, backupCount=1,
        encoding="utf-8")
    fh.setFormatter(fmt)
    fh._tgwsp = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh._tgwsp = True  # type: ignore[attr-defined]
    root.addHandler(sh)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for noisy in ("asyncio", "httpx", "httpcore", "hpack", "h2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return fh


def _censor(handler: logging.Handler) -> None:
    """Скрывать домены в логе так же, как это делает само ядро."""
    try:
        from proxy.utils import DomainCensorFilter  # type: ignore
    except Exception:
        return
    if not any(isinstance(f, DomainCensorFilter) for f in handler.filters):
        handler.addFilter(DomainCensorFilter())


# ---------------------------------------------------------------- статус

class Status:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.data: Dict[str, Any] = {
            "state": "starting", "pid": os.getpid(), "started": time.time(),
            "updated": time.time(), "error": "", "note": "", "restarts": 0,
            "summary": "", "active": 0, "total": 0, "bytes_up": 0,
            "bytes_down": 0, "ws_errors": 0, "host": "", "port": 0,
            "core_version": core_loader.active_version(),
            "core_source": core_loader.active_source(),
        }

    def update(self, **kw: Any) -> None:
        with self._lock:
            self.data.update(kw)
            self.data["updated"] = time.time()
            snapshot = dict(self.data)
        try:
            paths.write_json_atomic(paths.status_path(), snapshot)
        except OSError as exc:
            log.warning("не удалось записать status.json: %r", exc)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.data.get(key, default)


def _collect_stats() -> Dict[str, Any]:
    try:
        from proxy.stats import stats  # type: ignore
    except Exception:
        return {}
    out: Dict[str, Any] = {}
    try:
        out["summary"] = stats.summary()
    except Exception:
        pass
    out["active"] = int(getattr(stats, "connections_active", 0))
    out["total"] = int(getattr(stats, "connections_total", 0))
    out["bytes_up"] = int(getattr(stats, "bytes_up", 0))
    out["bytes_down"] = int(getattr(stats, "bytes_down", 0))
    out["ws_errors"] = int(getattr(stats, "ws_errors", 0))
    return out


# ------------------------------------------------------------ раннер ядра

class ProxyRunner(threading.Thread):
    """Поток с asyncio-циклом прокси + супервизор (рестарты, откат ядра)."""

    def __init__(self, status: Status) -> None:
        super().__init__(name="proxy-runner", daemon=True)
        self.status = status
        self.stop_flag = threading.Event()
        self.reload_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.resume_event = threading.Event()
        self._cfg_mod: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._lock = threading.Lock()
        self.fatal: Optional[str] = None
        self.module: Any = None

    # --- управление из основного потока
    def request_stop(self) -> None:
        self.stop_flag.set()
        self._kick()

    def request_reload(self) -> None:
        self.reload_flag.set()
        self._kick()

    def request_pause(self) -> None:
        """Остановить сетевое ядро, оставив сервис жить (режим экономии)."""
        self.resume_event.clear()
        self.pause_flag.set()
        self._kick()

    def request_resume(self) -> None:
        self.resume_event.set()

    def _kick(self) -> None:
        with self._lock:
            loop, ev = self._loop, self._stop_event
        if loop is not None and ev is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:
                pass

    # --- загрузка ядра (с откатом при ошибке импорта)
    def _load_core(self) -> Any:
        for attempt in range(3):
            source = core_loader.activate()
            core_loader.purge_modules()
            try:
                mod = importlib.import_module("proxy.tg_ws_proxy")
                cfg_mod = importlib.import_module("proxy.config")
                _censor_all()
                self.status.update(
                    core_version=core_loader.active_version(),
                    core_source=source)
                return mod, cfg_mod
            except Exception as exc:  # ImportError, SyntaxError, ...
                log.error("Не удалось импортировать ядро (%s): %r", source, exc)
                log.debug("%s", traceback.format_exc())
                if source == "github" and core_loader.rollback(
                        f"ошибка импорта: {exc!r}"):
                    self.status.update(note="rolled_back")
                    continue
                raise
        raise RuntimeError("не удалось подключить ядро")

    def _apply_config(self, cfg_mod: Any, cfg: Dict[str, Any]) -> None:
        pc = cfg_mod.proxy_config
        for key, value in config_store.to_proxy_kwargs(cfg).items():
            if hasattr(pc, key):
                setattr(pc, key, value)
            else:
                log.warning("в новом ядре нет поля proxy_config.%s - пропуск", key)

    # --- основной цикл
    def run(self) -> None:
        crashes: list[float] = []
        reuse = False       # после паузы ядро и конфиг уже загружены - не перезагружаем
        while not self.stop_flag.is_set():
            self.reload_flag.clear()
            cfg = config_store.load()
            if reuse and self.module is not None:
                mod = self.module
                self.status.update(state="starting", error="")
            else:
                setup_logging(bool(cfg.get("verbose")))
                self.status.update(
                    state="starting", error="", host=cfg["host"], port=cfg["port"])
                errs = config_store.validate(cfg)
                if errs:
                    self._fail("Некорректная конфигурация: " + ", ".join(sorted(errs)))
                    return
                try:
                    mod, cfg_mod = self._load_core()
                except Exception as exc:
                    self._fail(f"Ядро не загружено: {exc!r}")
                    return
                self.module = mod
                _censor_all()
                self._apply_config(cfg_mod, cfg)
            reuse = False

            started = time.monotonic()
            error: Optional[BaseException] = None
            try:
                self._run_loop(mod)
            except BaseException as exc:      # noqa: BLE001
                error = exc
            uptime = time.monotonic() - started

            if self.stop_flag.is_set():
                break
            if self.pause_flag.is_set() and error is None:
                self.pause_flag.clear()
                self.resume_event.clear()
                self.status.update(state="paused", active=0)
                log.info("saver: сетевое ядро остановлено (пауза)")
                while not (self.stop_flag.is_set() or self.resume_event.is_set()
                           or self.reload_flag.is_set()):
                    self.resume_event.wait(0.5)
                if self.stop_flag.is_set():
                    break
                reuse = not self.reload_flag.is_set()
                self.resume_event.clear()
                log.info("saver: возобновление (%s)", "из паузы" if reuse else "с перезагрузкой")
                continue
            if self.reload_flag.is_set() and error is None:
                log.info("Перезагрузка по reload.signal")
                self.status.update(restarts=self.status.get("restarts", 0))
                continue

            # --- неожиданное завершение
            if error is not None:
                log.error("Прокси завершился с ошибкой: %r", error)
                log.debug("%s", "".join(traceback.format_exception(
                    type(error), error, error.__traceback__)))
                if isinstance(error, OSError) and error.errno in (
                        errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)):
                    self._fail(f"port_busy:{cfg['port']}")
                    return
                if isinstance(error, PermissionError):
                    self._fail(f"port_denied:{cfg['port']}")
                    return
            else:
                log.error("Прокси завершился без команды остановки")

            if (uptime < EARLY_FAIL_SECONDS
                    and core_loader.active_source() == "github"
                    and core_loader.rollback(
                        f"падение через {uptime:.1f} с после старта: {error!r}")):
                self.status.update(note="rolled_back")
                continue

            now = time.monotonic()
            crashes = [t for t in crashes if now - t < CRASH_WINDOW] + [now]
            if len(crashes) > MAX_CRASHES:
                self._fail(f"crash_loop:{error!r}")
                return
            self.status.update(
                state="starting", restarts=self.status.get("restarts", 0) + 1,
                error=repr(error) if error else "")
            if self.stop_flag.wait(RESTART_DELAY):
                break
        self.status.update(state="stopped")

    def _fail(self, message: str) -> None:
        log.error("ФАТАЛЬНО: %s", message)
        self.fatal = message
        self.status.update(state="error", error=message)

    def _run_loop(self, mod: Any) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ev = asyncio.Event()
        with self._lock:
            self._loop, self._stop_event = loop, ev
        # сигнал мог прийти, пока loop создавался
        if (self.stop_flag.is_set() or self.reload_flag.is_set()
                or self.pause_flag.is_set()):
            ev.set()
        try:
            loop.run_until_complete(mod._run(ev))
        finally:
            with self._lock:
                self._loop = self._stop_event = None
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()


def _censor_all() -> None:
    for h in logging.getLogger().handlers:
        if getattr(h, "_tgwsp", False):
            _censor(h)


# ------------------------------------------------------------ точка входа

def _signal_fresh(path: str, since: float) -> bool:
    try:
        return os.path.getmtime(path) >= since - 1.0
    except OSError:
        return False


def _probe_ready(runner: ProxyRunner, cfg: Dict[str, Any]) -> bool:
    mod = runner.module
    if mod is not None and hasattr(mod, "_server_instance"):
        srv = getattr(mod, "_server_instance", None)
        return bool(srv is not None and getattr(srv, "sockets", None))
    import socket
    try:
        with socket.create_connection(
                (config_store.probe_host(cfg), int(cfg["port"])), 0.3):
            return True
    except OSError:
        return False


def _service_context():
    """Context сервиса (для UsageStats/уведомлений). Только из основного потока сервиса."""
    if not paths.is_android():
        return None
    try:
        from jnius import autoclass  # type: ignore
        return autoclass("org.kivy.android.PythonService").mService
    except Exception:                                  # noqa: BLE001
        log.exception("service context")
        return None


def run() -> int:
    paths.exchange_dir()
    started_at = time.time()
    cfg0 = config_store.load()
    setup_logging(bool(cfg0.get("verbose")))
    log.info("Сервис запущен, pid=%d, аргумент=%r", os.getpid(),
             os.environ.get("PYTHON_SERVICE_ARGUMENT"))

    for stale in (paths.stop_signal_path(), paths.reload_signal_path()):
        if os.path.exists(stale) and not _signal_fresh(stale, started_at):
            paths.remove_quiet(stale)

    libcrypto_shim.install()
    status = Status()
    status.update(state="starting", host=cfg0["host"], port=cfg0["port"])

    runner = ProxyRunner(status)
    runner.start()
    saver_ctl = saver.SaverController(status, runner, ctx=_service_context())

    last_status = 0.0
    try:
        while runner.is_alive():
            now = time.time()
            if _signal_fresh(paths.stop_signal_path(), started_at):
                log.info("Получен stop.signal")
                paths.remove_quiet(paths.stop_signal_path())
                runner.request_stop()
                break
            if _signal_fresh(paths.resume_signal_path(), started_at):
                paths.remove_quiet(paths.resume_signal_path())
                saver_ctl.on_resume_request()
            if _signal_fresh(paths.reload_signal_path(), started_at):
                paths.remove_quiet(paths.reload_signal_path())
                log.info("Получен reload.signal")
                started_at = time.time()
                runner.request_reload()
            if now - last_status >= STATUS_INTERVAL:
                last_status = now
                fields = _collect_stats()
                if status.get("state") == "starting" and runner.is_alive():
                    cfg = config_store.load()
                    if _probe_ready(runner, cfg) and not runner.fatal:
                        fields["state"] = "running"
                        fields["error"] = ""
                if status.get("state") in ("running", "starting", "paused"):
                    status.update(**fields)
            try:
                saver_ctl.tick()
            except Exception:                           # noqa: BLE001
                log.exception("saver tick")
            time.sleep(POLL_INTERVAL)

        runner.join(STOP_JOIN_TIMEOUT)
        if runner.is_alive():
            log.warning("Поток прокси не завершился за %.0f с", STOP_JOIN_TIMEOUT)
    except BaseException:       # noqa: BLE001
        log.error("Сбой супервизора: %s", traceback.format_exc())
        runner.request_stop()
        status.update(state="error", error="supervisor crash")
        raise
    finally:
        if runner.fatal:
            status.update(state="error", error=runner.fatal)
        elif status.get("state") != "error":
            status.update(state="stopped")
    log.info("Сервис остановлен")
    return 0
