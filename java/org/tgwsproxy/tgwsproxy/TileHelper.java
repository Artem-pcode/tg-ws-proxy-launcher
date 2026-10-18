package org.tgwsproxy.tgwsproxy;

import android.app.StatusBarManager;
import android.content.ComponentName;
import android.content.Context;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.service.quicksettings.TileService;

import java.util.function.Consumer;

/** Вызывается из Python (pyjnius, главный поток): запрос добавить плитку в шторку. */
public class TileHelper {
    /** Android 13+: системный диалог «Добавить плитку?». false - API недоступно. */
    public static boolean requestAdd(Context ctx) {
        if (Build.VERSION.SDK_INT < 33) return false;
        try {
            StatusBarManager sbm = (StatusBarManager) ctx.getSystemService(Context.STATUS_BAR_SERVICE);
            int id = ctx.getResources().getIdentifier("ic_tile", "drawable", ctx.getPackageName());
            sbm.requestAddTileService(
                    new ComponentName(ctx, ProxyTileService.class),
                    "TG WS Proxy",
                    Icon.createWithResource(ctx, id),
                    ctx.getMainExecutor(),
                    new Consumer<Integer>() {
                        @Override public void accept(Integer result) { }
                    });
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /** Попросить систему обновить плитку (если шторка открыта). */
    public static void refresh(Context ctx) {
        try {
            TileService.requestListeningState(ctx, new ComponentName(ctx, ProxyTileService.class));
        } catch (Throwable ignored) {
        }
    }
}
