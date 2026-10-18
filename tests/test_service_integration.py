"""Интеграционный тест: настоящий service_runner + настоящее ядро (десктоп)."""
import json, os, socket, subprocess, sys, tempfile, time, unittest, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServiceIT(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="tgwsp-")
        os.environ["TGWSP_HOME"] = self.home
        from src.core import paths, config_store
        self.paths, self.cs = paths, config_store
        self.port = free_port()
        cfg = config_store.default_config()
        cfg["port"] = self.port
        config_store.save(cfg)
        self.cfg = cfg
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        shutil.rmtree(self.home, ignore_errors=True)

    def start(self):
        env = dict(os.environ, TGWSP_HOME=self.home)
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "services", "proxy_service.py")],
            env=env, cwd=self.home, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def status(self):
        return self.paths.read_json(self.paths.status_path(), {}) or {}

    def wait_state(self, state, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if self.status().get("state") == state:
                return True
            time.sleep(0.2)
        return False

    def test_start_stop(self):
        self.start()
        self.assertTrue(self.wait_state("running"), self.status())
        with socket.create_connection(("127.0.0.1", self.port), 2):
            pass
        st = self.status()
        self.assertEqual(st["core_source"], "builtin")
        self.assertTrue(st["core_version"])
        self.assertIn("total=", st.get("summary", ""))
        # stop.signal
        self.paths.touch(self.paths.stop_signal_path())
        self.assertEqual(self.proc.wait(timeout=20), 0)
        self.assertEqual(self.status()["state"], "stopped")
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", self.port), 1)

    def test_port_busy_is_fatal(self):
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", self.port)); blocker.listen(1)
        try:
            self.start()
            self.assertTrue(self.wait_state("error"), self.status())
            self.assertTrue(self.status()["error"].startswith("port_busy"))
            self.assertEqual(self.proc.wait(timeout=20), 0)
        finally:
            blocker.close()

    def test_reload_applies_new_config(self):
        self.start()
        self.assertTrue(self.wait_state("running"), self.status())
        new_port = free_port()
        cfg = self.cs.load(); cfg["port"] = new_port; self.cs.save(cfg)
        time.sleep(1.2)
        self.paths.touch(self.paths.reload_signal_path())
        end = time.time() + 20; ok = False
        while time.time() < end:
            try:
                socket.create_connection(("127.0.0.1", new_port), 0.5).close(); ok = True; break
            except OSError:
                time.sleep(0.3)
        self.assertTrue(ok, self.status())
        self.paths.touch(self.paths.stop_signal_path())
        self.proc.wait(timeout=20)

    def test_bad_downloaded_core_rolls_back(self):
        # current/ с ядром, которое не импортируется -> откат на встроенное
        cur = os.path.join(self.paths.core_current(), "proxy")
        os.makedirs(cur)
        with open(os.path.join(cur, "__init__.py"), "w") as f:
            f.write('__version__ = "99.0.0"\nraise RuntimeError("broken core")\n')
        self.start()
        self.assertTrue(self.wait_state("running"), self.status())
        st = self.status()
        self.assertEqual(st["core_source"], "builtin")
        self.assertEqual(st.get("note"), "rolled_back")
        self.assertTrue(any(d.startswith("failed_") for d in os.listdir(self.paths.core_root())))
        self.paths.touch(self.paths.stop_signal_path())
        self.proc.wait(timeout=20)


if __name__ == "__main__":
    unittest.main()
