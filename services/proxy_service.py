"""Точка входа Android Foreground Service (python-for-android).

p4a запускает этот файл в отдельном процессе. Весь код - в src/core/service_runner.py.
"""
import os
import sys


def _bootstrap_paths():
    here = None
    try:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    except NameError:
        pass
    candidates = [here, os.environ.get("ANDROID_APP_PATH"),
                  os.environ.get("ANDROID_ARGUMENT"), os.getcwd()]
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "src", "core")):
            if c not in sys.path:
                sys.path.insert(0, c)
            return c
    return None


_bootstrap_paths()

from src.core import service_runner  # noqa: E402

if __name__ == "__main__":
    service_runner.run()
else:  # p4a может выполнять файл через runpy с другим __name__
    service_runner.run()
