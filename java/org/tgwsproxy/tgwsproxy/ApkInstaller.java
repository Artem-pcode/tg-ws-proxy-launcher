package org.tgwsproxy.tgwsproxy;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;

/** Вызывается из Python (pyjnius, главный поток): запуск системной установки скачанного APK. */
public class ApkInstaller {
    public static final int STARTED = 0;
    public static final int NEED_PERMISSION = 1;
    public static final int FAILED = 2;

    /** name - имя файла в files/tgwsproxy/app_update/. */
    public static int install(Context ctx, String name) {
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                PackageManager pm = ctx.getPackageManager();
                if (!pm.canRequestPackageInstalls()) {
                    Intent s = new Intent("android.settings.MANAGE_UNKNOWN_APP_SOURCES",
                            Uri.parse("package:" + ctx.getPackageName()));
                    s.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    ctx.startActivity(s);
                    return NEED_PERMISSION;
                }
            }
            Uri uri = Uri.parse("content://" + ctx.getPackageName() + ".apkprovider/" + Uri.encode(name));
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(uri, "application/vnd.android.package-archive");
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            ctx.startActivity(i);
            return STARTED;
        } catch (Throwable t) {
            return FAILED;
        }
    }

    public static boolean canInstall(Context ctx) {
        return Build.VERSION.SDK_INT < 26 || ctx.getPackageManager().canRequestPackageInstalls();
    }
}
