import ast, os, re, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.core import bg_status as b


class Evaluate(unittest.TestCase):
    def test_old_android(self):
        self.assertEqual(b.evaluate(30, None, None, False)["overall"], "not_needed")

    def test_applied_full(self):
        self.assertEqual(b.evaluate(34, "false", "2147483647", True)["overall"], "applied")

    def test_applied_max_unreadable(self):
        r = b.evaluate(34, "false", None, False)
        self.assertEqual((r["max"], r["overall"]), ("unknown", "applied"))

    def test_not_applied(self):
        self.assertEqual(b.evaluate(34, None, "32", True)["overall"], "not_applied")
        self.assertEqual(b.evaluate(34, None, None, False)["overall"], "not_applied")

    def test_partial(self):
        self.assertEqual(b.evaluate(34, "false", "32", True)["overall"], "partial")
        self.assertEqual(b.evaluate(34, None, "2147483647", True)["overall"], "partial")

    def test_android12_only_max(self):
        self.assertEqual(b.evaluate(31, None, "2147483647", True)["overall"], "applied")

    def test_commands(self):
        c = b.commands("a.b.c")
        self.assertTrue(all(x.startswith("adb shell") for x in c))
        self.assertIn("a.b.c", c[-1])


class TilePackaging(unittest.TestCase):
    def test_hook_patches_manifest(self):
        sys.path.insert(0, ROOT)
        import p4a_hook
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "AndroidManifest.xml")
            open(p, "w").write('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="x.y"><application></application></manifest>')
            self.assertTrue(p4a_hook.patch_manifest(p))
            self.assertFalse(p4a_hook.patch_manifest(p))        # идемпотентно
            t = open(p).read()
            self.assertIn('x.y.ProxyTileService', t)
            self.assertIn("BIND_QUICK_SETTINGS_TILE", t)
            import xml.dom.minidom as m
            m.parseString(t)

    def test_spec_and_files(self):
        spec = open(os.path.join(ROOT, "buildozer.spec")).read()
        for k in ("android.add_src = java", "p4a.hook = p4a_hook.py", "READ_DEVICE_CONFIG"):
            self.assertIn(k, spec)
        for f in ("java/org/tgwsproxy/tgwsproxy/ProxyTileService.java",
                  "java/org/tgwsproxy/tgwsproxy/TileHelper.java", "res/drawable/ic_tile.xml"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, f)), f)

    def test_java_matches_python_protocol(self):
        j = open(os.path.join(ROOT, "java/org/tgwsproxy/tgwsproxy/ProxyTileService.java")).read()
        for name in ("status.json", "config.json", "stop.signal", "reload.signal"):
            self.assertIn(name, j)
        from src.core import paths
        self.assertEqual((paths.CONFIG_FILE, paths.STATUS_FILE, paths.STOP_SIGNAL, paths.RELOAD_SIGNAL),
                         ("config.json", "status.json", "stop.signal", "reload.signal"))
        from src.core import status_reader as sr
        self.assertEqual(sr.STALE_AFTER, 5.0)
        self.assertIn("STALE_AFTER = 5.0", j)
        self.assertEqual(j.count("{") , j.count("}"))


if __name__ == "__main__":
    unittest.main()
