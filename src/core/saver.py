"""Режим экономии батареи: ставит прокси на паузу, когда Telegram не активен.

Как это работает
----------------
* Активность Telegram определяется ТОЧНО - по событиям UsageStatsManager
  (ACTIVITY_RESUMED / ACTIVITY_PAUSED по каждому окну приложения). Это видит и
  свёрнутое окно, и выключенный экран. Нужен однократный доступ
  «Данные об использовании» (Настройки -> Особые права). Без доступа режим
  экономии НЕ работает (прокси просто остаётся включённым) - так безопаснее,
  чем гадать по косвенным признакам и отключать прокси посреди чтения чата.
* Пауза наступает не сразу: Telegram должен быть неактивен непрерывно
  `saver_timeout_min` минут. Вернулись в Telegram - таймер сбрасывается и
  стартует заново при следующем сворачивании. Поэтому:
    - долгое чтение чата (Telegram на экране) никогда не вызывает паузу;
    - «свернул на секунду» - таймер просто сбросится при возврате.
* Пока идёт заметная передача данных (загрузка/выгрузка файлов в фоне), таймер
  тоже откладывается.
* На паузе сервис остаётся жив, но сетевое ядро остановлено (нет keep-alive
  соединений и пулов - именно они тратят батарею); раз в ~1.5 с проверяется
  только «вышел ли Telegram на экран» - при этом прокси возобновляется сам.
* Своё окно приложения тоже считается «активным» (пока вы смотрите на него, пауза не наступит).
* Отладка (`saver_debug`): постоянное уведомление с живым состоянием и отдельные
  уведомления на каждое событие + строки `saver:` в логе.
"""
from __future__ import annotations

import collections
import logging
import os
import time
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple

from . import config_store, paths

log = logging.getLogger("tgwsp.saver")

# события UsageEvents
EV_RESUMED = 1          # ACTIVITY_RESUMED / MOVE_TO_FOREGROUND
EV_PAUSED = 2           # ACTIVITY_PAUSED / MOVE_TO_BACKGROUND
EV_SCREEN_OFF = 16      # SCREEN_NON_INTERACTIVE
EV_DESTROYED = 24       # ACTIVITY_DESTROYED

TICK_RUNNING = 5.0      # как часто проверять, пока прокси работает
TICK_PAUSED = 1.5       # как часто проверять на паузе (задержка возобновления)
TRAFFIC_WINDOW = 60.0   # окно оценки трафика, с
TRAFFIC_ACTIVE_BYTES = 64 * 1024   # >= столько за окно - считаем «идёт передача»
INITIAL_HISTORY_MS = 12 * 3600 * 1000


# ------------------------------------------------------------------ политика

class SaverPolicy:
    """Чистая логика решений (без Android) - покрыта unit-тестами."""

    def __init__(self, timeout_s: float, now: float) -> None:
        self.timeout_s = timeout_s
        self.last_active = now
        self.samples: Deque[Tuple[float, int]] = collections.deque()
        self.prev_fg: Optional[bool] = None
        self.last_reason = ""
        self.last_traffic = 0

    def mark_active(self, now: float, reason: str = "") -> None:
        self.last_active = now
        if reason:
            self.last_reason = reason

    def traffic_in_window(self, now: float, total_bytes: int) -> int:
        self.samples.append((now, total_bytes))
        while self.samples and now - self.samples[0][0] > TRAFFIC_WINDOW:
            self.samples.popleft()
        return max(0, total_bytes - self.samples[0][1])

    def idle_for(self, now: float) -> float:
        return max(0.0, now - self.last_active)

    def decide(self, now: float, *, paused: bool, telegram_fg: bool,
               total_bytes: int) -> Tuple[Optional[str], str]:
        """-> (action, reason); action: 'pause' | 'resume' | None."""
        events: List[str] = []
        if self.prev_fg is not None and telegram_fg != self.prev_fg:
            events.append("fg" if telegram_fg else "bg")
        self.prev_fg = telegram_fg

        if paused:
            if telegram_fg:
                self.mark_active(now, "telegram_fg")
                self.samples.clear()
                return "resume", "Telegram на экране"
            return None, ""

        traffic = self.traffic_in_window(now, total_bytes)
        self.last_traffic = traffic
        if telegram_fg:
            self.mark_active(now, "telegram_fg")
            return None, ""
        if traffic >= TRAFFIC_ACTIVE_BYTES:
            self.mark_active(now, "traffic")
            return None, ""
        if self.idle_for(now) >= self.timeout_s:
            return "pause", f"Telegram неактивен {int(self.idle_for(now))} с"
        return None, ""


# ----------------------------------------------------------- события Android

class UsageProvider:
    """Интерфейс: telegram_active() -> bool."""

    def available(self) -> bool:                       # есть ли доступ
        return False

    def telegram_active(self, packages: Iterable[str]) -> bool:
        return False


class FileUsageProvider(UsageProvider):
    """Для тестов на ПК: файл TGWSP_FAKE_FG содержит 1 (Telegram на экране) или 0."""

    def __init__(self, path: str) -> None:
        self.path = path

    def available(self) -> bool:
        return True

    def telegram_active(self, packages: Iterable[str]) -> bool:
        try:
            with open(self.path, "r") as fh:
                return fh.read().strip() == "1"
        except OSError:
            return False


