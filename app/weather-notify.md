# 愛知県西部のDiscord天気通知

対象は `230010`（愛知県西部）固定。天気アプリのお気に入りの変更には追従しない。
Issue: `ats030-8vza3`。

朝は既存 `morning-digest.timer` の毎日03:00 JSTに送る。当日の降水確率が50%以上、
最高気温が前日分の予報から5℃以上変化、または注意報がある日に天気欄を追加する。
初日は比較データがないため気温を表示する。比較は実測気温ではない。
予報取得に失敗したら既存の日報・RSS通知を続け、比較用データは更新しない。

`weather-notify.timer` は5分ごとに気象庁の警報JSONを確認する。
初回の発表中警報、新しい種類、特別警報への切り替わりを既存Webhookへ送る。
注意報や解除だけでは随時通知しない。解除後の再発表は再び送る。
取得失敗時と送信失敗時は状態を維持し、次回に再試行する。
区域単位の通知なので市区町村別の対象は通知内の気象庁リンクで確認する。

状態は `~/data/weather-notify/`。警報はロックで同時実行を防ぎ、JSONは原子的に置換する。
Discordが受理した直後にプロセスが停止した場合、次回に同じ通知が届く可能性はある。

検証（外部送信なし）:

```bash
python3 app/weather-notify-selftest.py
python3 app/morning-digest-selftest.py
python3 app/weather_notify.py --dry-run
python3 app/morning-digest.py --dry-run
systemd-analyze --user verify .config/systemd/user/weather-notify.service .config/systemd/user/weather-notify.timer
```

有効化:

```bash
systemctl --user daemon-reload
systemctl --user enable --now weather-notify.timer
```

停止・復旧:

```bash
systemctl --user disable --now weather-notify.timer
```

朝の天気欄も停止する場合は `morning-digest.py` の天気連携変更を戻す。
状態ファイルを消すと、次の実行は初回として発表中の警報を再送する。
