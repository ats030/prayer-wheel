/* 記録の組み立てと復元。
 *
 * 置き場は Google ドライブひとつ。ログインに Google アカウントを使う以上、
 * 全員が持っている保存先はここで、選ばせる理由がない。以前は WebDAV・端末内の
 * フォルダ・ファイル書き出しも並べていたが、ボタンが7個並ぶ画面になっていた。
 *
 * APIキーは含めない。ファイルが漏れたとき、そのまま課金されるキーが渡る。
 * 入れ直しの手間は、ブラウザのパスワード管理に預けることで解いた
 * (settings.html の autocomplete)。同じものを二重に持つと、片方が漏れる筋が増える。
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

/* 写真に使ってよい実体バイト数。base64 で約1.33倍になるので、ファイルは12MB前後で頭打ち。
   端末の中 (IndexedDB) はこの制限を受けず、記録は全部そのまま残る */
const BACKUP_PHOTO_BUDGET = 9 * 1024 * 1024;

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

  /* ドライブのファイルはタブを開くたびに1回引く。写真を無制限に詰めると、
     モバイル回線で毎回それを落とすことになる。新しい記録から順に写真を入れ、
     予算を使い切ったら、それより古い記録は本文だけにする (記録自体は消さない)。
     以前ここを見積もったとき、元が500pxの評価用画像で測ってしまい、実際の
     4分の1の大きさだと思い込んでいた。実カメラ写真では1枚が100KB〜300KBある。 */
  const newestFirst = [...entries].sort((a, b) =>
    String(b.createdAt || "").localeCompare(String(a.createdAt || "")));
  let budget = BACKUP_PHOTO_BUDGET;
  let dropped = 0;
  const records = [];
  for (const entry of newestFirst) {
    const copy = {...entry};
    /* 送った写真は全部残す。1枚目だけ書き出すと、別の端末で読み込んだとたんに
       撮り足した寄りの1枚が消える */
    const photos = Array.isArray(entry.thumbnails) && entry.thumbnails.length
      ? entry.thumbnails.filter(Boolean)
      : (entry.thumbnail ? [entry.thumbnail] : []);
    const bytes = photos.reduce((total, blob) => total + (blob.size || 0), 0);
    if (photos.length && bytes <= budget) {
      budget -= bytes;
      /* thumbnail は書き出さない。1枚目は thumbnails[0] と同じもので、両方入れると
         ファイルの3分の1が同じ写真の写しになる。読み込む側が1枚目から組み直す */
      copy.thumbnail = null;
      copy.thumbnails = [];
      for (const blob of photos) copy.thumbnails.push(await blobToDataUrl(blob));
    } else {
      if (photos.length) dropped++;
      copy.thumbnail = null;
      copy.thumbnails = [];
    }
    records.push(copy);
  }
  let settings = null;
  try { settings = JSON.parse(localStorage.getItem("species-public-settings") || "null"); } catch (error) { settings = null; }

  const payload = {
    photosOmitted: dropped,
    format: BACKUP_FORMAT,
    exportedAt: new Date().toISOString(),
    note: "APIキーは含めません。別の端末では入れ直してください。",
    settings,
    records,
  };
  return payload;
}

/* 読み込んだ内容を戻す。既存の記録は消さず、同じidは新しいほうを残す。
 *
 * 「混ぜる」動作にしてある。片方の端末で消した記録は、もう片方には残る。
 * 消したことを伝える印を持たない限り、削除は行き渡らない。消えるより残るほうが
 * 害が小さいので、こちらを既定にする。 */
/* 読み込んだファイルに APIキーが入っていても、書き戻さない。
   以前の版が書いたものが残っていることがある。次に保存したときに消える */
async function restoreBackup(payload) {
  if (!payload || payload.format !== BACKUP_FORMAT) throw new Error("この生きものノートの書き出しファイルではありません");
  const records = Array.isArray(payload.records) ? payload.records : [];
  const db = await backupDb();
  let restored = 0;
  for (const record of records) {
    if (!record?.id) continue;
    const entry = {...record};
    /* 新しい書き出しは thumbnails だけを持つ。古いものは thumbnail 1枚だけ持つ */
    entry.thumbnails = Array.isArray(record.thumbnails)
      ? record.thumbnails.map(dataUrlToBlob).filter(Boolean) : [];
    if (!entry.thumbnails.length) {
      const single = dataUrlToBlob(record.thumbnail);
      if (single) entry.thumbnails = [single];
    }
    entry.thumbnail = entry.thumbnails[0] || null;
    /* 予算の都合で写真を落としたぶんが入っていることがある。写真のない側で
       写真のある手元を上書きしない。書き出しは新しい記録から詰めるので、
       古い記録ほどこの形で戻ってくる */
    const reading = db.transaction("entries", "readonly");
    const existing = await backupRequest(reading.objectStore("entries").get(record.id));
    await backupTransaction(reading);
    if (!entry.thumbnails.length && existing) {
      const kept = (Array.isArray(existing.thumbnails) && existing.thumbnails.length)
        ? existing.thumbnails : (existing.thumbnail ? [existing.thumbnail] : []);
      if (kept.length) { entry.thumbnails = kept; entry.thumbnail = kept[0]; }
    }
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

/* 記録が増減するたびに呼ばれる。まとめて1回だけ書くよう少し待つ。
   ドライブにつながっていないときは何もしない (記録は端末の中に残る) */
let backupTimer = null;
function scheduleAutoBackup() {
  /* 運営者用も書く。以前は「試し撮りが利用者の記録に混ざる」を理由に止めていたが、
     混ざるのは保存先が同じファイルだったからで、書き込み自体が悪かったのではない。
     いまはモードごとに別ファイルへ書く (gdrive.js の driveFileName)。止めていた間、
     運営者用の記録はその端末のブラウザから出られなかった。 */
  clearTimeout(backupTimer);
  backupTimer = setTimeout(() => {
    if (typeof autoSaveToDrive === "function") autoSaveToDrive();
  }, 1500);
}

/* 記録に残す縮小画像。撮影画面と記録画面の両方が作る (記録側は足した写真ぶん)。
   長辺はサーバーが外部AIへ送る上限と同じ 1600px にそろえる (vision.MAX_EDGE)。
   これより小さく持つと、記録から「調べ直す」ときだけ元より低い解像度で走る。
   これより大きく持っても、送る前に縮められるので意味がない。
   実カメラ写真 (1200x1600) で測ると 1600px で中央値 324KB、960px で 122KB。
   ドライブへ持ち出すぶんは backupPhotoBudget で別に絞る。 */
const HISTORY_MAX_EDGE = 1600;
async function shrinkForHistory(file){if(!file)return null;const bitmap=await createImageBitmap(file);const scale=Math.min(1,HISTORY_MAX_EDGE/Math.max(bitmap.width,bitmap.height));const canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));canvas.getContext("2d").drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close();return new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",.78))}
