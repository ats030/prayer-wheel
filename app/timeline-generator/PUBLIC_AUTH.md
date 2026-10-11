# 公開生成APIの保護

更新日: 2026-10-11。共通処理: ats030-xu1or。Googleログイン接続: ats030-cxaz0。

一般公開の本人確認はGoogleログインを使う方針です。Googleアカウントの識別には変更されない `sub` を用い、メールアドレスを受付の所有者IDにしません。[GoogleのOpenID Connect仕様](https://developers.google.com/identity/openid-connect/openid-connect)を参照してください。

`public_security.py` は認証後の共通処理です。`google_login.py` と `public_server.py` にGoogleのサーバーフローと独立したログイン用HTTP入口を実装しました。公開URL・OAuthクライアントは未設定のため、実アカウントでの認証と外部配備は未検証です。生成ワーカーは接続していません。私用の `server.py` は変更しておらず、利用者別の公開認証を持たないままです。私用サーバーを公開サービスの上流に接続してはいけません。

## セッション

Googleの応答をサーバー側で検証したコールバックだけが `issue_verified(issuer, subject)` を呼びます。このメソッド自体はGoogleのトークンを検証しません。ブラウザ指定の `owner`、任意のJWTのデコード結果、メールヘッダーを渡してはいけません。未設定・未確認のOAuthクライアントでは公開サーバーを起動できません。

セッションの資格情報は256ビットの乱数です。サーバーにはそのSHA256値だけを保持し、`__Host-timeline_session` Cookieに `Secure; HttpOnly; SameSite=Lax; Path=/` を付けます。期限は最大1時間、同時保持は既定1000件です。期限切れは削除し、上限時は既存セッションを追い出さず503で新規発行を拒否します。ログアウトしたセッションと、再起動前の全セッションは失効します。

再ログイン成功時は、そのブラウザの旧セッションを新しい資格情報へ原子的に置き換えます。同時保持の上限でも置き換えられ、本人確認が失敗した場合は旧セッションを維持します。

受付の所有者IDは、運営者が持つ秘密鍵と認証済み `issuer` / `sub` のHMACです。メール・氏名・Googleの原IDを台帳やAPIへ渡しません。同じ秘密鍵とアカウントなら、再ログインしても同じ受付を取得できます。秘密鍵を変更すると旧受付との対応を失うため、台帳の保持期間中は安全に保持し、通常の再起動で作り直しません。

現在の保持方式は単一プロセス用です。複数プロセス間の共有やログアウトの同期はありません。公開サービスの複数レプリカ構成にはそのまま使えません。

## Googleのサーバーフロー

ログイン画面の明示操作で、同じOriginから `POST /auth/google/start` に空のJSON `{}` を送ります。Googleへの認証要求は `openid` だけを要求し、メール・プロフィール・ドライブへの追加権限やオフラインのrefresh tokenを求めません。返る認証URLの接続先は固定です。

stateとブラウザ結び付けCookieは別々の256ビット乱数です。nonceとPKCE S256の検証値も作り、サーバーのメモリ内に最大1000件・10分だけ保持します。`GET /auth/google/callback` はGoogleからの別サイト遷移なので、通常APIのFetch-Site拒否条件の例外です。固定Host、Cookieとstateの組、一回限りの消費で保護し、別ブラウザ・Cookie欠落・二重呼出・期限切れを拒否します。

認可コードは `https://oauth2.googleapis.com/token` へサーバーから直接HTTPSで交換します。証明書検証を使い、環境のHTTPプロキシとHTTPリダイレクトは無効にします。接続先は公式Discoveryの確認済みURLに固定し、変更時は再確認が必要です。認可コードとクライアントシークレットはPOST本文に入れ、URL・ログ・DBには残しません。取得応答は64KiBまで、ソケットの待機時間は10秒です。

この直接TLSのコード交換応答は、Googleがクライアントシークレットで認証したサーバーへ返すものとして信頼します。Google公式仕様の「5. Obtain user information from the ID token」で、この経路に限って署名の別検証を省略できることを確認しています。issuer・audience・azp・期限・iat・nbf・nonce・subjectとトークン形式を検査してから、subjectだけを共通セッションへ渡します。ブラウザが送ったIDトークンを受け付ける経路も、IDトークンを別コンポーネントへ渡す経路もありません。将来その経路を追加する場合は、公開鍵による署名検証が必須です。[公式仕様](https://developers.google.com/identity/openid-connect/openid-connect)

成功・失敗ともコードやstateを含まない `/login` に303で戻します。エラーは固定コードから画面文言へ変換し、プロバイダーの応答本文は表示しません。CookieはSecure/HttpOnly、認証応答とAPI応答はno-store/no-referrerです。

## HTTPへの接続契約

| 用途 | 共通処理 | 条件 |
|---|---|---|
| セッション情報 | `session_view(headers)` | 認証成功時にCSRFトークンと残り秒数だけを返す。ownerは返さない。 |
| 自分の受付取得 | `receipt(ledger, headers, receipt_id)` | 所有者はセッションから導出。不明・他人の受付は同じ404。 |
| 自分のキャンセル | `receipt(..., cancel=True)` | 固定Originと `X-CSRF-Token` が必要。台帳の未開始キャンセル返却を維持。 |
| 自分の結果受領確認 | `receive(ledger, headers, receipt_id)` | 固定OriginとCSRFが必要。受領後の再取得猶予は10分。同じ確認を再送しても期限を延長しない。 |
| ログアウト | `logout(headers)` | 固定OriginとCSRFが必要。返ったCookie削除ヘッダーを送る。 |

`PublicBoundary.from_env(issuer)` は `TIMELINE_SOURCE=wikipedia`、固定HTTPSの `TIMELINE_PUBLIC_ORIGIN`、32バイトの運営秘密鍵を16進数64桁にした `TIMELINE_PUBLIC_OWNER_KEY` を要求します。未設定・別経路では起動用インスタンスを作れません。鍵は秘密の設定として扱い、Git・ログ・画面へ出しません。

Hostは設定した公開Originのホストと完全一致させます。`X-Forwarded-Host` などで上書きしません。HTTP中継が必要な場合は、公開用プロセスに到達する経路を閉じ、信頼する中継で固定Hostを設定する配備検証が必要です。この共通処理だけでは中継経路のアクセス制御を代替しません。

変更操作はOriginの省略も拒否します。取得操作はOrigin省略を許しますが、指定された別Originと `Sec-Fetch-Site: same-site/cross-site` は拒否します。Host・Origin・Cookie・CSRF・Fetch-Siteの重複ヘッダー、重複セッションCookieも拒否します。資格情報はCookieだけから読み、作成者を示す任意ヘッダーは使いません。

HTTPアダプターは `PublicError.status/code` を固定JSONへ変換し、`Cache-Control: no-store` を付けます。本人の期限切れ結果は410、完了後キャンセルは409、不正な生成結果は502です。例外本文や内部データを返してはいけません。受付頻度・取得量の制限、HTTPサイズ上限、purge/backup、ワーカー停止、中継の直通防止は後続の公開サービス接続で検証します。

現在の `public_server.py` は `/login`、固定した画面資産、`/api/session`、Google開始/コールバック、`POST /auth/logout` を配信します。`make_server(..., ledger=専用TrialLedger)` を明示的に接続した場合だけ、以下の本人操作を追加します。通常起動の `main()` は台帳を接続しません。台帳の所有・closeは呼び出し側の責務です。

| メソッド・URL | 動作 |
| --- | --- |
| `GET /api/receipts/<受付ID>` | 本人の受付状態と、保存期限内の最小化した結果を取得 |
| `POST /api/receipts/<受付ID>/cancel` | 本人の待機中・生成中受付を中止。未開始だけ元の受付日の枠を返却 |
| `POST /api/receipts/<受付ID>/received` | 端末保存後の受領確認。期限を10分の再取得猶予へ短縮 |

未認証401、他人・不明IDは404、CSRF不正403、状態競合409、本人の期限切れ410を返します。owner・入力payload・内部seq・引用quote・traceは返しません。新規受付、受付一覧、ワーカー起動は未接続です。任意ファイル、`/api/jobs`、私用評価、台帳ファイル、生成受付は配信しません。POSTは空JSONだけを受け、4KiB超過・重複Content-Length・Transfer-Encodingを拒否します。バックエンドは127.0.0.1のみで待ち受けます。

## 実接続の設定

| 環境変数 | 内容 |
|---|---|
| `TIMELINE_SOURCE` | `wikipedia` 必須 |
| `TIMELINE_PUBLIC_ORIGIN` | 登録する公開HTTPS Origin。末尾のパス・クエリ不可。ホスト名は小文字化し、既定ポート443は省略 |
| `TIMELINE_PUBLIC_OWNER_KEY` | 台帳保持期間中維持するランダム32バイトの秘密鍵（16進64桁） |
| `TIMELINE_GOOGLE_CLIENT_ID` | GoogleのWeb application OAuthクライアントID |
| `TIMELINE_GOOGLE_CLIENT_SECRET` | 同クライアントの秘密値。Git/チャット/画面に出さない |
| `TIMELINE_GOOGLE_CLIENT_REVIEWED` | 実クライアントの条件・設定確認後だけ `1` にする |
| `TIMELINE_PUBLIC_PORT` | バックエンドのローカルポート。既定8534 |

実接続は次の順で準備します。

1. 公開HTTPS URLを確定し、Google Cloud ConsoleでWeb applicationのOAuthクライアントを作成します。承認済みリダイレクトURIに `<公開Origin>/auth/google/callback` を登録します。
2. アプリ名・運営連絡先・プライバシーポリシー・利用条件と実クライアントの無料条件を確認します。Google APIs規約・OAuthポリシーと同意画面を確認し、`tool-license.yaml` の未確認条件を確定します。有料のIdentity Platformや他サービスを有効にしません。
3. 秘密値をローカルの0600設定または配備の秘密ストアに置き、`python3 public_server.py` を単一プロセスで起動します。公開TLS中継・固定Host・直通防止・外部側の接続数/頻度制限を設定した後、実Googleアカウントでログイン・拒否・ログアウト・再起動を検証します。

ブラウザで表示するログインの説明は、公開サービス全体のプライバシーポリシーを代替しません。現画面にあるLAN用visit-logタグは公開HTTPSとCSPで通信できず、CSPを緩めません。公開配備時は公開ネットワーク例外の理由をissueと配備設定に記録します。現在は配備・例外設定を行っていません。

## 結果の最小化

`result_view()` は、サーバーが生成したWikipedia限定結果だけを受け取り、テーマ・期間・注意書き・出来事の年/日付/題名/説明・出典名/URLを返します。引用・trace・内部ID・APIキーなどの未知のフィールドをコピーしません。最大50出来事、文字項目ごとの上限とJSON全体512KiBの上限を検査します。

出典はHTTPSの日本語版・英語版Wikipedia記事のみです。資格情報付きURL、別ホスト、非標準ポート、クエリ、空の記事名、制御文字を拒否します。外部通信は行いません。持込ファイルの `source_mode` は自己申告なので、この関数を通すだけで公開承認済みと扱ってはいけません。受信文字列は既存の端末保存と同様、HTMLとして実行せず描画します。

共通処理は本文の事実確認やCCライセンス表示を代替しません。出典との内容監査と [PUBLIC_LICENSE.md](PUBLIC_LICENSE.md) の帰属・改変表示は必要です。

## 検証と切り戻し

`python3 -m unittest test_google_login test_public_server test_public_security -v` は認証済み応答を模したテスト用トークンで検証します。実HTTP通信と一時台帳でログイン・本人限定取得・キャンセル・410/409・結果最小化を確認します。`browser_public_login.py` は仮のHTTPS Originと実ローカルHTTP入口でSecure Cookieと画面遷移を確認し、Googleの画面とトークン応答をテスト用応答へ置き換えます。Playwrightのredirect後ルート制約を避けるため、ブラウザ試験の303はmeta遷移に置き換え、実HTTPの303は別のHTTPテストで確認します。実Googleアカウント認証の証拠ではなく、Google通信・モデル生成・外部配備は行いません。

公開認証用コードはローカル検証段階で、実サービスへ配備していません。この変更で公開生成受付は開きません。切り戻しは接続先の公開サービス停止とコード復元です。私用DBと端末IndexedDBは変更・削除しません。
