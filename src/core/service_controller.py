"""Запуск/остановка сервиса со стороны UI-процесса."""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple

from . import config_store, paths, status_reader

log = logging.getLogger("tgwsp.controller")

SERVICE_NAME = "Proxysvc"       # services = proxysvc:... -> ServiceProxysvc
_desktop_proc: Optional[subprocess.Popen] = None


# ------------------------------------------------------------ Android-мост

_svc_cache = None


def _resolve_service_class():
    from jnius import autoclass  # type: ignore
    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    cls = autoclass(activity.getPackageName() + ".Service" + SERVICE_NAME)
    return activity, cls


def _run_on_main(fn):
    """Выполнить fn в главном потоке Kivy и вернуть результат.

    PyJNIus в фоновых потоках использует системный ClassLoader, который не видит
    классы приложения (ServiceProxysvc) -> ClassNotFoundException.
    """
    import threading
    if threading.current_thread() is threading.main_thread():
        return fn()
    from kivy.clock import Clock  # type: ignore
    box, done = {}, threading.Event()

    def work(_dt):
        try:
            box["r"] = fn()
        except BaseException as exc:                  # noqa: BLE001
            box["e"] = exc
        done.set()

    Clock.schedule_once(work, 0)
    if not done.wait(10):
        raise TimeoutError("main thread did not respond")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _java_service_class():
    global _svc_cache
    if _svc_cache is None:
        _svc_cache = _run_on_main(_resolve_service_class)
    return _svc_cache


def preload() -> None:
    """Вызвать из главного потока при старте приложения."""
    if not paths.is_android():
        return
    try:
        _java_service_class()
    except Exception:                                  # noqa: BLE001
        log.exception("preload service class")


def _android_start(arg: str) -> None:
    activity, cls = _java_service_class()
    _run_on_main(lambda: cls.start(activity, arg))


def _android_stop() -> None:
    activity, cls = _java_service_class()
    _run_on_main(lambda: cls.stop(activity))


# --------------------------------------------------------------- публичное

def is_running() -> bool:
    return status_reader.is_alive()


def port_open(cfg: Dict[str, Any], timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(
                (config_store.probe_host(cfg), int(cfg["port"])), timeout=timeout):
            return True
    except OSError:
        return False


def resume() -> None:
    """Вернуть прокси из паузы режима экономии."""
    paths.touch(paths.resume_signal_path())


def is_really_running(cfg: Dict[str, Any]) -> bool:
    """Прокси реально принимает соединения (а не только 'так написано в status.json').

    Файл статуса остаётся «свежим» ещё несколько секунд после гибели сервиса
    (например, когда систему убила приложение при закрытии из «недавних»),
    поэтому доверять ему одному нельзя.
    """
    st = status_reader.read()
    return st.get("state") == status_reader.RUNNING and port_open(cfg)


def start(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """Сохранить конфиг и запустить сервис. -> (ok, error_code)."""
    global _desktop_proc
    errors = config_store.validate(cfg)
    if errors:
        return False, "invalid_config"
    config_store.save(cfg)
    st = status_reader.read()
    if st.get("alive"):
        if st.get("state") == status_reader.PAUSED:
            resume()
            return True, ""
        if st.get("state") == status_reader.STARTING:
            return True, ""
        if st.get("state") == status_reader.RUNNING:
            if port_open(cfg):
                return True, ""
            # статус «работает», а порт закрыт: сервис мёртв или завис - перезапускаем
            log.warning("status=running, но порт %s закрыт - перезапуск сервиса", cfg.get("port"))
            if paths.is_android():
                try:
                    _android_stop()
                    time.sleep(0.7)
                except Exception:                      # noqa: BLE001
                    log.exception("stop before restart")

    paths.remove_quiet(paths.stop_signal_path())
    paths.remove_quiet(paths.reload_signal_path())
    # сразу показываем "запускается", не дожидаясь первой записи сервиса
    paths.write_json_atomic(paths.status_path(), {
        "state": "starting", "updated": time.time(), "pid": 0,
        "host": cfg.get("host"), "port": cfg.get("port"),
    })
    try:
        if paths.is_android():
            _android_start(paths.config_path())
        else:
            script = os.path.join(paths.app_dir(), "services", "proxy_service.py")
            _desktop_proc = subprocess.Popen(
                [sys.executable, script],
                env=dict(os.environ, PYTHON_SERVICE_ARGUMENT=paths.config_path()))
    except Exception as exc:                      # noqa: BLE001
        log.exception("не удалось запустить сервис")
        paths.write_json_atomic(paths.status_path(), {
            "state": "error", "updated": time.time(), "error": repr(exc)})
        return False, "start_failed"
    return True, ""


def stop(timeout: float = 6.0) -> bool:
    """Записать stop.signal и дождаться остановки; при неудаче - жёстко."""
    global _desktop_proc
    if not status_reader.is_alive():
        return True
    paths.touch(paths.stop_signal_path())
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not status_reader.is_alive():
            _finish_stop()
            return True
        time.sleep(0.2)
    log.warning("сервис не остановился по сигналу - принудительная остановка")
    _finish_stop(force=True)
    return not status_reader.is_alive()


def _finish_stop(force: bool = False) -> None:
    global _desktop_proc
    if paths.is_android():
        try:
            _android_stop()
        except Exception:                          # noqa: BLE001
            log.exception("Service.stop не удался")
    elif _desktop_proc is not None:
        try:
            if force:
                _desktop_proc.kill()
            else:
                _desktop_proc.wait(timeout=3)
        except Exception:                          # noqa: BLE001
            _desktop_proc.kill()
        _desktop_proc = None
    if force:
        paths.write_json_atomic(paths.status_path(), {
            "state": "stopped", "updated": time.time()})


def reload() -> None:
    """Попросить работающий сервис перечитать конфиг и ядро (без остановки процесса)."""
    if status_reader.is_alive():
        paths.touch(paths.reload_signal_path())


def restart(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    config_store.save(cfg)
    if status_reader.is_alive():
        reload()
        return True, ""
    return start(cfg)


def wait_ready(cfg: Dict[str, Any], timeout: float = 5.0, interval: float = 0.2,
               cancel: Optional[Callable[[], bool]] = None) -> bool:
    """Опрашивать 127.0.0.1:{port} до готовности (ТЗ 4.4). Ошибка сервиса - сразу False."""
    host, port = config_store.probe_host(cfg), int(cfg["port"])
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel and cancel():
            return False
        st = status_reader.read()
        if st.get("state") == status_reader.ERROR:
            return False
        if st.get("state") == status_reader.PAUSED:
            resume()
        if st.get("state") == status_reader.RUNNING or st.get("state") == status_reader.STARTING:
            # статус "running" пишется раз в 2 с, поэтому дополнительно пробуем порт
            try:
                with socket.create_connection((host, port), timeout=0.3):
                    return True
            except OSError:
                pass
        time.sleep(interval)
    return False
