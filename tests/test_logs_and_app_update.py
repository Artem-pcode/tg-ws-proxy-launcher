import io, json, os, re, shutil, sys, tempfile, unittest, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="tgwsp-")
        os.environ["TGWSP_HOME"] = self.home

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)


class LogViewTests(Base):
    def test_tail_and_pages(self):
        from src.core import logview as lv
        f = os.path.join(self.home, "x.log")
        open(f, "w").write("\n".join(f"line {i}" for i in range(1000)) + "\n")
        lines = lv.read_lines(f)
        self.assertEqual(len(lines), 1000)
        self.assertEqual(lv.tail_lines(lines, 3), ["line 997", "line 998", "line 999"])
        p0, n0, pages = lv.page(lines, 0, 150)
        self.assertEqual((n0, pages, p0[-1]), (0, 7, "line 999"))
        last, n, _ = lv.page(lines, 99, 150)          # за пределами -> последняя страница
        self.assertEqual((n, last[0]), (6, "line 0"))
        self.assertEqual(sum(len(lv.page(lines, i, 150)[0]) for i in range(7)), 1000)

    def test_tail_limit_drops_partial_line(self):
        from src.core import logview as lv
        f = os.path.join(self.home, "y.log")
        open(f, "w").write("aaaaaaaaaa\nbbbb\ncccc\n")
        self.assertEqual(lv.read_lines(f, 12), ["bbbb", "cccc"])

    def test_chunks_and_clip(self):
        from src.core import logview as lv
        ch = lv.chunks([str(i) for i in range(30)], 12)
        self.assertEqual([c.count("\n") + 1 for c in ch], [12, 12, 6])
        self.assertEqual(len(lv.clip("x" * 1000)), lv.MAX_LINE)
        self.assertEqual(lv.read_lines("/nonexistent"), [])
        self.assertEqual(lv.page([], 0, 10)[1:], (0, 1))


class ConfigNewKeys(Base):
    def test_log_mb_and_updates(self):
        from src.core import config_store as cs
        cfg = cs.load()
        self.assertEqual(cfg["log_max_mb"], 5.0)
        self.assertTrue(cfg["app_check_updates"])
        cfg["log_max_mb"] = "0.1"
        self.assertIn("log_max_mb", cs.validate(cfg))
        cfg["log_max_mb"] = "2,5"
        self.assertEqual(cs.validate(cfg), {})
        self.assertEqual(cs.normalize(cfg)["log_max_mb"], 2.5)

    def test_service_log_size(self):
        from src.core import service_runner as sr
        h = sr.setup_logging(False, 1.5)
        self.assertEqual(h.maxBytes, int(1.5 * 1024 * 1024))
        import logging
        for x in list(logging.getLogger().handlers):
            if getattr(x, "_tgwsp", False):
                logging.getLogger().removeHandler(x)


def _release(tag, assets):
    return json.dumps({"tag_name": tag, "body": "notes", "html_url": "https://github.com/x/y",
                       "assets": assets}).encode()


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _apk_bytes():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("AndroidManifest.xml", "x")
    return b.getvalue()


