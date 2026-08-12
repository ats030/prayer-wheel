/* 記録の組み立てと復元。
 *
 * 置き場は Google ドライブひとつ。ログインに Google アカウントを使う以上、
 * 全員が持っている保存先はここで、選ばせる理由がない。以前は WebDAV・端末内の
 * フォルダ・ファイル書き出しも並べていたが、ボタンが7個並ぶ画面になっていた。
 *
 * APIキーは既定では含めない。ファイルが漏れたとき、そのまま課金されるキーが渡る。
 * ただし端末や入口 (公開版と :8443) を移るたびに入れ直すのは重いので、承知のうえで
 * 一緒に置くことも選べる。選んだ人だけが、その危険を引き受ける。
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

  const payload = {
    format: BACKUP_FORMAT,
    exportedAt: new Date().toISOString(),
    note: "APIキーは含めません。別の端末では入れ直してください。",
    settings,
    records,
  };
  if (savingKeys()) {
    payload.apiKeys = collectApiKeys();
    payload.note = "APIキーを含みます。このファイルが他人に渡ると、あなたのキーで料金が発生します。";
  }
  return payload;
}

/* 読み込んだ内容を戻す。既存の記録は消さず、同じidは新しいほうを残す。
 *
 * 「混ぜる」動作にしてある。片方の端末で消した記録は、もう片方には残る。
 * 消したことを伝える印を持たない限り、削除は行き渡らない。消えるより残るほうが
 * 害が小さいので、こちらを既定にする。 */
/* APIキーを一緒に置くかどうか。既定は置かない */
const SAVE_KEYS_FLAG = "species-save-keys-to-cloud";

function savingKeys() {
  try { return localStorage.getItem(SAVE_KEYS_FLAG) === "1"; } catch (error) { return false; }
}

function setSavingKeys(on) {
  try { on ? localStorage.setItem(SAVE_KEYS_FLAG, "1") : localStorage.removeItem(SAVE_KEYS_FLAG); }
  catch (error) { /* 覚えられなくても、その場の選択は効く */ }
}

const KEY_NAMES = ["gemini", "openai", "anthropic", "plantnet"];

function collectApiKeys() {
  const keys = {};
  for (const name of KEY_NAMES) {
    const value = typeof readApiKey === "function" ? readApiKey(name) : "";
    if (value) keys[name] = value;
  }
  return keys;
}

function restoreApiKeys(keys) {
  if (!keys || typeof writeApiKey !== "function") return 0;
  let restored = 0;
  for (const name of KEY_NAMES) {
    if (keys[name]) { writeApiKey(name, keys[name]); restored++; }
  }
  return restored;
}

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
  restoreApiKeys(payload.apiKeys);
  return restored;
}

/* 記録が増減するたびに呼ばれる。まとめて1回だけ書くよう少し待つ。
   ドライブにつながっていないときは何もしない (記録は端末の中に残る) */
let backupTimer = null;
function scheduleAutoBackup() {
  clearTimeout(backupTimer);
  backupTimer = setTimeout(() => {
    if (typeof autoSaveToDrive === "function") autoSaveToDrive();
  }, 1500);
}
