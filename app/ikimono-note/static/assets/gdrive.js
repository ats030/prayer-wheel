/* Google ドライブへの保存。
 *
 * Google ドライブは WebDAV を提供していないので、OAuth と Drive API を使う。
 * 通信はブラウザから Google へ直接行き、本サービスのサーバーを経由しない。
 * そのため写真も認証トークンも運営者を通らない (WebDAV 中継とはここが違う)。
 *
 * 権限は drive.file に絞る。このアプリが作ったファイルしか見えないので、
 * 利用者のドライブ全体を読む力は持たない。
 */

const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";
/* 保存先は画面のモードで分ける。運営者用 (8443) の試し撮りが利用者の記録と同じ
   ファイルに入ると、あとから見分けられない。以前はその理由で運営者用の書き込み
   ごと止めていたが、それだと運営者の記録が端末から出られず、別の端末で見られない。
   ファイルを分ければ、混ざらないことと持ち出せることが両立する。 */
const DRIVE_FILE_NAMES = {operator: "ikimono-note-operator.json", public: "ikimono-note.json"};
function driveFileName() {
  return DRIVE_FILE_NAMES[document.body?.dataset?.appMode] || DRIVE_FILE_NAMES.public;
}
const DRIVE_KEY = "species-drive-file";   // 作ったファイルのIDを覚えておく

/* トークンはタブの中に置く (sessionStorage)。以前はメモリだけに置いていたが、
   この画面はページごとに別なので、画面を移るたびに消えていた。消えたら取り直す
   作りにしてあったものの、GIS の取り直しはポップアップを開くため、利用者の操作
   なしには通らない。結果、画面を移るたびに「つなぎ直しが必要です」が出ていた。
   タブを閉じれば消える。ディスクには残さない */
const DRIVE_TOKEN_KEY = "species-drive-token";
let driveToken = null;
/* Google のアクセストークンは1時間ほどで切れる。期限を見ずに持ち続けていたため、
   タブを開いたまま1時間たつと最初の書き込みが 401 で落ち、「許可が切れました」と
   出ていた。黙って取り直せば済む場面で、利用者につなぎ直しを求めていた。 */
let driveTokenExpiry = 0;

function rememberDriveToken(token, expiry) {
  driveToken = token;
  driveTokenExpiry = expiry;
  try {
    if (token) sessionStorage.setItem(DRIVE_TOKEN_KEY, JSON.stringify({token, expiry}));
    else sessionStorage.removeItem(DRIVE_TOKEN_KEY);
  } catch (error) { /* 覚えられなくても、その画面のあいだは使える */ }
}

(function recallDriveToken() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(DRIVE_TOKEN_KEY) || "null");
    if (saved && saved.token && Date.now() < saved.expiry) {
      driveToken = saved.token;
      driveTokenExpiry = saved.expiry;
    }
  } catch (error) { /* 壊れていたら無いものとして扱う */ }
})();
let driveClientId = "";     // 取り直すときに要る。公開情報なので秘密ではない
/* 取り直しは同時に走らせない。GIS のトークン要求を並行で投げると、あとから
   initTokenClient したほうが driveTokenClient を上書きし、先の要求のコールバックが
   どこにも届かなくなる。設定画面では「開いたときの取り込み」と「画面の状態を描く」が
   同時に走るので、これは実際に起きる筋 */
let driveTokenRequest = null;
/* 取り直せなかった理由。握りつぶすと、切れたという報告から先へ進めない */
let lastDriveTokenError = "";
let driveTokenClient = null;
const DRIVE_LINKED = "species-drive-linked";   // 一度つないだかどうか。トークンそのものではない

function driveConfigured(clientId) {
  return Boolean(clientId);
}

/* Google のスクリプトは必要になってから読む。使わない人に読ませない */
function loadGoogleIdentity() {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.getElementById("gis-script");
    if (existing) { existing.addEventListener("load", () => resolve()); return; }
    const script = document.createElement("script");
    script.id = "gis-script";
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Google への接続を読み込めませんでした"));
    document.head.append(script);
  });
}

