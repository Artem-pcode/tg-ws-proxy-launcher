"""Сценарий клика по ярлыку (ТЗ 4.4 / 9.2), без привязки к UI.

Что важно (исправление бага «с первого раза прокси не стартует»):
* «работает» по status.json недостаточно - проверяем, что порт реально открыт
  (после закрытия приложения файл статуса ещё несколько секунд выглядит свежим);
* если сервис не поднялся - повторяем запуск один раз;
* после открытия Telegram проверяем, что прокси жив, и при необходимости поднимаем снова.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Tuple

from . import config_store, service_controller, status_reader, telegram_helper

log = logging.getLogger("tgwsp.launch")

READY_TIMEOUT = 12.0        # холодный старт Python-сервиса на слабом телефоне бывает долгим
RETRY_AFTER = 5.0           # если за это время сервис вообще не отозвался - запустить ещё раз
VERIFY_SECONDS = 3.0        # контроль живости прокси после открытия Telegram


def _ensure_proxy(cfg: Dict[str, Any], on_state: Callable[[str], None]) -> Tuple[bool, str]:
    if service_controller.is_really_running(cfg):
        log.info("прокси уже работает (порт открыт)")
        return True, ""

    errors = config_store.validate(cfg)
    if errors:
        return False, "invalid_config"

    on_state("launching")
    for attempt in (1, 2):
        ok, reason = service_controller.start(cfg)
        log.info("запуск сервиса, попытка %d: ok=%s reason=%s", attempt, ok, reason)
        if not ok:
            return False, reason or "start_failed"
        timeout = RETRY_AFTER if attempt == 1 else READY_TIMEOUT
        if service_controller.wait_ready(cfg, timeout=timeout):
            return True, ""
        st = status_reader.read()
        log.warning("не готов за %.0f с, status=%s", timeout, st.get("state"))
        if st.get("state") == status_reader.ERROR:
            return False, "not_ready"
        if st.get("alive") and attempt == 1:
            # сервис отозвался (starting) - просто ещё грузится, ждём остаток
            if service_controller.wait_ready(cfg, timeout=READY_TIMEOUT - RETRY_AFTER):
                return True, ""
            return False, "not_ready"
    return False, "not_ready"


def run(cfg: Dict[str, Any], on_state: Callable[[str], None] = lambda s: None
        ) -> Tuple[bool, str]:
    """-> (ok, reason). reason: '', 'invalid_config', 'start_failed', 'not_ready', 'no_telegram', 'tg_failed'."""
    log.info("клик по ярлыку")
    if not telegram_helper.resolve_package(cfg):
        return False, "no_telegram"

    ok, reason = _ensure_proxy(cfg, on_state)
    if not ok:
        return False, reason

    on_state("opening_telegram")
    if not telegram_helper.launch(cfg):
        return False, "tg_failed"
    log.info("Telegram открыт")

    # страховка: убедиться, что прокси не умер сразу после старта
    deadline = time.time() + VERIFY_SECONDS
    while time.time() < deadline:
        time.sleep(0.5)
        if not service_controller.port_open(cfg):
            log.warning("прокси пропал после открытия Telegram - поднимаю снова")
            ok, reason = _ensure_proxy(cfg, lambda s: None)
            if not ok:
                return False, reason
            break
    return True, ""
