import os, shutil, socket, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.core.saver import SaverPolicy, TRAFFIC_ACTIVE_BYTES


def decide(p, t, **kw):
    kw.setdefault("paused", False); kw.setdefault("telegram_fg", False); kw.setdefault("total_bytes", 0)
    return p.decide(t, **kw)[0]


class PolicyTests(unittest.TestCase):
    def test_pauses_only_after_continuous_inactivity(self):
        p = SaverPolicy(300, 0)
        self.assertIsNone(decide(p, 100))
        self.assertIsNone(decide(p, 299))
        self.assertEqual(decide(p, 301), "pause")

    def test_short_minimize_resets_timer(self):
        p = SaverPolicy(300, 0)
        self.assertIsNone(decide(p, 250))                 # свернул 250 с назад
        self.assertIsNone(decide(p, 255, telegram_fg=True))   # вернулся на секунду
        self.assertIsNone(decide(p, 500))                 # таймер пошёл заново с 255 -> 245 с
        self.assertIsNone(decide(p, 554))
        self.assertEqual(decide(p, 556), "pause")

    def test_long_reading_never_pauses(self):
        p = SaverPolicy(300, 0)
        for t in range(0, 7200, 5):
            self.assertIsNone(decide(p, t, telegram_fg=True))

    def test_background_transfer_defers_pause(self):
        p = SaverPolicy(60, 0)
        total = 0
        for t in range(0, 600, 5):
            total += TRAFFIC_ACTIVE_BYTES // 6            # ~идёт загрузка
            self.assertIsNone(decide(p, t, total_bytes=total))
        # передача закончилась -> через таймаут пауза
        acts = [decide(p, 600 + t, total_bytes=total) for t in range(0, 200, 5)]
        self.assertIn("pause", acts)

    def test_resume_when_telegram_returns(self):
        p = SaverPolicy(60, 0)
        self.assertIsNone(decide(p, 10, paused=True))
        self.assertEqual(decide(p, 20, paused=True, telegram_fg=True), "resume")
        # после возобновления - полный таймер
        self.assertIsNone(decide(p, 70))
        self.assertEqual(decide(p, 81), "pause")


class ServiceSaverIT(unittest.TestCase):
    """Настоящий сервис: пауза и автовозобновление по «окну Telegram» (файл вместо UsageStats)."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="tgwsp-")
        os.environ["TGWSP_HOME"] = self.home
        from src.core import paths, config_store
        self.paths, self.cs = paths, config_store
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]
        cfg = config_store.default_config()
        cfg.update(port=self.port, battery_saver=True, saver_timeout_min=0.1, saver_debug=True)
        config_store.save(cfg)
        self.fg = os.path.join(self.home, "fg")
        open(self.fg, "w").write("0")
        env = dict(os.environ, TGWSP_HOME=self.home, TGWSP_FAKE_FG=self.fg)
        self.proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "services", "proxy_service.py")],
                                     env=env, cwd=self.home, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def tearDown(self):
        if self.proc.poll() is None:
            self.proc.kill()
        shutil.rmtree(self.home, ignore_errors=True)

    def state(self):
        return (self.paths.read_json(self.paths.status_path(), {}) or {}).get("state")

    def wait(self, state, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if self.state() == state:
                return True
            time.sleep(0.3)
        return False

    def port_open(self):
        try:
            socket.create_connection(("127.0.0.1", self.port), 0.5).close(); return True
        except OSError:
            return False

    def test_pause_and_resume(self):
        self.assertTrue(self.wait("running", 25))
        self.assertTrue(self.port_open())
        open(self.fg, "w").write("1")                      # Telegram на экране
        time.sleep(9)                                      # дольше таймаута (6 с) - паузы быть не должно
        self.assertEqual(self.state(), "running")
        open(self.fg, "w").write("0")                      # свернули
        self.assertTrue(self.wait("paused", 25), self.state())
        time.sleep(0.5)
        self.assertFalse(self.port_open())                 # порт закрыт - ядро остановлено
        open(self.fg, "w").write("1")                      # открыли Telegram
        self.assertTrue(self.wait("running", 15), self.state())
        self.assertTrue(self.port_open())
        # resume.signal тоже работает
        open(self.fg, "w").write("0")
        self.assertTrue(self.wait("paused", 25))
        from src.core import service_controller
        service_controller.resume()
        self.assertTrue(self.wait("running", 15))
        self.paths.touch(self.paths.stop_signal_path())
        self.assertEqual(self.proc.wait(timeout=20), 0)
        log = open(self.paths.log_path(), encoding="utf-8").read()
        self.assertIn("saver: ПАУЗА", log); self.assertIn("saver: ВОЗОБНОВЛЕНО", log)
        self.assertIn("saver-debug:", log)


if __name__ == "__main__":
    unittest.main()


class StaleStatusBug(unittest.TestCase):
    def test_fresh_running_status_with_dead_port_is_not_running(self):
        home = tempfile.mkdtemp(prefix="tgwsp-"); os.environ["TGWSP_HOME"] = home
        try:
            from src.core import paths, service_controller as sc, config_store as cs
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
            cfg = cs.default_config(); cfg["port"] = port
            # сервис «умер» только что: статус свежий и «running», порт закрыт
            paths.write_json_atomic(paths.status_path(), {"state": "running", "updated": time.time()})
            self.assertTrue(sc.status_reader.read()["alive"])          # старое поведение поверило бы
            self.assertFalse(sc.is_really_running(cfg))                # новое - нет
            # а если порт реально слушает - считаем работающим
            srv = socket.socket(); srv.bind(("127.0.0.1", port)); srv.listen(1)
            try:
                self.assertTrue(sc.is_really_running(cfg))
            finally:
                srv.close()
        finally:
            shutil.rmtree(home, ignore_errors=True)