async function driveSignIn(clientId) {
  driveClientId = clientId || driveClientId;
  await loadGoogleIdentity();
  return new Promise((resolve, reject) => {
    driveTokenClient = google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: DRIVE_SCOPE,
      callback: (response) => {
        if (response.error) {
          /* 何が起きたか分からないと直しようがない。Google が返す符丁をそのまま見せる */
          reject(new Error(`${response.error}${response.error_description ? "：" + response.error_description : ""}`));
          return;
        }
        /* 期限ぎりぎりで使うと、往復のあいだに切れる。1分手前で切れた扱いにする */
        /* 期限ぎりぎりで使うと、往復のあいだに切れる。1分手前で切れた扱いにする。
           下限を置くと、短いトークンを実際より長生きだと思い込む */
        rememberDriveToken(response.access_token,
                           Date.now() + Math.max(0, Number(response.expires_in || 3600) - 60) * 1000);
        rememberDriveLink(true);
        resolve(driveToken);
      },
      error_callback: (error) => {
        /* type は popup_closed / popup_failed_to_open / unknown のいずれか。
           閉じられたのか、開けなかったのか、Google に断られたのかで手が違う */
        const kind = error?.type || "unknown";
        const hint = kind === "popup_failed_to_open"
          ? "ブラウザがポップアップを止めています。このサイトのポップアップを許可してください。"
          : kind === "popup_closed"
          ? "許可の画面が閉じられました。ログイン後に自動で閉じる場合は、Google Cloud Console で"
            + "テストユーザーに自分のアカウントを追加し、スコープに drive.file を足してください。"
          : "";
        reject(new Error(`${error?.message || "Google の許可を得られませんでした"}（${kind}）${hint ? " " + hint : ""}`));
      },
    });
    /* 画面を出さない取得はできない。GIS のトークン取得は必ずポップアップを開き、
       公式にも "from a user-driven event such as a button press" とある。
       prompt: "none" を渡しても窓は開くので、押されたときにだけここへ来る */
    driveTokenClient.requestAccessToken({prompt: "consent"});
  });
}

function driveTokenAlive() {
  return Boolean(driveToken) && Date.now() < driveTokenExpiry;
}

function driveSignedIn() {
  /* 使えるトークンがあるかどうかだけを答える。設定画面はこれを呼ぶ前に
     ensureDriveToken で取り直しているので、ここで false なら本当に駄目な状態。
     取り直せば済む状態を「つながっています」と見せると、直せる不調が隠れる */
  return driveTokenAlive();
}

function driveLinked() {
  try { return localStorage.getItem(DRIVE_LINKED) === "1"; } catch (error) { return false; }
}

function rememberDriveLink(linked) {
  try { linked ? localStorage.setItem(DRIVE_LINKED, "1") : localStorage.removeItem(DRIVE_LINKED); }
  catch (error) { /* 覚えられなくても、その場では使える */ }
}

/* 使えるトークンがあれば返す。無ければ、押されたときだけ取りに行く。
 *
 * 以前は無ければ黙って取り直していたが、GIS のトークン取得は必ずポップアップを
 * 開き、公式にも "obtain a new token by calling requestAccessToken() from a
 * user-driven event such as a button press" とある。読み込み時に呼んでも
 * ブラウザに止められ、popup_failed_to_open になるだけだった。画面を移るたびに
 * これが起き、「すぐ切れる」ように見えていた。
 */
