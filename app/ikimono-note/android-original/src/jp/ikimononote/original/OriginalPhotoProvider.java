package jp.ikimononote.original;

import android.Manifest;
import android.content.ContentUris;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Build;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.ParcelFileDescriptor;
import android.os.ProxyFileDescriptorCallback;
import android.os.storage.StorageManager;
import android.system.ErrnoException;
import android.system.OsConstants;
import android.provider.DocumentsContract.Document;
import android.provider.DocumentsContract.Root;
import android.provider.DocumentsProvider;
import android.provider.MediaStore;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.Semaphore;

public final class OriginalPhotoProvider extends DocumentsProvider {
    public static final String AUTHORITY = "jp.ikimononote.original.documents";
    private static final String ROOT = "photos";
    private static final String ZIP = "application/zip";
    private static final String[] ROOT_COLUMNS = {Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID, Root.COLUMN_TITLE,
        Root.COLUMN_SUMMARY, Root.COLUMN_FLAGS, Root.COLUMN_MIME_TYPES, Root.COLUMN_ICON};
    private static final String[] DOCUMENT_COLUMNS = {Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME,
        Document.COLUMN_MIME_TYPE, Document.COLUMN_FLAGS, Document.COLUMN_SIZE, Document.COLUMN_LAST_MODIFIED};
    private final Semaphore openFiles = new Semaphore(3);
    private Handler fileHandler;

    static boolean hasPhotoAccess(Context context) {
        String permission = Build.VERSION.SDK_INT >= 33 ? Manifest.permission.READ_MEDIA_IMAGES : Manifest.permission.READ_EXTERNAL_STORAGE;
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED
            || (Build.VERSION.SDK_INT >= 34 && context.checkSelfPermission(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) == PackageManager.PERMISSION_GRANTED);
    }

    @Override public boolean onCreate() {
        HandlerThread thread = new HandlerThread("original-photo-read");
        thread.start();
        fileHandler = new Handler(thread.getLooper());
        return true;
    }

