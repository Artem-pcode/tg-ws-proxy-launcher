package org.tgwsproxy.tgwsproxy;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileNotFoundException;

/**
 * Отдаёт системному установщику скачанный APK из files/tgwsproxy/app_update/.
 * Без зависимостей (androidx). Доступ только к *.apk в этой папке.
 */
public class ApkProvider extends ContentProvider {
    private File resolve(Uri uri) throws FileNotFoundException {
        String name = uri.getLastPathSegment();
        if (name == null || name.contains("/") || name.contains("..") || !name.endsWith(".apk")) {
            throw new FileNotFoundException("bad name");
        }
        try {
            File dir = new File(new File(getContext().getFilesDir(), "tgwsproxy"), "app_update");
            File f = new File(dir, name).getCanonicalFile();
            if (!f.getParentFile().equals(dir.getCanonicalFile()) || !f.isFile()) {
                throw new FileNotFoundException("not found");
            }
            return f;
        } catch (java.io.IOException e) {
            throw new FileNotFoundException("io");
        }
    }

    @Override public boolean onCreate() { return true; }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    @Override public String getType(Uri uri) { return "application/vnd.android.package-archive"; }

    @Override public Cursor query(Uri uri, String[] projection, String selection,
                                  String[] selectionArgs, String sortOrder) {
        try {
            File f = resolve(uri);
            MatrixCursor c = new MatrixCursor(new String[]{"_display_name", "_size"});
            c.addRow(new Object[]{f.getName(), f.length()});
            return c;
        } catch (FileNotFoundException e) {
            return null;
        }
    }

    @Override public Uri insert(Uri uri, ContentValues values) { return null; }
    @Override public int delete(Uri uri, String selection, String[] selectionArgs) { return 0; }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) { return 0; }
}
