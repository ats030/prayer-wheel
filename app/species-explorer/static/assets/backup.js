/* 設定と記録の持ち出し。保存先は利用者が選ぶ。
 *
 * 運営者のサーバーへは何も送らない。プライバシーポリシーの「サーバーへ保存しません」を
 * 維持したまま、端末を移っても記録が残るようにするのが目的。
 *
 * APIキーは含めない。ファイルが漏れたとき、そのまま課金されるキーが渡ってしまう。
 */

const BACKUP_FORMAT = "ikimono-note/1";

function backupDb() {
  return new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) { reject(new Error("このブラウザは記録の保存に対応していません")); return; }
    const request = indexedDB.open("species-history", 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("entries")) db.createObjectStore("entries", {keyPath: "id"});
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function backupRequest(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function backupTransaction(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

function dataUrlToBlob(value) {
  /* fetch(dataUrl) は connect-src 'self' に弾かれる。自前でデコードする */
  if (typeof value !== "string" || !value.startsWith("data:")) return null;
  const comma = value.indexOf(",");
  if (comma < 0) return null;
  const header = value.slice(0, comma);
  const mime = (header.match(/^data:([^;]+)/) || [])[1] || "application/octet-stream";
  const binary = atob(value.slice(comma + 1));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], {type: mime});
}

/* 書き出す中身を組み立てる。写真は data URL にして1ファイルへ収める */
async function buildBackup() {
  const db = await backupDb();
  const transaction = db.transaction("entries", "readonly");
  const entries = await backupRequest(transaction.objectStore("entries").getAll());
  await backupTransaction(transaction);
  db.close();

  const records = [];
  for (const entry of entries) {
    const copy = {...entry};
    copy.thumbnail = entry.thumbnail ? await blobToDataUrl(entry.thumbnail) : null;
    records.push(copy);
  }
  let settings = null;
  try { settings = JSON.parse(localStorage.getItem("species-public-settings") || "null"); } catch (error) { settings = null; }
  return {
    format: BACKUP_FORMAT,
    exportedAt: new Date().toISOString(),
    note: "APIキーは含めません。別の端末では入れ直してください。",
    settings,
    records,
  };
}

/* 読み込んだ内容を戻す。既存の記録は消さず、同じidは新しいほうを残す */
async function restoreBackup(payload) {
  if (!payload || payload.format !== BACKUP_FORMAT) throw new Error("この生きものノートの書き出しファイルではありません");
  const records = Array.isArray(payload.records) ? payload.records : [];
  const db = await backupDb();
  let restored = 0;
  for (const record of records) {
    if (!record?.id) continue;
    const entry = {...record};
    entry.thumbnail = dataUrlToBlob(record.thumbnail);
    const transaction = db.transaction("entries", "readwrite");
    transaction.objectStore("entries").put(entry);
    await backupTransaction(transaction);
    restored++;
  }
  db.close();
  if (payload.settings) {
    localStorage.setItem("species-public-settings", JSON.stringify(payload.settings));
  }
  return restored;
}

function backupFileName() {
  const now = new Date();
  const stamp = [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"), String(now.getDate()).padStart(2, "0")].join("-");
  return `ikimono-note-${stamp}.json`;
}


/* ── 既定の保存先 ─────────────────────────────────────────
 * 選んだファイルへの参照 (FileSystemFileHandle) を持っておき、記録が変わるたびに
 * 書き直す。参照は IndexedDB に入れられるので、次に開いたときも同じ場所へ書ける。
 *
 * 記録の本体 (species-history) とは別のDBに置く。既存DBのバージョンを上げると、
 * すでに記録を持っている利用者の移行を伴うため。
 *
 * 読み込みは「混ぜる」動作にしてある。片方の端末で消した記録は、もう片方には
 * 残る。消したことを伝える印を持たない限り、削除は行き渡らない。
 * 消えるより残るほうが害が小さいので、こちらを既定にする。
 */

const HANDLE_DB = "species-backup";
const HANDLE_KEY = "default-target";

function handleDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(HANDLE_DB, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("handles")) db.createObjectStore("handles");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function backupSupported() {
  return typeof window.showSaveFilePicker === "function";
}

/* 使えないときは理由を返す。黙って消えると、機能が無いのか壊れたのか分からない */
function backupUnavailableReason() {
  if (backupSupported()) return "";
  if (!window.isSecureContext) return "この画面は暗号化されていない接続 (http://) のため、保存先を決められません。https:// で開くと使えます。";
  return "このブラウザは保存先の指定に対応していません。Chrome か Edge でお試しください。書き出し・読み込みはこのままお使いいただけます。";
}

async function rememberTarget(handle) {
  const db = await handleDb();
  const transaction = db.transaction("handles", "readwrite");
  transaction.objectStore("handles").put(handle, HANDLE_KEY);
  await backupTransaction(transaction);
  db.close();
}

async function storedTarget() {
  if (!backupSupported()) return null;
  try {
    const db = await handleDb();
    const transaction = db.transaction("handles", "readonly");
    const handle = await backupRequest(transaction.objectStore("handles").get(HANDLE_KEY));
    await backupTransaction(transaction);
    db.close();
    return handle || null;
  } catch (error) {
    return null;
  }
}

async function forgetTarget() {
  const db = await handleDb();
  const transaction = db.transaction("handles", "readwrite");
  transaction.objectStore("handles").delete(HANDLE_KEY);
  await backupTransaction(transaction);
  db.close();
}

/* 権限は再訪のたびに確認が要る。granted でなければ、利用者の操作なしには要求できない */
async function targetPermission(handle, {ask = false} = {}) {
  if (!handle?.queryPermission) return "granted";
  const options = {mode: "readwrite"};
  let state = await handle.queryPermission(options);
  if (state !== "granted" && ask) state = await handle.requestPermission(options);
  return state;
}

async function writeBackupTo(handle) {
  const payload = await buildBackup();
  const writable = await handle.createWritable();
  await writable.write(new Blob([JSON.stringify(payload)], {type: "application/json"}));
  await writable.close();
  return payload.records.length;
}

async function readBackupFrom(handle) {
  const file = await handle.getFile();
  return await restoreBackup(JSON.parse(await file.text()));
}

/* 記録が変わるたびに呼ばれる。まとめて1回だけ書くよう少し待つ */
let backupTimer = null;
function scheduleAutoBackup() {
  if (!backupSupported()) return;
  clearTimeout(backupTimer);
  backupTimer = setTimeout(async () => {
    try {
      const handle = await storedTarget();
      if (!handle) return;
      if (await targetPermission(handle) !== "granted") return;  // 次に画面を開いたとき許可を促す
      await writeBackupTo(handle);
    } catch (error) {
      console.error("記録を保存先へ書けませんでした", error);
    }
  }, 1500);
}
