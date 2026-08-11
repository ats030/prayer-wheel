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
const DRIVE_FILE_NAME = "ikimono-note.json";
const DRIVE_KEY = "species-drive-file";   // 作ったファイルのIDを覚えておく

let driveToken = null;      // メモリだけに置く。保存すると盗まれたとき困る
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

async function driveSignIn(clientId, {silent = false} = {}) {
  await loadGoogleIdentity();
  return new Promise((resolve, reject) => {
    driveTokenClient = google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: DRIVE_SCOPE,
      callback: (response) => {
        if (response.error) { reject(new Error(response.error_description || response.error)); return; }
        driveToken = response.access_token;
        rememberDriveLink(true);
        resolve(driveToken);
      },
      error_callback: (error) => reject(new Error(error?.message || "Google の許可を得られませんでした")),
    });
    // 初回は画面を出す。二度目からは、出さずに取れるなら出さない
    driveTokenClient.requestAccessToken(silent ? {prompt: "none"} : {prompt: ""});
  });
}

function driveSignedIn() {
  return Boolean(driveToken);
}

function driveLinked() {
  try { return localStorage.getItem(DRIVE_LINKED) === "1"; } catch (error) { return false; }
}

function rememberDriveLink(linked) {
  try { linked ? localStorage.setItem(DRIVE_LINKED, "1") : localStorage.removeItem(DRIVE_LINKED); }
  catch (error) { /* 覚えられなくても、その場では使える */ }
}

/* 一度つないだ相手なら、画面を出さずに取り直せることが多い。取れなければ諦める。
   自動保存のたびに許可を求めると、記録するたび画面が出て使い物にならない */
async function ensureDriveToken(clientId) {
  if (driveToken) return driveToken;
  if (!clientId || !driveLinked()) return null;
  try {
    return await driveSignIn(clientId, {silent: true});
  } catch (error) {
    return null;
  }
}

/* 記録が変わったあとに呼ばれる。つながっていなければ黙って何もしない */
async function autoSaveToDrive() {
  try {
    const settings = await fetch("/api/settings").then(r => r.ok ? r.json() : null);
    const token = await ensureDriveToken(settings?.google_client_id || "");
    if (!token) return false;
    await saveToDrive();
    return true;
  } catch (error) {
    console.error("ドライブへ書けませんでした", error);
    return false;
  }
}

function driveFileId() {
  try { return localStorage.getItem(DRIVE_KEY) || ""; } catch (error) { return ""; }
}

function forgetDrive() {
  driveToken = null;
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
  if (response.status === 401) { driveToken = null; throw new Error("Google の許可が切れました。もう一度つないでください"); }
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
  const query = encodeURIComponent(`name='${DRIVE_FILE_NAME}' and trashed=false`);
  const response = await driveFetch(`https://www.googleapis.com/drive/v3/files?q=${query}&fields=files(id,name)&pageSize=1`);
  const found = (await response.json()).files?.[0]?.id || "";
  if (found) rememberDriveFile(found);
  return found;
}

async function saveToDrive() {
  const payload = await buildBackup();
  const body = new Blob([JSON.stringify(payload)], {type: "application/json"});
  const existing = await findDriveFile();
  const metadata = existing ? {} : {name: DRIVE_FILE_NAME, mimeType: "application/json"};
  const form = new FormData();
  form.append("metadata", new Blob([JSON.stringify(metadata)], {type: "application/json"}));
  form.append("file", body);
  const base = "https://www.googleapis.com/upload/drive/v3/files";
  const url = existing ? `${base}/${existing}?uploadType=multipart` : `${base}?uploadType=multipart`;
  const response = await driveFetch(url, {method: existing ? "PATCH" : "POST", body: form});
  rememberDriveFile((await response.json()).id || existing);
  return payload.records.length;
}

async function loadFromDrive() {
  const existing = await findDriveFile();
  if (!existing) throw new Error("Google ドライブにまだ記録がありません");
  const response = await driveFetch(`https://www.googleapis.com/drive/v3/files/${existing}?alt=media`);
  return await restoreBackup(JSON.parse(await response.text()));
}