class AndroidUsageProvider(UsageProvider):
    def __init__(self, ctx: Any) -> None:
        from jnius import autoclass, cast  # type: ignore
        self._ctx = ctx
        self._autoclass, self._cast = autoclass, cast
        self._usm = cast("android.app.usage.UsageStatsManager",
                         ctx.getSystemService("usagestats"))
        self._event = autoclass("android.app.usage.UsageEvents$Event")()
        self._resumed: Set[Tuple[str, str]] = set()
        self._last_ms = 0
        self._primed = False

    def available(self) -> bool:
        return usage_access_granted(self._ctx)

    def _poll(self) -> None:
        now_ms = int(time.time() * 1000)
        begin = self._last_ms if self._primed else now_ms - INITIAL_HISTORY_MS
        events = self._usm.queryEvents(begin, now_ms + 1000)
        ev = self._event
        last = begin
        while events.hasNextEvent():
            events.getNextEvent(ev)
            ts = int(ev.getTimeStamp())
            etype = int(ev.getEventType())
            key = (str(ev.getPackageName()), str(ev.getClassName()))
            if etype == EV_RESUMED:
                self._resumed.add(key)
            elif etype in (EV_PAUSED, EV_DESTROYED):
                self._resumed.discard(key)
            elif etype == EV_SCREEN_OFF:
                self._resumed.clear()
            last = max(last, ts)
        self._last_ms = max(last, begin)
        self._primed = True

    def telegram_active(self, packages: Iterable[str]) -> bool:
        self._poll()
        wanted = set(packages)
        return any(pkg in wanted for pkg, _cls in self._resumed)


def usage_access_granted(ctx: Any) -> bool:
    """Проверка специального доступа «Данные об использовании» (AppOps)."""
    try:
        from jnius import autoclass, cast  # type: ignore
        aom = cast("android.app.AppOpsManager", ctx.getSystemService("appops"))
        uid = autoclass("android.os.Process").myUid()
        mode = aom.checkOpNoThrow("android:get_usage_stats", uid, ctx.getPackageName())
        return int(mode) == int(autoclass("android.app.AppOpsManager").MODE_ALLOWED)
    except Exception:                                  # noqa: BLE001
        log.exception("usage_access_granted")
        return False


# ---------------------------------------------------------- отладочные уведомления

class DebugNotifier:
    """Уведомления для отладки. На ПК/без прав - только строки в логе."""

    CHANNEL = "tgwsp_saver_debug"
    ONGOING_ID = 9101

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._event_id = 9200
        self._nm = None
        self._ready = False
        if ctx is None:
            return
        try:
            from jnius import autoclass, cast  # type: ignore
            self._autoclass = autoclass
            NM = autoclass("android.app.NotificationManager")
            self._nm = cast("android.app.NotificationManager",
                            ctx.getSystemService("notification"))
            chan = autoclass("android.app.NotificationChannel")(
                self.CHANNEL, "Saver debug", NM.IMPORTANCE_LOW)
            self._nm.createNotificationChannel(chan)
            self._ready = True
        except Exception:                              # noqa: BLE001
            log.exception("DebugNotifier init")

    def _post(self, nid: int, title: str, text: str, ongoing: bool) -> None:
        if not self._ready:
            return
        try:
            B = self._autoclass("android.app.Notification$Builder")
            b = B(self._ctx, self.CHANNEL)
            b.setContentTitle(title)
            b.setContentText(text)
            b.setStyle(self._autoclass("android.app.Notification$BigTextStyle")().bigText(text))
            b.setSmallIcon(self._ctx.getApplicationInfo().icon)
            b.setOngoing(ongoing)
            b.setOnlyAlertOnce(True)
            b.setShowWhen(True)
            self._nm.notify(nid, b.build())
        except Exception:                              # noqa: BLE001
            log.exception("notify")

    def ongoing(self, text: str) -> None:
        self._post(self.ONGOING_ID, "Saver (debug)", text, True)

    def event(self, title: str, text: str) -> None:
        log.info("saver-debug: %s - %s", title, text)
        self._event_id += 1
        if self._event_id > 9300:
            self._event_id = 9201
        self._post(self._event_id, title, time.strftime("%H:%M:%S ") + text, False)

    def clear(self) -> None:
        if self._ready:
            try:
                self._nm.cancel(self.ONGOING_ID)
            except Exception:                          # noqa: BLE001
                pass


# ------------------------------------------------------------------ контроллер

