import io, os, shutil, sys, tempfile, unittest, zipfile, json, stat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="tgwsp-")
        os.environ["TGWSP_HOME"] = self.home
    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)


class ConfigTests(Base):
    def test_defaults_valid_and_secret_generated(self):
        from src.core import config_store as cs
        cfg = cs.load()
        self.assertEqual(cs.validate(cfg), {})
        self.assertEqual(len(cfg["secret"]), 32)
        self.assertEqual(cs.load()["secret"], cfg["secret"])   # сохранён

    def test_validation(self):
        from src.core import config_store as cs
        cfg = cs.default_config()
        cfg.update(port="70000", host="bad host", secret="xyz", dc_ip="2:1.2.3\n4:149.154.167.220",
                   buf_kb="1", pool_size="-1", cfproxy_domains="a.com\nnot_a_domain",
                   fake_tls_domain="nodot")
        errs = cs.validate(cfg)
        self.assertEqual(set(errs), {"port", "host", "secret", "dc_ip", "buf_kb", "pool_size",
                                     "cfproxy_domains", "fake_tls_domain"})

    def test_mapping_to_proxy_config(self):
        from src.core import config_store as cs
        cfg = cs.default_config()
        cfg.update(port=2000, buf_kb=128, no_h2=True, no_cfproxy=True, no_secure=True,
                   cfproxy_domains="a.example.com, b.example.com", force_test_dc=True)
        kw = cs.to_proxy_kwargs(cfg)
        self.assertEqual(kw["port"], 2000)
        self.assertEqual(kw["buffer_size"], 128 * 1024)
        self.assertFalse(kw["cfproxy_h2_media"]); self.assertFalse(kw["fallback_cfproxy"])
        self.assertTrue(kw["disable_secure"]); self.assertTrue(kw["force_test_dc"])
        self.assertEqual(kw["dc_redirects"], {2: "149.154.167.220", 4: "149.154.167.220"})
        self.assertEqual(kw["cfproxy_user_domains"], ["a.example.com", "b.example.com"])
        # все поля существуют в ProxyConfig встроенного ядра
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from proxy.config import ProxyConfig
        pc = ProxyConfig()
        for k in kw:
            self.assertTrue(hasattr(pc, k), k)

    def test_tg_uri(self):
        from src.core import config_store as cs
        cfg = cs.default_config(); cfg["secret"] = "ab" * 16; cfg["port"] = 1443
        self.assertEqual(cs.build_tg_uri(cfg), "tg://proxy?server=127.0.0.1&port=1443&secret=dd" + "ab" * 16)
        cfg["fake_tls_domain"] = "example.com"
        self.assertTrue(cs.build_tg_uri(cfg).endswith("secret=ee" + "ab" * 16 + b"example.com".hex()))

    def test_reset_keeps_secret(self):
        from src.core import config_store as cs
        cfg = cs.default_config(); cfg["port"] = 5; s = cfg["secret"]
        r = cs.reset_proxy_settings(cfg)
        self.assertEqual(r["port"], 1443); self.assertEqual(r["secret"], s)


def make_zip(files, root="tg-ws-proxy-1.99.0"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name if name.startswith("/") or name.startswith("..") else f"{root}/{name}", data)
    return buf.getvalue()


GOOD = {
    "proxy/__init__.py": '__version__ = "1.99.0"\nfrom .config import x\n',
    "proxy/config.py": "import asyncio, ssl\nimport httpx\nx = 1\n",
    "README.md": "hi",
}