async function ensureDriveToken(clientId, {interactive = false} = {}) {
  driveClientId = clientId || driveClientId;
  if (driveTokenAlive()) return driveToken;
  rememberDriveToken(null, 0);
  if (!driveClientId || !driveLinked()) return null;
  if (!interactive) {
    /* 押されていないのに窓を開けにいかない。理由は画面に出す側で言い換える */
    lastDriveTokenError = "";
    return null;
  }
  if (driveTokenRequest) return driveTokenRequest;   // すでに誰かが取りに行っている
  driveTokenRequest = (async () => {
    try {
      const token = await driveSignIn(driveClientId);
      lastDriveTokenError = "";
      return token;
    } catch (error) {
      lastDriveTokenError = String(error?.message || error || "理由の記載なし");
      console.info("ドライブのトークンを取り直せませんでした", error);
      return null;
    } finally {
      driveTokenRequest = null;
    }
  })();
  return driveTokenRequest;
}

/* 画面に出す「なぜ取り直せなかったか」。利用者が押せる手は「つなぎ直す」だけだが、
   何と言われたかが出ていれば、運営者は原因に辿り着ける */
function driveTokenTrouble() {
  return lastDriveTokenError;
}

/* 最後に書けたかどうかを残す。黙って失敗し続けると、保存されたつもりで
   記録がどこにも無い状態になる。画面はこれを見て伝える */
const DRIVE_STATUS = "species-drive-status";

function driveStatus() {
  try { return JSON.parse(localStorage.getItem(DRIVE_STATUS) || "null"); } catch (error) { return null; }
}

function noteDriveStatus(ok, detail) {
  try {
    localStorage.setItem(DRIVE_STATUS, JSON.stringify({ok, detail: detail || "", at: new Date().toISOString()}));
  } catch (error) { /* 残せなくても保存自体は行う */ }
}

/* 記録が変わったあとに呼ばれる。つながっていなければ何もしないが、
   つないだはずなのに書けなかったときは、そのことを残す */
async function autoSaveToDrive() {
  const linked = driveLinked();
  try {
    const settings = await fetch("/api/settings").then(r => r.ok ? r.json() : null);
    const token = await ensureDriveToken(settings?.google_client_id || "");
    if (!token) {
      if (linked) noteDriveStatus(false, "つなぎ直しが必要です" + (driveTokenTrouble() ? "（" + driveTokenTrouble() + "）" : ""));
      return false;
    }
    const count = await saveToDrive();
    noteDriveStatus(true, `記録 ${count}件`);
    return true;
  } catch (error) {
    console.error("ドライブへ書けませんでした", error);
    noteDriveStatus(false, error.message || "書き込めませんでした");
    return false;
  }
}

function driveFileId() {
  try { return localStorage.getItem(DRIVE_KEY) || ""; } catch (error) { return ""; }
}

function forgetDrive() {
  driveToken = null;
  driveTokenExpiry = 0;
  rememberDriveLink(false);
  rememberDriveFile("");
}

function rememberDriveFile(id) {
  try { id ? localStorage.setItem(DRIVE_KEY, id) : localStorage.removeItem(DRIVE_KEY); } catch (error) { /* 覚えられなくても保存はできる */ }
}

async function driveFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {...(options.headers || {}), Authorization: "Bearer " + driveToken},
  });
  if (response.status === 401) {
    /* 期限より先に無効化されることがある (別の端末で許可を外した等)。
       ここで黙って取り直そうとしていたが、それは窓を開ける操作で、押されていない
       以上ブラウザに止められる。取り直しは設定画面のボタンに任せる */
    rememberDriveToken(null, 0);
    throw new Error("Google の許可が切れました。設定画面でもう一度つないでください");
  }
  if (!response.ok) throw new Error(`Google ドライブが応答しませんでした（${response.status}）`);
  return response;
}

/* 以前このアプリが作ったファイルを探す。drive.file なので自分のファイルだけが見える */
async function findDriveFile() {
  const known = driveFileId();
  if (known) {
    try { await driveFetch(`https://www.googleapis.com/drive/v3/files/${known}?fields=id,trashed`); return known; }
    catch (error) { rememberDriveFile(""); }
  }
  const query = encodeURIComponent(`name='${driveFileName()}' and trashed=false`);
  const response = await driveFetch(`https://www.googleapis.com/drive/v3/files?q=${query}&fields=files(id,name)&pageSize=1`);
  const found = (await response.json()).files?.[0]?.id || "";
  if (found) rememberDriveFile(found);
  return found;
}