    private boolean ready() {
        return hasPhotoAccess(getContext()) && getContext().checkSelfPermission(Manifest.permission.ACCESS_MEDIA_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    @Override public Cursor queryRoots(String[] projection) {
        MatrixCursor result = new MatrixCursor(projection == null ? ROOT_COLUMNS : projection);
        MatrixCursor.RowBuilder row = result.newRow();
        row.add(Root.COLUMN_ROOT_ID, ROOT).add(Root.COLUMN_DOCUMENT_ID, ROOT)
            .add(Root.COLUMN_TITLE, "生きものノート 元写真")
            .add(Root.COLUMN_SUMMARY, ready() ? "写真を選ぶと自動ZIP化" : "補助アプリを開いて写真と撮影場所を許可")
            .add(Root.COLUMN_FLAGS, Root.FLAG_SUPPORTS_SEARCH)
            .add(Root.COLUMN_MIME_TYPES, ZIP).add(Root.COLUMN_ICON, R.drawable.icon);
        return result;
    }

    private void addRoot(MatrixCursor result) {
        result.newRow().add(Document.COLUMN_DOCUMENT_ID, ROOT)
            .add(Document.COLUMN_DISPLAY_NAME, "元写真（自動ZIP）")
            .add(Document.COLUMN_MIME_TYPE, Document.MIME_TYPE_DIR).add(Document.COLUMN_FLAGS, 0);
    }

    private Uri photoUri(String documentId) throws FileNotFoundException {
        if (!documentId.matches("photo:[0-9]+")) throw new FileNotFoundException("写真を選び直してください。");
        try { return ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, Long.parseLong(documentId.substring(6))); }
        catch (NumberFormatException invalid) { throw new FileNotFoundException("写真を選び直してください。"); }
    }

    private Cursor photos(Uri uri, String selection, String[] args) {
        return getContext().getContentResolver().query(uri,
            new String[]{MediaStore.Images.Media._ID, MediaStore.Images.Media.DISPLAY_NAME, MediaStore.Images.Media.SIZE, MediaStore.Images.Media.DATE_MODIFIED},
            selection, args, MediaStore.Images.Media.DATE_ADDED + " DESC");
    }

    private void addPhoto(MatrixCursor result, Cursor photo) {
        String name = PhotoZip.safeName(photo.getString(1));
        long zipSize;
        try { zipSize = PhotoZip.size(photo.getLong(2), name); }
        catch (IOException impossible) { return; }
        if (zipSize > PhotoZip.LIMIT || photo.getLong(2) <= 0) return;
        result.newRow().add(Document.COLUMN_DOCUMENT_ID, "photo:" + photo.getLong(0))
            .add(Document.COLUMN_DISPLAY_NAME, name + ".zip")
            .add(Document.COLUMN_MIME_TYPE, ZIP).add(Document.COLUMN_FLAGS, 0)
            .add(Document.COLUMN_SIZE, zipSize).add(Document.COLUMN_LAST_MODIFIED, photo.getLong(3) * 1000);
    }

    @Override public Cursor queryDocument(String documentId, String[] projection) throws FileNotFoundException {
        MatrixCursor result = new MatrixCursor(projection == null ? DOCUMENT_COLUMNS : projection);
        if (ROOT.equals(documentId)) { addRoot(result); return result; }
        if (!ready()) throw new FileNotFoundException("補助アプリで写真と撮影場所を許可してください。");
        try (Cursor photo = photos(photoUri(documentId), null, null)) {
            if (photo == null || !photo.moveToFirst()) throw new FileNotFoundException("この写真は読み取れません。");
            addPhoto(result, photo);
        }
        return result;
    }

    @Override public Cursor queryChildDocuments(String parent, String[] projection, String sortOrder) throws FileNotFoundException {
        if (!ROOT.equals(parent)) throw new FileNotFoundException("フォルダがありません。");
        return listPhotos(projection, null);
    }

    @Override public Cursor querySearchDocuments(String root, String query, String[] projection) throws FileNotFoundException {
        if (!ROOT.equals(root)) throw new FileNotFoundException("フォルダがありません。");
        return listPhotos(projection, query);
    }

    private Cursor listPhotos(String[] projection, String query) {
        MatrixCursor result = new MatrixCursor(projection == null ? DOCUMENT_COLUMNS : projection);
        if (!ready()) return result;
        String selection = MediaStore.Images.Media.SIZE + " BETWEEN 1 AND " + PhotoZip.LIMIT
            + " AND " + MediaStore.Images.Media.MIME_TYPE + " IN ('image/jpeg','image/png','image/webp')";
        String[] args = null;
        if (query != null) { selection += " AND " + MediaStore.Images.Media.DISPLAY_NAME + " LIKE ?"; args = new String[]{"%" + query + "%"}; }
        try (Cursor photos = photos(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, selection, args)) {
            if (photos != null) while (photos.moveToNext()) addPhoto(result, photos);
        } catch (SecurityException revoked) { /* Permission can be revoked while the picker is open. */ }
        return result;
    }

    @Override public ParcelFileDescriptor openDocument(String documentId, String mode, CancellationSignal cancellation) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("写真の書き込みはできません。");
        if (!ready()) throw new FileNotFoundException("補助アプリで写真と撮影場所を許可してください。");
        Uri original = MediaStore.setRequireOriginal(photoUri(documentId));
        String name;
        try (Cursor photo = photos(photoUri(documentId), null, null)) {
            if (photo == null || !photo.moveToFirst()) throw new FileNotFoundException("この写真は読み取れません。");
            name = photo.getString(1);
        }
        if (!openFiles.tryAcquire()) throw new FileNotFoundException("写真を読み取り中です。少し待って選び直してください。");
        try (InputStream input = getContext().getContentResolver().openInputStream(original)) {
            if (input == null) throw new IOException("元写真を読み取れません。");
            if (cancellation != null) cancellation.throwIfCanceled();
            byte[] zip = PhotoZip.create(input, name);
            if (cancellation != null) cancellation.throwIfCanceled();
            // Browsers need size/seek support. A proxy FD provides both without a disk copy.
            return getContext().getSystemService(StorageManager.class).openProxyFileDescriptor(
                ParcelFileDescriptor.MODE_READ_ONLY, new ProxyFileDescriptorCallback() {
                    private byte[] bytes = zip;
                    @Override public long onGetSize() { return bytes.length; }
                    @Override public int onRead(long offset, int size, byte[] data) throws ErrnoException {
                        if (offset < 0 || size < 0) throw new ErrnoException("read", OsConstants.EINVAL);
                        if (offset >= bytes.length) return 0;
                        int count = Math.min(Math.min(size, data.length), bytes.length - (int) offset);
                        System.arraycopy(bytes, (int) offset, data, 0, count);
                        return count;
                    }
                    @Override public void onRelease() { bytes = null; openFiles.release(); }
                }, fileHandler);
        } catch (Exception failed) {
            openFiles.release();
            // Never fall back to a redacted URI or log photographs/coordinates.
            throw new FileNotFoundException("元写真を取得できませんでした。写真と撮影場所の許可を確認してください。");
        }
    }
}
