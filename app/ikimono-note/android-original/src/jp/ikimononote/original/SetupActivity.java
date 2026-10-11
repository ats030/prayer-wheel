package jp.ikimononote.original;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.media.ExifInterface;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.ZipInputStream;

public final class SetupActivity extends Activity {
    private TextView status;
    private TextView diagnosticResult;
    private Button diagnosticButton;
    private final ExecutorService diagnosticWorker = Executors.newSingleThreadExecutor();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (24 * getResources().getDisplayMetrics().density);
        column.setPadding(pad, pad * 2, pad, pad);
        scroll.addView(column);
        TextView title = new TextView(this);
        title.setText("生きものノート\n元写真を渡す");
        title.setTextSize(26);
        column.addView(title);
        TextView help = new TextView(this);
        help.setText("写真を選ぶと、撮影場所を残したまま自動でZIPに包みます。手動で圧縮する必要はありません。\n\n最初に、使う写真と、その写真の撮影場所を読み取る許可を設定してください。写真へのアクセスは、選んだ写真だけでも使えます。\n\nその後Braveで生きものノートを開き、「元写真ZIPを選ぶ」→ ファイル選択画面のメニュー →「生きものノート 元写真」から写真を1枚選びます。\n\n端末内のJPEG・PNG・WebP写真に対応します。写真とZIPは各15MBまでです。この補助アプリはネットへ接続せず、写真を端末へ保存しません。選んだZIPは、通常の写真登録と同じくWebサービスへ渡ります。\n");
        help.setTextSize(16);
        column.addView(help);
        status = new TextView(this);
        status.setTextSize(16);
        column.addView(status);
        Button photos = new Button(this);
        photos.setText("1. 使う写真を許可する");
        photos.setOnClickListener(v -> {
            String[] permissions;
            if (Build.VERSION.SDK_INT >= 34) permissions = new String[]{Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED};
            else if (Build.VERSION.SDK_INT >= 33) permissions = new String[]{Manifest.permission.READ_MEDIA_IMAGES};
            else permissions = new String[]{Manifest.permission.READ_EXTERNAL_STORAGE};
            requestPermissions(permissions, 1);
        });
        column.addView(photos);
        Button location = new Button(this);
        location.setText("2. 写真の撮影場所を許可する");
        location.setOnClickListener(v -> requestPermissions(new String[]{Manifest.permission.ACCESS_MEDIA_LOCATION}, 2));
        column.addView(location);
        diagnosticButton = new Button(this);
        diagnosticButton.setText("3. 元写真の位置情報を確認する");
        diagnosticButton.setOnClickListener(v -> {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.setType("application/zip");
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.putExtra(DocumentsContract.EXTRA_INITIAL_URI,
                DocumentsContract.buildDocumentUri(OriginalPhotoProvider.AUTHORITY, "photos"));
            startActivityForResult(intent, 3);
        });
        column.addView(diagnosticButton);
        diagnosticResult = new TextView(this);
        diagnosticResult.setTextSize(16);
        diagnosticResult.setTextIsSelectable(true);
        diagnosticResult.setText("Webで場所を読み取れない場合は、同じ写真を選んで確認してください。\n結果は長押しでコピーできます。\n");
        column.addView(diagnosticResult);
        Button site = new Button(this);
        site.setText("Braveで生きものノートを開く");
        site.setOnClickListener(v -> {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse("https://ikimono-note.ats030.workers.dev/"));
            intent.setPackage("com.brave.browser");
            try { startActivity(intent); }
            catch (android.content.ActivityNotFoundException missing) {
                intent.setPackage(null);
                startActivity(intent);
            }
        });
        column.addView(site);
        setContentView(scroll);
    }

    @Override protected void onResume() {
        super.onResume();
        updateStatus();
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(requestCode, permissions, grants);
        updateStatus();
    }

    private void updateStatus() {
        boolean photos = OriginalPhotoProvider.hasPhotoAccess(this);
        boolean location = checkSelfPermission(Manifest.permission.ACCESS_MEDIA_LOCATION) == PackageManager.PERMISSION_GRANTED;
        status.setText("写真：" + (photos ? "許可済み" : "未許可") + "\n撮影場所：" + (location ? "許可済み" : "未許可")
            + (photos && location ? "\n準備できました。Braveで写真を選んでください。\n" : "\n上の説明を読み、下のボタンで許可してください。\n"));
        getContentResolver().notifyChange(DocumentsContract.buildRootsUri(OriginalPhotoProvider.AUTHORITY), null);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != 3 || resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        if (!OriginalPhotoProvider.AUTHORITY.equals(uri.getAuthority())) {
            diagnosticResult.setText("メニューから「生きものノート 元写真」を選び、同じ写真を確認してください。");
            return;
        }
        diagnosticButton.setEnabled(false);
        diagnosticResult.setText("元写真を確認しています…");
        diagnosticWorker.execute(() -> {
            String result;
            try (InputStream input = getContentResolver().openInputStream(uri);
                 ZipInputStream zip = new ZipInputStream(input)) {
                if (zip.getNextEntry() == null) throw new java.io.IOException();
                ByteArrayOutputStream output = new ByteArrayOutputStream();
                byte[] buffer = new byte[32768];
                int count;
                while ((count = zip.read(buffer)) != -1) {
                    if (output.size() + count > PhotoZip.LIMIT) throw new java.io.IOException();
                    output.write(buffer, 0, count);
                }
                if (output.size() == 0 || zip.getNextEntry() != null) throw new java.io.IOException();
                byte[] photo = output.toByteArray();
                StringBuilder fingerprint = new StringBuilder();
                for (byte value : MessageDigest.getInstance("SHA-256").digest(photo)) fingerprint.append(String.format("%02x", value & 255));
                String gpsStatus;
                try {
                    ExifInterface exif = new ExifInterface(new ByteArrayInputStream(photo));
                    float[] coordinates = new float[2];
                    boolean valid = exif.getLatLong(coordinates)
                        && Float.isFinite(coordinates[0]) && Float.isFinite(coordinates[1])
                        && Math.abs(coordinates[0]) <= 90 && Math.abs(coordinates[1]) <= 180;
                    if (valid) gpsStatus = "原本のGPSあり（Androidで読み取れました）";
                    else if (exif.getAttribute(ExifInterface.TAG_GPS_LATITUDE) != null
                            || exif.getAttribute(ExifInterface.TAG_GPS_LONGITUDE) != null)
                        gpsStatus = "原本のGPSタグはありますが、値を読み取れません";
                    else gpsStatus = "原本のGPSタグなし";
                } catch (Exception invalidExif) { gpsStatus = "Androidで写真のEXIFを解析できません"; }
                result = "原本取得：成功\n位置情報：" + gpsStatus
                    + "\n写真の確認コード：" + fingerprint.substring(0, 16)
                    + "\nWeb画面の確認コードと同じか確認してください。";
            } catch (Exception failure) {
                result = "原本取得：失敗\n写真と撮影場所の許可を確認し、同じ写真を選び直してください。";
            }
            final String message = result;
            runOnUiThread(() -> {
                if (isDestroyed()) return;
                diagnosticResult.setText(message);
                diagnosticButton.setEnabled(true);
            });
        });
    }

    @Override protected void onDestroy() {
        diagnosticWorker.shutdownNow();
        super.onDestroy();
    }
}