class SaverController:
    """Живёт в основном потоке сервиса; вызывается из его цикла (tick)."""

    def __init__(self, status: Any, runner: Any, ctx: Any = None,
                 provider: Optional[UsageProvider] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.status, self.runner, self.ctx, self.clock = status, runner, ctx, clock
        self.provider = provider
        if self.provider is None:
            fake = os.environ.get("TGWSP_FAKE_FG")
            if fake:
                self.provider = FileUsageProvider(fake)
            elif ctx is not None:
                try:
                    self.provider = AndroidUsageProvider(ctx)
                except Exception:                      # noqa: BLE001
                    log.exception("AndroidUsageProvider")
        self.notifier = DebugNotifier(ctx)
        self._cfg: Dict[str, Any] = {}
        self._cfg_mtime = 0.0
        self._cfg_checked = 0.0
        self.policy = SaverPolicy(300.0, clock())
        self._next_tick = 0.0
        self._was_enabled = False
        self._last_fg: Optional[bool] = None
        self._paused_by_saver = False
        self._no_access_reported = False

    # --- конфиг (перечитываем при изменении файла)
    def _refresh_cfg(self, now: float) -> None:
        if now - self._cfg_checked < 3.0 and self._cfg:
            return
        self._cfg_checked = now
        try:
            mtime = os.path.getmtime(paths.config_path())
        except OSError:
            return
        if mtime != self._cfg_mtime or not self._cfg:
            self._cfg_mtime = mtime
            self._cfg = config_store.load()
            self.policy.timeout_s = max(5.0, float(self._cfg["saver_timeout_min"]) * 60.0)

    def packages(self) -> List[str]:
        from .telegram_helper import KNOWN_PACKAGES
        chosen = self._cfg.get("telegram_package", "auto")
        pkgs = [chosen] if chosen and chosen != "auto" else [p for p, _ in KNOWN_PACKAGES]
        own = self._own_package()
        if own:
            pkgs.append(own)
        return pkgs

    def _own_package(self) -> str:
        try:
            return str(self.ctx.getPackageName()) if self.ctx is not None else ""
        except Exception:                              # noqa: BLE001
            return ""

    # --- внешние события
    def on_resume_request(self) -> None:
        """Явная просьба вернуть прокси (ярлык, кнопка в приложении)."""
        self.policy.mark_active(self.clock(), "user_request")
        self.runner.request_resume()
        self._paused_by_saver = False
        self._event("Возобновление", "по запросу пользователя")

    def _debug(self) -> bool:
        return bool(self._cfg.get("saver_debug"))

    def _event(self, title: str, text: str) -> None:
        log.info("saver: %s - %s", title, text)
        if self._debug():
            self.notifier.event(title, text)

    # --- основной шаг
    def tick(self) -> None:
        now = self.clock()
        if now < self._next_tick:
            return
        state = self.status.get("state")
        self._next_tick = now + (TICK_PAUSED if state == "paused" else TICK_RUNNING)
        self._refresh_cfg(now)
        enabled = bool(self._cfg.get("battery_saver"))

        if not enabled:
            if self._was_enabled:
                self._was_enabled = False
                self.notifier.clear()
                if state == "paused":
                    self.runner.request_resume()
                    self._event("Экономия выключена", "прокси возобновлён")
            return
        if not self._was_enabled:
            self._was_enabled = True
            self.policy.mark_active(now, "enabled")
            self._event("Экономия включена",
                        f"пауза после {self.policy.timeout_s / 60:g} мин неактивности Telegram")

        if self.provider is None or not self.provider.available():
            if not self._no_access_reported:
                self._no_access_reported = True
                self._event("Экономия НЕ работает", "нет доступа «Данные об использовании»")
            if self._debug():
                self.notifier.ongoing("Нет доступа к данным об использовании - экономия не активна")
            return
        self._no_access_reported = False

        if state not in ("running", "paused"):
            self.policy.mark_active(now)             # запуск/перезапуск - даём полный таймер
            return

        try:
            fg = self.provider.telegram_active(self.packages())
        except Exception:                              # noqa: BLE001
            log.exception("telegram_active")
            return
        if self._last_fg is not None and fg != self._last_fg:
            self._event("Telegram на экране" if fg else "Telegram ушёл с экрана",
                        "таймер сброшен" if fg else
                        f"пауза через {self.policy.timeout_s / 60:g} мин, если не вернётесь")
        self._last_fg = fg

        total = int(self.status.get("bytes_up", 0)) + int(self.status.get("bytes_down", 0))
        action, reason = self.policy.decide(
            now, paused=(state == "paused"), telegram_fg=fg, total_bytes=total)

        if action == "pause":
            self._paused_by_saver = True
            self.runner.request_pause()
            self._event("ПАУЗА", f"прокси остановлен: {reason}")
        elif action == "resume":
            self._paused_by_saver = False
            self.runner.request_resume()
            self._event("ВОЗОБНОВЛЕНО", reason)

        if self._debug():
            idle = self.policy.idle_for(now)
            left = max(0.0, self.policy.timeout_s - idle)
            traffic = self.policy.last_traffic if state != "paused" else 0
            self.notifier.ongoing(
                f"Telegram: {'на экране' if fg else 'не на экране'}\n"
                f"прокси: {state}\n"
                f"неактивен: {int(idle)} с, до паузы: {int(left)} с (таймаут {int(self.policy.timeout_s)} с)\n"
                f"трафик за {int(TRAFFIC_WINDOW)} с: {traffic // 1024} КБ\n"
                f"последняя причина активности: {self.policy.last_reason or '-'}")