/* 原寸の写真は、記録ごとに1枚ずつ別ファイルとして置く。
 *
 * 1つのJSONへ base64 で詰めていたころは、タブを開くたびに十数MBを引き、記録が1件
 * 増えるたびに丸ごと上げ直していた。写真を外へ出すと、JSONは小さい1枚と札だけになり、
 * 上げ直すのは変わったぶんだけ、引くのは開いた記録のぶんだけで済む。
 *
 * 名前に記録のidを入れておくのは、札を失っても後片付けできるようにするため。
 * drive.file なので、このアプリが作ったファイルしか見えない。
 */
const PHOTO_PREFIX = "ikimono-photo-";
function photoFileName(recordId, index) {
  return PHOTO_PREFIX + driveFileName().replace(/\.json$/, "") + "-" + recordId + "-" + index + ".jpg";
}

async function uploadPhoto(name, blob) {
  const form = new FormData();
  form.append("metadata", new Blob([JSON.stringify({name, mimeType: "image/jpeg"})],
                                   {type: "application/json"}));
  form.append("file", blob);
  const response = await driveFetch(
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
    {method: "POST", body: form});
  return (await response.json()).id || "";
}

/* まだ上げていない記録の原寸を上げ、札を記録へ書き戻す。
   1回の保存で上げる枚数を抑える。50件×3枚を一度に上げると、記録を1件足しただけで
   何十回も往復することになる。残りは次の保存で片付く */
const PHOTO_UPLOADS_PER_SAVE = 6;
async function uploadPendingPhotos() {
  const entries = await allHistoryEntries();
  let budget = PHOTO_UPLOADS_PER_SAVE;
  const updated = [];
  for (const entry of entries) {
    if (budget <= 0) break;
    const photos = (Array.isArray(entry.thumbnails) && entry.thumbnails.length)
      ? entry.thumbnails : (entry.thumbnail ? [entry.thumbnail] : []);
    const known = Array.isArray(entry.drivePhotos) ? entry.drivePhotos : [];
    if (!photos.length || known.length >= photos.length) continue;
    const ids = [...known];
    for (let index = known.length; index < photos.length && budget > 0; index++) {
      budget--;
      const id = await uploadPhoto(photoFileName(entry.id, index), photos[index]);
      if (!id) break;
      ids.push(id);
    }
    if (ids.length !== known.length) updated.push({...entry, drivePhotos: ids});
  }
  if (updated.length) await putHistoryEntries(updated);
  return updated.length;
}

/* 札をたどって原寸を引き、手元へ入れる。開いた記録のぶんだけ呼ぶ */
async function fetchRecordPhotos(record) {
  const ids = Array.isArray(record?.drivePhotos) ? record.drivePhotos : [];
  if (!ids.length) return [];
  const settings = await fetch("/api/settings").then(r => r.ok ? r.json() : null);
  if (!await ensureDriveToken(settings?.google_client_id || "")) return [];
  const photos = [];
  for (const id of ids) {
    const response = await driveFetch(`https://www.googleapis.com/drive/v3/files/${id}?alt=media`);
    photos.push(await response.blob());
  }
  if (photos.length) await putHistoryEntries([{...record, thumbnails: photos, thumbnail: photos[0]}]);
  return photos;
}

/* 記録が消えたぶんのファイルを片付ける。drive.file なので自分のものしか見えない */
async function pruneDrivePhotos() {
  const entries = await allHistoryEntries();
  const alive = new Set(entries.flatMap(entry => (entry.drivePhotos || [])));
  const query = encodeURIComponent(`name contains '${PHOTO_PREFIX}' and trashed=false`);
  const response = await driveFetch(
    `https://www.googleapis.com/drive/v3/files?q=${query}&fields=files(id)&pageSize=200`);
  const files = (await response.json()).files || [];
  let removed = 0;
  for (const file of files) {
    if (alive.has(file.id)) continue;
    try { await driveFetch(`https://www.googleapis.com/drive/v3/files/${file.id}`, {method: "DELETE"}); removed++; }
    catch (error) { /* 消せなくても次回また試す */ }
  }
  return removed;
}