class AppUpdateTests(Base):
    URL = "https://github.com/Artem-pcode/tg-ws-proxy-launcher/releases/download/v9.0.0/app-debug.apk"

    def _patch(self, routes):
        from src.core import update_manager as um
        self._orig = um._open
        um._open = lambda url, accept="*/*", timeout=20.0: _Resp(routes[url])

    def tearDown(self):
        from src.core import update_manager as um
        if hasattr(self, "_orig"):
            um._open = self._orig
        super().tearDown()

    def test_version_file_matches_spec(self):
        from src.core import app_update as au
        spec = open(os.path.join(ROOT, "buildozer.spec")).read()
        self.assertEqual(re.search(r"^version\s*=\s*(\S+)", spec, re.M).group(1), au.local_version())

    def test_pick_apk_rejects_foreign_urls_and_names(self):
        from src.core import app_update as au
        good = {"name": "a.apk", "browser_download_url": self.URL, "size": 1}
        self.assertEqual(au.pick_apk([good])["name"], "a.apk")
        self.assertIsNone(au.pick_apk([{"name": "a.apk", "browser_download_url": "https://evil.com/a.apk"}]))
        self.assertIsNone(au.pick_apk([{"name": "../a.apk", "browser_download_url": self.URL}]))
        self.assertIsNone(au.pick_apk([{"name": "a.zip", "browser_download_url": self.URL}]))
        self.assertIsNone(au.pick_apk([]))

    def test_check_newer_and_download(self):
        from src.core import app_update as au
        apk = _apk_bytes()
        assets = [{"name": "app-debug.apk", "browser_download_url": self.URL, "size": len(apk)}]
        self._patch({au.API_LATEST: _release("v9.0.0", assets), self.URL: apk})
        info = au.check_latest()
        self.assertTrue(info["newer"])
        self.assertEqual(info["apk_name"], "app-debug.apk")
        seen = []
        name = au.download(info, seen.append)
        self.assertEqual(name, "app-debug.apk")
        self.assertTrue(os.path.exists(os.path.join(au.update_dir(), name)))
        self.assertTrue(seen and seen[-1] == 1.0)

    def test_not_newer_and_no_apk(self):
        from src.core import app_update as au
        self._patch({au.API_LATEST: _release("v" + au.local_version(), [])})
        info = au.check_latest()
        self.assertFalse(info["newer"])
        self.assertEqual(info["apk_url"], "")
        with self.assertRaises(au.UpdateError):
            au.download(info)

    def test_corrupt_apk_rejected_and_removed(self):
        from src.core import app_update as au
        bad = b"not a zip"
        assets = [{"name": "app-debug.apk", "browser_download_url": self.URL, "size": len(bad)}]
        self._patch({au.API_LATEST: _release("v9.0.0", assets), self.URL: bad})
        info = au.check_latest()
        with self.assertRaises(au.UpdateError) as cm:
            au.download(info)
        self.assertEqual(cm.exception.code, "apk_bad")
        self.assertEqual(os.listdir(au.update_dir()), [])

    def test_size_mismatch(self):
        from src.core import app_update as au
        apk = _apk_bytes()
        assets = [{"name": "app-debug.apk", "browser_download_url": self.URL, "size": len(apk) + 5}]
        self._patch({au.API_LATEST: _release("v9.0.0", assets), self.URL: apk})
        with self.assertRaises(au.UpdateError):
            au.download(au.check_latest())


class AndroidPartsPresent(unittest.TestCase):
    def test_files_and_permissions(self):
        spec = open(os.path.join(ROOT, "buildozer.spec")).read()
        self.assertIn("REQUEST_INSTALL_PACKAGES", spec)
        for f in ("ApkProvider.java", "ApkInstaller.java"):
            t = open(os.path.join(ROOT, "java/org/tgwsproxy/tgwsproxy", f)).read()
            self.assertEqual(t.count("{"), t.count("}"))
        inst = open(os.path.join(ROOT, "java/org/tgwsproxy/tgwsproxy/ApkInstaller.java")).read()
        self.assertIn(".apkprovider/", inst)
        import p4a_hook
        self.assertIn(".apkprovider", dict(p4a_hook.BLOCKS)["ApkProvider"])

    def test_i18n_keys_for_new_ui(self):
        from src.core import i18n
        keys = set(re.findall(r'tr\("([a-z_0-9]+)"', "".join(
            open(os.path.join(ROOT, "src/ui/screens", f)).read()
            for f in ("logs.py", "app_update_card.py", "settings.py"))))
        for lang in ("ru", "en"):
            miss = [k for k in keys if k not in i18n.STRINGS[lang]]
            self.assertEqual(miss, [], lang)


if __name__ == "__main__":
    unittest.main()
