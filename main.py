"""TG WS Proxy Launcher - точка входа Kivy (UI-процесс)."""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

os.environ.setdefault("KIVY_NO_ARGS", "1")

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s")


def _setup_file_log():
    try:
        import logging.handlers
        from src.core import paths
        h = logging.handlers.RotatingFileHandler(
            paths.launcher_log_path(), maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s",
                                         "%Y-%m-%d %H:%M:%S"))
        logging.getLogger().addHandler(h)
    except Exception:
        pass


def main():
    _setup_file_log()
    from src.ui.app import TgWsProxyApp
    TgWsProxyApp().run()


if __name__ == "__main__":
    main()