async function saveToDrive() {
  /* 先に原寸を上げてから JSON を作る。順が逆だと、上げたばかりの札が JSON に入らない */
  try { await uploadPendingPhotos(); } catch (error) { console.info("写真を上げられませんでした", error); }
  const payload = await buildBackup();
  const body = new Blob([JSON.stringify(payload)], {type: "application/json"});
  const existing = await findDriveFile();
  const metadata = existing ? {} : {name: driveFileName(), mimeType: "application/json"};
  const form = new FormData();
  form.append("metadata", new Blob([JSON.stringify(metadata)], {type: "application/json"}));
  form.append("file", body);
  const base = "https://www.googleapis.com/upload/drive/v3/files";
  const url = existing ? `${base}/${existing}?uploadType=multipart` : `${base}?uploadType=multipart`;
  const response = await driveFetch(url, {method: existing ? "PATCH" : "POST", body: form});
  rememberDriveFile((await response.json()).id || existing);
  try { await pruneDrivePhotos(); } catch (error) { /* 後片付けは次回でよい */ }
  return payload.records.length;
}

async function loadFromDrive() {
  const existing = await findDriveFile();
  if (!existing) throw new Error("Google ドライブにまだ記録がありません");
  const response = await driveFetch(`https://www.googleapis.com/drive/v3/files/${existing}?alt=media`);
  return await restoreBackup(JSON.parse(await response.text()));
}

/* つないである端末では、画面を開いたときに一度だけ取り込む。
 *
 * 取り込みを設定画面のボタンだけに任せると、別の端末で先に1件調べた瞬間、
 * その少ない側でドライブのファイルが上書きされる。書き込みは last-writer-wins で、
 * 統合が起きるのは読み込みのときだけだから。開いた直後に合流させておけば、
 * そのあとの自動保存はどの端末でも「全部入り」を書く。
 *
 * 1タブにつき1回。記録50件は数MBあるので、画面を移るたびに引き直さない。
 */
const DRIVE_PULLED = "species-drive-pulled";
let drivePull = null;   // defer と DOMContentLoaded の両方から呼ばれる。二重に引かない

function syncFromDriveOnce() {
  if (!drivePull) drivePull = pullFromDrive();
  return drivePull;
}

async function pullFromDrive() {
  if (!driveLinked()) return false;
  try { if (sessionStorage.getItem(DRIVE_PULLED) === "1") return false; } catch (error) { return false; }
  try {
    const settings = await fetch("/api/settings").then(r => r.ok ? r.json() : null);
    if (!await ensureDriveToken(settings?.google_client_id || "")) {
      noteDriveStatus(false, "ドライブから取り込むには、設定画面でつなぎ直してください"
                             + (driveTokenTrouble() ? "（" + driveTokenTrouble() + "）" : ""));
      return false;
    }
    const restored = await loadFromDrive();
    try { sessionStorage.setItem(DRIVE_PULLED, "1"); } catch (error) { /* 覚えられなくても取り込みは済んでいる */ }
    /* 記録一覧はもう描き終わっている。描き直す機会を渡す */
    document.dispatchEvent(new CustomEvent("species-records-restored", {detail: {restored}}));
    return true;
  } catch (error) {
    /* まだ1件も保存していない端末では「記録がありません」で正常に落ちる。
       画面に出すことはしない (利用者が押していない処理で赤字を出さない) */
    console.info("ドライブから取り込めませんでした", error);
    return false;
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => { syncFromDriveOnce(); });
} else {
  syncFromDriveOnce();
}
