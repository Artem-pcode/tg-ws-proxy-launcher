package org.tgwsproxy.tgwsproxy;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.util.Locale;

/**
 * Плитка быстрых настроек: включает/выключает ВЕСЬ сервис приложения
 * (ServiceProxysvc: прокси + режим экономии), а не просто сокет.
 *
 * Состояние берётся из status.json, который пишет Python-сервис
 * (то же самое, что видит экран «Статус»). Пока шторка открыта, плитка
 * опрашивает файл раз в секунду, поэтому всегда синхронна с приложением.
 * Обмен с Python - теми же файлами (config.json, stop.signal ...).
 */
public class ProxyTileService extends TileService {
    private static final double STALE_AFTER = 5.0;
    private static final long POLL_MS = 1000;
    private static final long FORCE_STOP_MS = 6000;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean listening = false;
    private long optimisticUntil = 0;       // «запускается» сразу после нажатия
    private boolean optimisticOn = false;

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (!listening) return;
            refresh();
            handler.postDelayed(this, POLL_MS);
        }
    };

    // ------------------------------------------------------------ жизненный цикл

    @Override public void onTileAdded() { super.onTileAdded(); refresh(); }

    @Override public void onStartListening() {
        super.onStartListening();
        listening = true;
        refresh();
        handler.removeCallbacks(poll);
        handler.postDelayed(poll, POLL_MS);
    }

    @Override public void onStopListening() {
        listening = false;
        handler.removeCallbacks(poll);
        super.onStopListening();
    }

    @Override public void onClick() {
        super.onClick();
        try {
            if (readState().alive) stopProxy(); else startProxy();
        } catch (Throwable t) {
            openApp();
        }
        refresh();
    }

    // ------------------------------------------------------------ состояние

    private static final class State {
        boolean alive;
        String state = "stopped";
    }

    private File exchangeDir() {
        return new File(new File(getFilesDir(), "tgwsproxy"), "proxy");
    }

    private static String readFile(File f) {
        try (FileInputStream in = new FileInputStream(f)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        } catch (Throwable t) {
            return null;
        }
    }

    private State readState() {
        State s = new State();
        String txt = readFile(new File(exchangeDir(), "status.json"));
        if (txt == null) return s;
        try {
            JSONObject o = new JSONObject(txt);
            String st = o.optString("state", "stopped");
            double age = System.currentTimeMillis() / 1000.0 - o.optDouble("updated", 0);
            boolean live = st.equals("starting") || st.equals("running") || st.equals("paused");
            if (live && age <= STALE_AFTER) {
                s.alive = true;
                s.state = st;
            } else if (st.equals("error") && age <= 60) {
                s.state = "error";
            }
        } catch (Throwable ignored) {
        }
        return s;
    }

    private boolean russian() {
        String lang = "auto";
        String txt = readFile(new File(exchangeDir(), "config.json"));
        if (txt != null) {
            try { lang = new JSONObject(txt).optString("lang", "auto"); } catch (Throwable ignored) { }
        }
        if (lang.equals("ru")) return true;
        if (lang.equals("en")) return false;
        return Locale.getDefault().getLanguage().equals("ru");
    }

    private void refresh() {
        Tile tile = getQsTile();
        if (tile == null) return;
        State s = readState();
        boolean ru = russian();
        boolean on = s.alive;
        String state = s.state;
        if (!on && System.currentTimeMillis() < optimisticUntil) {
            on = optimisticOn;
            state = optimisticOn ? "starting" : "stopped";
        } else if (s.alive != optimisticOn) {
            optimisticUntil = 0;
        }
        String sub;
        switch (state) {
            case "starting": sub = ru ? "Запуск…" : "Starting…"; break;
            case "running": sub = ru ? "Включён" : "On"; break;
            case "paused": sub = ru ? "Пауза (экономия)" : "Paused (saver)"; break;
            case "error": sub = ru ? "Ошибка" : "Error"; break;
            default: sub = ru ? "Выключен" : "Off";
        }
        tile.setLabel("TG WS Proxy");
        tile.setState(on ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        if (Build.VERSION.SDK_INT >= 29) tile.setSubtitle(sub);
        try {
            int id = getResources().getIdentifier("ic_tile", "drawable", getPackageName());
            if (id != 0) tile.setIcon(Icon.createWithResource(this, id));
        } catch (Throwable ignored) {
        }
        tile.updateTile();
    }

    // ------------------------------------------------------------ действия

    private void startProxy() {
        File dir = exchangeDir();
        File cfg = new File(dir, "config.json");
        if (!cfg.exists()) {                  // приложение ещё ни разу не настраивали
            openApp();
            return;
        }
        new File(dir, "stop.signal").delete();
        new File(dir, "reload.signal").delete();
        // сразу показываем «запускается», как делает UI (иначе плитка мигнёт «выключено»)
        writeFile(new File(dir, "status.json"),
                "{\"state\": \"starting\", \"updated\": " + (System.currentTimeMillis() / 1000.0)
                        + ", \"pid\": 0}");
        optimisticOn = true;
        optimisticUntil = System.currentTimeMillis() + 8000;
        try {
            ServiceProxysvc.start(getApplicationContext(), cfg.getAbsolutePath());
        } catch (Throwable t) {
            // Android 12+ может запретить старт foreground-сервиса из фона - тогда открываем приложение
            optimisticOn = false;
            optimisticUntil = 0;
            writeFile(new File(dir, "status.json"),
                    "{\"state\": \"stopped\", \"updated\": " + (System.currentTimeMillis() / 1000.0) + "}");
            openApp();
        }
    }

    private void stopProxy() {
        final Context app = getApplicationContext();
        final File dir = exchangeDir();
        writeFile(new File(dir, "stop.signal"), "1");
        optimisticOn = false;
        optimisticUntil = System.currentTimeMillis() + 4000;
        handler.postDelayed(new Runnable() {
            @Override public void run() {
                if (readState().alive) {       // сервис не остановился по сигналу - жёстко
                    try { ServiceProxysvc.stop(app); } catch (Throwable ignored) { }
                    writeFile(new File(dir, "status.json"),
                            "{\"state\": \"stopped\", \"updated\": "
                                    + (System.currentTimeMillis() / 1000.0) + "}");
                }
            }
        }, FORCE_STOP_MS);
    }

    private static void writeFile(File f, String text) {
        try {
            File tmp = new File(f.getParentFile(), f.getName() + ".tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(text.getBytes("UTF-8"));
            }
            if (!tmp.renameTo(f)) {
                try (FileOutputStream out = new FileOutputStream(f)) {
                    out.write(text.getBytes("UTF-8"));
                }
            }
        } catch (Throwable ignored) {
        }
    }

    private void openApp() {
        try {
            Intent i = getPackageManager().getLaunchIntentForPackage(getPackageName());
            if (i == null) return;
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (Build.VERSION.SDK_INT >= 34) {
                // метод API 34; компилируем с API 33 - вызываем через рефлексию
                PendingIntent pi = PendingIntent.getActivity(
                        this, 0, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
                TileService.class.getMethod("startActivityAndCollapse", PendingIntent.class)
                        .invoke(this, pi);
            } else {
                startActivityAndCollapse(i);
            }
        } catch (Throwable ignored) {
        }
    }
}
