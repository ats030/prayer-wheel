package jp.ikimononote.original;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public final class SetupActivity extends Activity {
    private TextView status;

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
        Button site = new Button(this);
        site.setText("Braveで生きものノートを開く");
        site.setOnClickListener(v -> {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse("https://ikimono-note-736831430371.asia-northeast1.run.app/"));
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
}
