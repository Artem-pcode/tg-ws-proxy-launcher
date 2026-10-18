"""Хук python-for-android: добавляет в AndroidManifest.xml сервис плитки быстрых настроек.

p4a не умеет добавлять <service> с intent-filter штатно, поэтому после
генерации манифеста (after_apk_build, рабочая папка = dist) вставляем блок
перед </application>. Идемпотентно.
"""
import os

MARK = "ProxyTileService"

SERVICE_XML = """
        <service android:name="{package}.ProxyTileService"
                 android:label="TG WS Proxy"
                 android:icon="@drawable/ic_tile"
                 android:exported="true"
                 android:permission="android.permission.BIND_QUICK_SETTINGS_TILE">
            <intent-filter>
                <action android:name="android.service.quicksettings.action.QS_TILE" />
            </intent-filter>
            <meta-data android:name="android.service.quicksettings.ACTIVE_TILE"
                       android:value="false" />
        </service>
"""


def _package(text):
    import re
    m = re.search(r'<manifest[^>]*\spackage="([^"]+)"', text)
    return m.group(1) if m else "org.tgwsproxy.tgwsproxy"


def patch_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if MARK in text or "</application>" not in text:
        return False
    xml = SERVICE_XML.format(package=_package(text))
    text = text.replace("</application>", xml + "    </application>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def after_apk_build(toolchain):
    for p in ("src/main/AndroidManifest.xml", "AndroidManifest.xml"):
        if os.path.exists(p):
            print("[p4a_hook] manifest %s patched: %s" % (p, patch_manifest(p)))