class UpdateTests(Base):
    def _apply(self, files, tag="v1.99.0"):
        from src.core import update_manager as um, paths
        zp = os.path.join(paths.cache_dir(), "t.zip")
        with open(zp, "wb") as f:
            f.write(make_zip(files) if isinstance(files, dict) else files)
        return um.apply_zip(zp, tag)

    def test_versions(self):
        from src.core import update_manager as um
        self.assertTrue(um.version_gt("v1.11.3", "1.11.2"))
        self.assertFalse(um.version_gt("1.11.2", "v1.11.2"))
        self.assertTrue(um.version_gt("v1.12", "1.11.9"))
        self.assertFalse(um.version_gt("1.2", "1.10"))

    def test_apply_and_backup_and_rollback(self):
        from src.core import update_manager as um, core_loader, paths
        self.assertEqual(core_loader.active_source(), "builtin")
        v = self._apply(GOOD)
        self.assertEqual(v, "1.99.0")
        self.assertEqual(core_loader.active_source(), "github")
        self.assertEqual(core_loader.active_version(), "1.99.0")
        meta = json.load(open(os.path.join(paths.core_current(), "version.json")))
        self.assertEqual(meta["tag"], "v1.99.0"); self.assertEqual(meta["source"], "github")
        self.assertFalse(os.path.exists(os.path.join(paths.core_current(), "README.md")))
        # второе обновление -> предыдущее в backup
        g2 = dict(GOOD); g2["proxy/__init__.py"] = '__version__ = "2.0.0"\n'
        self._apply(g2, "v2.0.0")
        self.assertEqual(core_loader.active_version(), "2.0.0")
        self.assertEqual(um.core_info()["backup_version"], "1.99.0")
        self.assertTrue(um.rollback_manual())
        self.assertEqual(core_loader.active_version(), "1.99.0")
        # ещё откат -> встроенное
        self.assertTrue(um.rollback_manual())
        self.assertEqual(core_loader.active_source(), "builtin")
        self.assertFalse(um.rollback_manual())

    def expect(self, files, code):
        from src.core import update_manager as um, core_loader
        with self.assertRaises(um.UpdateError) as cm:
            self._apply(files)
        self.assertEqual(cm.exception.code, code, cm.exception)
        self.assertEqual(core_loader.active_source(), "builtin")   # ничего не применилось

    def test_rejects_path_traversal(self):
        f = dict(GOOD); f["proxy/../../evil.py"] = "x=1"
        self.expect(f, "unsafe_zip")

    def test_rejects_symlink(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n, d in GOOD.items():
                z.writestr(f"r/{n}", d)
            zi = zipfile.ZipInfo("r/proxy/link.py"); zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(zi, "/etc/passwd")
        self.expect(buf.getvalue(), "unsafe_zip")

    def test_rejects_new_deps(self):
        f = dict(GOOD); f["proxy/config.py"] = "import numpy\n"
        self.expect(f, "needs_new_deps")

    def test_function_level_import_ignored(self):
        f = dict(GOOD); f["proxy/config.py"] = "def main():\n    from utils.x import y\n"
        from src.core import core_loader
        self.assertEqual(self._apply(f), "1.99.0")

    def test_rejects_no_version_syntax_and_missing_pkg(self):
        self.expect({"proxy/__init__.py": "x = 1\n"}, "bad_version")
        self.expect({"proxy/__init__.py": '__version__="1"\ndef (:'}, "bad_source")
        self.expect({"README.md": "x"}, "no_proxy_pkg")
        self.expect(b"not a zip", "bad_zip")

    def test_download_size_limit_and_https_only(self):
        from src.core import update_manager as um, paths
        with self.assertRaises(um.UpdateError) as cm:
            um._open("http://example.com/x.zip")
        self.assertEqual(cm.exception.code, "insecure_url")

        class Resp:
            headers = {"Content-Length": str(um.MAX_ZIP_BYTES + 1)}
            def read(self, n=-1): return b""
            def __enter__(self): return self
            def __exit__(self, *a): pass
        orig = um._open
        um._open = lambda *a, **k: Resp()
        try:
            with self.assertRaises(um.UpdateError) as cm:
                um.download_and_apply("v1.99.0")
            self.assertEqual(cm.exception.code, "too_big")
        finally:
            um._open = orig

    def test_check_latest(self):
        from src.core import update_manager as um
        payload = json.dumps({"tag_name": "v9.9.9", "body": "log", "html_url": "u"}).encode()
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        orig = um._open
        um._open = lambda *a, **k: Resp(payload)
        try:
            r = um.check_latest()
        finally:
            um._open = orig
        self.assertTrue(r["newer"]); self.assertEqual(r["tag"], "v9.9.9"); self.assertEqual(r["changelog"], "log")

    def test_real_flowseal_zip_layout_validates(self):
        """Ядро из присланного архива должно проходить собственную проверку."""
        from src.core import update_manager as um
        self.assertEqual(um.validate_core(os.path.join(ROOT, "src", "proxy")),
                         um.core_loader.bundled_version())


class I18nTests(unittest.TestCase):
    def test_all_keys_used_exist_in_both_languages(self):
        import re
        from src.core.i18n import STRINGS
        self.assertEqual(set(STRINGS["ru"]), set(STRINGS["en"]))
        used = set()
        for dp, _, fs in os.walk(os.path.join(ROOT, "src")):
            if os.sep + "proxy" in dp:
                continue
            for fn in fs:
                if fn.endswith(".py"):
                    used |= set(re.findall(r"""\btr\(\s*['"]([a-z0-9_]+)['"]""", open(os.path.join(dp, fn)).read()))
        used = {k for k in used if not k.endswith("_")}      # динамические префиксы проверяем ниже
        for k in ("lang_auto", "lang_ru", "lang_en", "theme_auto", "theme_light", "theme_dark",
                  "state_stopped", "state_starting", "state_running", "state_error"):
            used.add(k)
        missing = {k for k in used if k not in STRINGS["ru"]}
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()


class BundledVersionFile(unittest.TestCase):
    def test_marker_matches_bundled_core(self):
        from src.core import core_loader
        marker = open(os.path.join(ROOT, "src", "BUNDLED_CORE_VERSION")).read().strip()
        self.assertEqual(marker, core_loader.read_version(os.path.join(ROOT, "src", "proxy")))
