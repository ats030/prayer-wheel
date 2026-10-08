// Only enabled by the Workers profile. No photograph or metadata is uploaded here.
import exifr from '/vendor/photo/exifr.mjs';
import {judgeCanvas} from './photo-quality.mjs';
import {readPhotoZip} from './photo-zip.mjs';

const LIMIT = 15 * 1024 * 1024;
const MAX_PIXELS = 50_000_000;
const prepared = new WeakMap();
let decoderModule;
let preparationQueue = Promise.resolve();
export const browserPhotosEnabled = () => document.body.dataset.browserPhotos === '1';

// exifr 7.1.3 ignores HEIF iloc base_offset. Keep the correction outside
// the unmodified library. Unsupported EXIF layouts fail visibly.
exifr.fileParsers.get('heic').prototype.findExtentInIloc = function(box, wanted) {
  if (wanted === undefined) return undefined;
  this.parseBoxFullHead(box);
  if (![0, 1, 2].includes(box.version)) throw new Error('対応していないHEICの撮影情報です');
  let cursor = box.start;
  const [offsetSize, lengthSize] = this.get8bits(cursor++);
  const [baseSize, rawIndexSize] = this.get8bits(cursor++);
  const indexSize = box.version === 0 ? 0 : rawIndexSize;
  const idSize = box.version === 2 ? 4 : 2;
  const count = this.file.getUintBytes(cursor, idSize);
  cursor += idSize;
  for (let item = 0; item < count; item++) {
    const id = this.file.getUintBytes(cursor, idSize); cursor += idSize;
    let method = 0;
    if (box.version !== 0) { method = this.file.getUint16(cursor) & 15; cursor += 2; }
    const reference = this.file.getUint16(cursor); cursor += 2;
    const base = baseSize ? this.file.getUintBytes(cursor, baseSize) : 0; cursor += baseSize;
    const extents = this.file.getUint16(cursor); cursor += 2;
    if (id === wanted) {
      if (method !== 0 || reference !== 0 || extents !== 1) {
        throw new Error('対応していないHEICの撮影情報です。別の元写真を選んでください。');
      }
      const offset = offsetSize ? this.file.getUintBytes(cursor + indexSize, offsetSize) : 0;
      const length = lengthSize ? this.file.getUintBytes(cursor + indexSize + offsetSize, lengthSize) : 0;
      if (!Number.isSafeInteger(base + offset) || !Number.isSafeInteger(length) || length <= 0) {
        throw new Error('HEICの撮影情報を読み取れませんでした');
      }
      return [base + offset, length];
    }
    cursor += extents * (indexSize + offsetSize + lengthSize);
  }
  throw new Error('HEICの撮影情報を読み取れませんでした');
};

function captureContext(metadata) {
  const captured = metadata?.DateTimeOriginal ?? metadata?.[36867]
    ?? metadata?.CreateDate ?? metadata?.[36868] ?? metadata?.ModifyDate ?? metadata?.[306];
  const context = {};
  if (typeof captured === 'string' && /^\d{4}:\d{2}:\d{2}/.test(captured)) {
    context.observed_date = captured.slice(0, 10).replaceAll(':', '-');
  }
  if (Number.isFinite(metadata?.latitude) && Number.isFinite(metadata?.longitude)
      && Math.abs(metadata.latitude) <= 90 && Math.abs(metadata.longitude) <= 180) {
    context.latitude = Number(metadata.latitude.toFixed(4));
    context.longitude = Number(metadata.longitude.toFixed(4));
    context.location = `緯度 ${context.latitude.toFixed(4)}, 経度 ${context.longitude.toFixed(4)}`;
  } else if (metadata && ['GPSLatitude', 'GPSLongitude', 'GPSLatitudeRef', 'GPSLongitudeRef']
      .some(key => Object.hasOwn(metadata, key))) context.gps_status = 'unreadable';
  return context;
}

function checkSize(width, height) {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1
      || width * height > MAX_PIXELS || Math.max(width, height) > 16384) {
    throw new Error('この写真は大きすぎて読み取れません。別の写真を選んでください。');
  }
}

// Bound common compressed formats before asking the browser to allocate pixels.
function checkHeaderSize(raw) {
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  if (raw.length >= 24 && view.getUint32(0) === 0x89504e47) {
    checkSize(view.getUint32(16), view.getUint32(20));
  } else if (raw.length >= 10 && String.fromCharCode(...raw.subarray(0, 3)) === 'GIF') {
    checkSize(view.getUint16(6, true), view.getUint16(8, true));
  } else if (raw.length >= 4 && raw[0] === 255 && raw[1] === 216) {
    let cursor = 2;
    while (cursor + 4 <= raw.length) {
      if (raw[cursor++] !== 255) break;
      while (raw[cursor] === 255) cursor++;
      const marker = raw[cursor++];
      if (marker === 0xda || marker === 0xd9) break;
      const length = view.getUint16(cursor);
      if (length < 2 || cursor + length > raw.length) break;
      if ([0xc0, 0xc1, 0xc2].includes(marker) && length >= 8) {
        checkSize(view.getUint16(cursor + 5), view.getUint16(cursor + 3)); return;
      }
      cursor += length;
    }
  }
}

