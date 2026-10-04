// 写真から読み取った座標だけを扱う。端末の現在地は取得しない。
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
    return new File([photo], name, {type: photo.type});
  } finally {
    clearTimeout(timeout);
  }
}

export async function readPhotoLocation(files) {
  const form = new FormData();
  files.forEach(file => form.append("files", file));
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch("/api/photo-metadata", {
      method: "POST", body: form, signal: controller.signal,
    });
    if (!response.ok) throw new Error("写真の情報を読み取れませんでした。元写真を選んで、もう一度お試しください。");
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

export function recordWithPhotoLocation(record, data, confirmReplace) {
  const coordinates = photoCoordinates(data);
  if (!coordinates) throw new Error("この写真からは位置情報を読み取れませんでした。元写真1枚をZIPに入れ、「元写真ZIPを選ぶ」をお試しください。ZIPに入れる前に位置情報が失われている場合は補えません。記録は変更していません。");
  const location = coordinateLabel(coordinates);
  const existing = record.coordinates != null || Boolean(record.context?.location?.trim());
  const unchanged = record.coordinates?.latitude === coordinates.latitude &&
    record.coordinates?.longitude === coordinates.longitude && record.context?.location === location;
  if (existing && !unchanged && !confirmReplace(
    "この記録には場所が入っています。元写真の撮影場所に置き換えますか？\n" + location)) return null;
  return {...record, coordinates, context: {...record.context, location}};
}
