"""Хук python-for-android: добавляет в AndroidManifest.xml компоненты, которых p4a штатно не умеет.

Блоки (вставляются перед </application>, идемпотентно, после генерации манифеста - after_apk_build):
  * ProxyTileService - плитка быстрых настроек;
  * ApkProvider - выдача скачанного APK системному установщику (самообновление приложения).
"""
import os
import re

BLOCKS = [
    ("ProxyTileService", """
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
"""),
    ("ApkProvider", """
        <provider android:name="{package}.ApkProvider"
                  android:authorities="{package}.apkprovider"
                  android:exported="false"
                  android:grantUriPermissions="true" />
"""),
]


def _package(text):
    m = re.search(r'<manifest[^>]*\spackage="([^"]+)"', text)
    return m.group(1) if m else "org.tgwsproxy.tgwsproxy"


def patch_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if "</application>" not in text:
        return False
    pkg, changed = _package(text), False
    for mark, xml in BLOCKS:
        if mark in text:
            continue
        text = text.replace("</application>", xml.format(package=pkg) + "    </application>", 1)
        changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return changed


def after_apk_build(toolchain):
    for p in ("src/main/AndroidManifest.xml", "AndroidManifest.xml"):
        if os.path.exists(p):
            print("[p4a_hook] manifest %s patched: %s" % (p, patch_manifest(p)))
