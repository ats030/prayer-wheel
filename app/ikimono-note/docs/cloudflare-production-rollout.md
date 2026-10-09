# Cloudflare本番化の準備

2026年10月10日（日本時間）。課題は `ats030-paskw` で管理する。
利用者の指定はCloudflare本番化の準備であり、現Cloud Runへの反映ではない。
この文書・検証は公開切替、旧環境停止、実データ移行を実施した記録ではない。

## 現在の配備と判断

| 対象 | 現在の状態 |
| --- | --- |
| 旧公開サイト | https://ikimono-note-736831430371.asia-northeast1.run.app 、health200を確認。維持する |
| Cloudflare検証版 | https://ikimono-note-preview.ats030.workers.dev 、Basic認証付き |
| JavaScript入口 | `e6369a23-5488-4a22-a881-771e3409e625` |
| 非公開Python | `6fee16f6-abc0-41cb-8aee-b7a63fa2dfbb` 、外部URL無効 |
| 入口SHA | `d02c2839f0e15bacdd6c4ff24dee5fbd95191868aec90b4b3eff7d18e9e56be9` |
| D1 | 検証専用 `ikimono-note-preview` 。旧Firestoreの内容をコピーしていない |

本番公開へはまだ切り替えない。候補表示・Googleログイン・Drive保存・別ブラウザでの
読込には利用者の成功報告があり、写真圧縮の合成画像検証も通過した。一方、
全経路の無料適合と旧記録・共有リンクの完全な引継ぎは未確認である。

## データの所在と引継ぎ

| データ | 所在・実装 | URL変更時に必要な処理 |
| --- | --- | --- |
| 端末の記録 | originごとのIndexedDB `species-history` | 新originには自動で移らない。既存Driveバックアップから復元を確認する |
| Drive記録 | 公開モードの `ikimono-note.json` 、`static/assets/gdrive.js` | 同じGoogle設定とアカウントで再接続し、既存ファイルを読めることを確認する |
| 写真 | 端末のBlobとDriveの別ファイル、`drivePhotos` のID | JSONの復元だけでは原寸写真は戻らない。全写真のIDから実際に再取得する |
| APIキー・セッション | originごとのブラウザ保存領域 | APIキーは再入力、Google/Driveは再認証。トークンを移行ファイルに含めない |
| 利用者情報・共有写真 | 旧Firestore、本体のD1 `users` / `shares` | 件数・所有者・共有token・payload・写真の内容を照合する。新tokenの再発行で旧URLを壊さない |
| 既存共有URL | 旧Cloud Run origin | 新DBへのコピーだけではURLを引き継げない。旧URLの提供を維持し、切替時の転送方式を検証する |

`tests/check_origin_migration.mjs` は、実Chromiumの別originに合成バックアップを復元する。
候補のGBIF出典、日時・位置・メモ、小画像、Drive写真ID3件を保持し、新originの既存記録と
併合すること、旧originの記録を残すこと、sessionStorageのAPIキーが渡らないことを確認済み。
Google/Driveへの通信はなく、実利用者の記録や共有データは読み取っていない。

```sh
/home/ats030/.nvm/versions/node/v24.19.0/bin/node app/ikimono-note/tests/check_origin_migration.mjs
```

## 公開条件と実施順

1. **無料枠の適合を検証する。** 通常候補の結果CPU3msだけで判断しない。
   上限2MiBの合成応答では62〜66msを観測した。その後、不要な項目をブラウザで除いた
   経路では6〜10msを観測した。識別本文・finishReason・生成設定・診断のトークン数は保持する。
   大きい本文やAPIへの直接送信は未解決であり、10msに達する観測もある。初回・未キャッシュ・
   最大入力・併用/他AI/再識別・OAuth・共有のCPUとメモリ、日次上限も確認する。
   実測・失敗記録は [計測証拠](cloudflare-preview-production-evidence.md) にある。
   [Cloudflare公式上限](https://developers.cloudflare.com/workers/platform/limits/) に合わせ、
   超過・欠測・版違いを成功扱いしない。
2. **引継ぎを検証する。** まず合成データ、次に対象を限定した実データで、記録・写真・
   共有リンク・所有権・削除の挙動を照合する。旧FirestoreやDriveの実データを扱う前に、
   対象とバックアップ・書込先を確定する。検証用D1を本番DBとして黙って流用しない。
3. **本番構成を確定する。** 本番URL・D1・固定秘密・OAuth戻り先を揃え、非公開Pythonを
   固定Service Binding経由だけで呼ぶ。本番URLはまだ作成・割当していない。
   現入口とPythonは両方でBasic認証とnoindexを強制しているので、入口だけの認証解除では
   本番化できない。検証版の認証は維持し、本番設定を明示的に分けて検証する。
   ログイン必須API、Host制限、CSP、秘密の非配信、出典・ライセンス表記を維持する。
4. **公開候補を検査してから切り替える。** バックエンド→入口の順で同じ版を配備し、
   healthの両SHA照合、Googleログイン、実写真の候補表示、全写真のDrive保存・再読込、
   既存共有リンク、公開ページのcanonical/robots/sitemapを確認する。公開用更新履歴は
   実公開日の日本時間で同時配信する。検証版の履歴をそのまま本番公開済みとして転記しない。

この順序を終えるまではBasic認証の解除、旧サイトからの自動転送、有料プランへの変更、
旧データや旧サービスの削除・停止を行わない。残件の進捗は文書内のチェック印ではなく課題で管理する。

## 切戻し

公開前は検証版だけを以前の整合する入口・Python版へ戻す。片方だけ戻してhealthの
SHA確認を回避しない。D1・Drive・旧Firestoreは削除しない。
公開切替時には、検証済みの旧公開URLへ案内を戻す方法と、切替後に新側へ保存された
記録・共有データを保全する方法を用意する。切戻しを旧DBへの自動上書きと同義にしない。
旧サービスの停止は、引継ぎと新側の安定動作を別途確認した後の作業にする。