const jpeg = (canvas, quality) => new Promise((resolve, reject) => {
  canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('写真を準備できませんでした')), 'image/jpeg', quality);
});

async function decode(file, raw) {
  const heic = raw.length >= 12 && String.fromCharCode(...raw.subarray(4, 8)) === 'ftyp';
  if (heic) {
    decoderModule ||= import('/vendor/photo/libheif.mjs').then(({default: factory}) => factory());
    const heif = await decoderModule;
    const decoder = new heif.HeifDecoder();
    let images = [];
    try {
      images = decoder.decode(raw);
      const primary = images.filter(image => image.is_primary());
      const image = primary.length === 1 ? primary[0] : images.length === 1 ? images[0] : null;
      if (!image) throw new Error('HEICの写真を読み取れませんでした');
      const width = image.get_width(), height = image.get_height();
      checkSize(width, height);
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
      const context = canvas.getContext('2d', {willReadFrequently: true});
      const pixels = context.createImageData(width, height);
      await new Promise((resolve, reject) => image.display(pixels, display => display
        ? resolve() : reject(new Error('HEICの写真を読み取れませんでした'))));
      context.putImageData(pixels, 0, 0);
      return canvas;
    } finally {
      images.forEach(image => image.free());
      if (decoder.decoder) heif.heif_context_free(decoder.decoder);
    }
  }
  checkHeaderSize(raw);
  const bitmap = await createImageBitmap(file);
  try {
    checkSize(bitmap.width, bitmap.height);
    const canvas = document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height;
    canvas.getContext('2d', {willReadFrequently: true}).drawImage(bitmap, 0, 0);
    return canvas;
  } finally { bitmap.close(); }
}

export function preparePhoto(file) {
  if (!prepared.has(file)) {
    const promise = preparationQueue.then(async () => {
      if (!file.size || file.size > LIMIT) throw new Error('写真は1枚15MB以下にしてください');
      const raw = new Uint8Array(await file.arrayBuffer());
      const metadata = await exifr.parse(raw, {tiff: true, exif: true, gps: true, reviveValues: false});
      if (metadata?.errors?.length) throw new Error('写真の撮影情報を読み取れませんでした。別の元写真を選んでください。');
      const canvas = await decode(file, raw);
      try {
        const quality = judgeCanvas(canvas);
        const scale = Math.min(1, 1600 / Math.max(canvas.width, canvas.height));
        const output = document.createElement('canvas');
        output.width = Math.max(1, Math.round(canvas.width * scale));
        output.height = Math.max(1, Math.round(canvas.height * scale));
        const context = output.getContext('2d'); context.imageSmoothingQuality = 'high';
        context.drawImage(canvas, 0, 0, output.width, output.height);
        let blob;
        for (const quality of [.86, .78, .68, .55]) {
          blob = await jpeg(output, quality);
          if (blob.size <= 2 * 1024 * 1024) break;
        }
        if (blob.size > 2 * 1024 * 1024) throw new Error('写真を送信できる大きさにできませんでした。別の写真を選んでください。');
        output.width = output.height = 0;
        return {photo: blob, metadata: captureContext(metadata), quality,
                dimensions: [canvas.width, canvas.height]};
      } finally { canvas.width = canvas.height = 0; }
    });
    preparationQueue = promise.catch(() => {});
    prepared.set(file, promise);
  }
  return prepared.get(file);
}

export async function originalFromZip(file) {
  if (file.size > LIMIT) throw new Error('ZIPは15MB以下にしてください');
  const {name, photo} = await readPhotoZip(new Uint8Array(await file.arrayBuffer()));
  const type = /\.hei[cf]$/i.test(name) ? 'image/heic' : /\.png$/i.test(name) ? 'image/png' : 'image/jpeg';
  const original = new File([photo], name, {type});
  await preparePhoto(original); // Validate while retaining original bytes and EXIF.
  return original;
}

export async function normalizePhotos(files) {
  const photos = [];
  for (const file of files) {
    if (/\.zip$/i.test(file.name) || file.type === 'application/zip') photos.push(await originalFromZip(file));
    else if (file.type.startsWith('image/') || /\.hei[cf]$/i.test(file.name)) photos.push(file);
  }
  return photos;
}

export async function metadataForPhotos(files) {
  const combined = {};
  for (const file of files) {
    const {metadata} = await preparePhoto(file);
    for (const [key, value] of Object.entries(metadata)) if (!Object.hasOwn(combined, key)) combined[key] = value;
  }
  return combined;
}

export async function appendPreparedPhotos(form, files) {
  const reports = [];
  for (let index = 0; index < files.length; index++) {
    const result = await preparePhoto(files[index]);
    if (!result.quality.ok) throw new Error(result.quality.problems.some(p => p.reason === 'dark' && p.level === 'block')
      ? '写真が暗すぎて、何が写っているか分かりません。明るい場所で撮り直してください。'
      : '写真が小さすぎます。もっと大きな写真で撮り直してください。');
    form.append('files', result.photo, `photo-${index+1}.jpg`);
    reports.push({metadata: result.metadata, measured: result.quality.measured});
  }
  form.append('client_photos', JSON.stringify(reports));
}
