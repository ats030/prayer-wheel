// 写真の読み取りと既存記録の座標更新。位置の選択はlocation-picker.mjsが扱う。
// Cache belongs to this exact returned File, never a filename or persisted record.
const originalMetadata = new WeakMap();
export function photoCoordinates(data) {
  const {latitude, longitude} = data || {};
  if (typeof latitude !== "number" || typeof longitude !== "number" ||
      !Number.isFinite(latitude) || !Number.isFinite(longitude) ||
      Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  return {latitude: Number(latitude.toFixed(4)), longitude: Number(longitude.toFixed(4))};
}

export function coordinateLabel(coordinates) {
  return `緯度 ${coordinates.latitude.toFixed(4)}, 経度 ${coordinates.longitude.toFixed(4)}`;
}

export function photoLocationState(data) {
  if (photoCoordinates(data)) return {code: "present", label: "GPSを読み取れました"};
  if (data?.gps_status === "unreadable") return {code: "unreadable", label: "GPSタグはありますが、値を読み取れません"};
  if (data?.gps_status === "exif_unreadable") return {code: "exif_unreadable", label: "写真のEXIFを解析できません"};
  return {code: "missing", label: "受け取った写真にGPSタグがありません"};
}

// This code stays in the browser; no filename, fingerprint or coordinates are logged.
export async function photoFingerprint(file) {
  if (file.size > 15 * 1024 * 1024) return "写真が15MBを超えています";
  try {
    const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    return [...new Uint8Array(digest)].slice(0, 8).map(byte => byte.toString(16).padStart(2, "0")).join("");
  } catch (_) { return "取得できませんでした"; }
}

export async function readOriginalZip(file) {
  if (file.size > 15 * 1024 * 1024) throw new Error("ZIPは15MB以下にしてください");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch("/api/photo-original", {
      method: "POST", body: file, headers: {"Content-Type": "application/zip"}, signal: controller.signal,
    });
    if (!response.ok) {
      let message = "ZIPを読み取れませんでした。元写真1枚をZIPに入れて選び直してください。";
      try {
        const data = await response.json();
        if (typeof data.detail === "string") message = data.detail;
      } catch (_) {}
      throw new Error(message);
    }
    const name = decodeURIComponent(response.headers.get("X-Photo-Name") || "photo");
    const photo = await response.blob();
    const original = new File([photo], name, {type: photo.type});
    const header = response.headers.get("X-Photo-Metadata");
    if (header) {
      try {
        const metadata = JSON.parse(decodeURIComponent(header));
        if (metadata && typeof metadata === "object" && !Array.isArray(metadata)) originalMetadata.set(original, metadata);
      } catch (_) { /* Older/incompatible responses use the existing metadata endpoint. */ }
    }
    return original;
  } finally {
    clearTimeout(timeout);
  }
}

export async function readPhotoLocation(files) {
  // The original ZIP response already read EXIF from these same bytes. Avoid a second upload.
  if (files.length && files.every(file => originalMetadata.has(file))) {
    const combined = {};
    files.forEach(file => {
      const data = originalMetadata.get(file);
      for (const key of ["observed_date", "latitude", "longitude", "location", "gps_status"]) {
        if (Object.prototype.hasOwnProperty.call(data, key) && !Object.prototype.hasOwnProperty.call(combined, key)) combined[key] = data[key];
      }
    });
    return combined;
  }
  const form = new FormData();
  files.forEach(file => form.append("files", file));
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch("/api/photo-metadata", {
      method: "POST", body: form, signal: controller.signal,
    });
    if (!response.ok) {
      const reason = response.status === 401 ? "ログイン状態を確認してください。" :
        response.status === 429 ? "少し待ってから選び直してください。" : "もう一度選び直してください。";
      throw new Error(`写真情報の問い合わせに失敗しました（HTTP ${response.status}）。${reason}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

export function recordWithPhotoLocation(record, data, confirmReplace) {
  const coordinates = photoCoordinates(data);
  if (!coordinates) throw new Error("この写真からは位置情報を読み取れませんでした。「撮影場所を指定する」から地図で補えます。記録は変更していません。");
  const location = data.manual ? String(data.location || coordinateLabel(coordinates)) : coordinateLabel(coordinates);
  const existing = record.coordinates != null || Boolean(record.context?.location?.trim());
  const unchanged = record.coordinates?.latitude === coordinates.latitude &&
    record.coordinates?.longitude === coordinates.longitude && record.context?.location === location;
  if (existing && !unchanged && !confirmReplace(
    "この記録には場所が入っています。選んだ撮影場所に置き換えますか？\n" + location)) return null;
  return {...record, coordinates, context: {...record.context, location}};
}
