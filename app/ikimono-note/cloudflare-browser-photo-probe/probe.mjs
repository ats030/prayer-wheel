import libheif from './node_modules/libheif-js/libheif-wasm/libheif-bundle.mjs';
import exifr from './node_modules/exifr/dist/full.esm.mjs';
import {readPhotoZip} from './zip.mjs';

const heif = await libheif();

// exifr 7.1.3 discards iloc base_offset. This bounded correction handles only
// file-offset, single-extent HEIF items; unsupported layouts must not pass silently.
exifr.fileParsers.get('heic').prototype.findExtentInIloc = function(box, wanted) {
  // findExifLocIdInIinf returns undefined for a valid file without EXIF.
  if (wanted === undefined) return undefined;
  this.parseBoxFullHead(box);
  if (![0, 1, 2].includes(box.version)) throw new Error('Unsupported iloc version');
  let cursor = box.start;
  const [offsetSize, lengthSize] = this.get8bits(cursor++);
  const [baseSize, rawIndexSize] = this.get8bits(cursor++);
  const indexSize = box.version === 0 ? 0 : rawIndexSize;
  const idSize = box.version === 2 ? 4 : 2;
  const count = this.file.getUintBytes(cursor, idSize);
  cursor += idSize;
  for (let item = 0; item < count; item++) {
    const id = this.file.getUintBytes(cursor, idSize);
    cursor += idSize;
    let method = 0;
    if (box.version !== 0) {
      method = this.file.getUint16(cursor) & 15;
      cursor += 2;
    }
    const reference = this.file.getUint16(cursor);
    cursor += 2;
    const base = baseSize ? this.file.getUintBytes(cursor, baseSize) : 0;
    cursor += baseSize;
    const extents = this.file.getUint16(cursor);
    cursor += 2;
    if (id === wanted) {
      if (method !== 0 || reference !== 0 || extents !== 1) {
        throw new Error('HEIF layout not covered by this probe');
      }
      const offset = offsetSize ? this.file.getUintBytes(cursor + indexSize, offsetSize) : 0;
      const length = lengthSize ? this.file.getUintBytes(cursor + indexSize + offsetSize, lengthSize) : 0;
      if (!Number.isSafeInteger(base + offset) || !Number.isSafeInteger(length) || length <= 0) {
        throw new Error('Invalid HEIF extent');
      }
      return [base + offset, length];
    }
    cursor += extents * (indexSize + offsetSize + lengthSize);
  }
  throw new Error('HEIF EXIF item not found');
};

function captureContext(metadata) {
  const captured = metadata?.DateTimeOriginal ?? metadata?.[36867]
    ?? metadata?.CreateDate ?? metadata?.[36868] ?? metadata?.ModifyDate ?? metadata?.[306];
  const context = {};
  if (typeof captured === 'string' && /^\d{4}:\d{2}:\d{2}/.test(captured)) {
    // EXIF is a local capture time. Preserve its calendar date, without UTC conversion.
    context.observed_date = captured.slice(0, 10).replaceAll(':', '-');
  }
  if (Number.isFinite(metadata?.latitude) && Number.isFinite(metadata?.longitude)
      && Math.abs(metadata.latitude) <= 90 && Math.abs(metadata.longitude) <= 180) {
    context.latitude = Number(metadata.latitude.toFixed(4));
    context.longitude = Number(metadata.longitude.toFixed(4));
  }
  return context;
}

window.probe = async function(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Fixture HTTP ${response.status}`);
  const raw = new Uint8Array(await response.arrayBuffer());
  return probeBytes(raw);
};

window.probeZip = async function(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Fixture HTTP ${response.status}`);
  const {name, photo} = await readPhotoZip(new Uint8Array(await response.arrayBuffer()));
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', photo))]
    .map(byte => byte.toString(16).padStart(2,'0')).join('');
  return {name, digest, result: await probeBytes(photo)};
};

async function probeBytes(raw) {
  if (raw.length > 15 * 1024 * 1024) throw new Error('Photo exceeds 15 MiB');
  const metadata = await exifr.parse(raw, {tiff: true, exif: true, gps: true, reviveValues: false});
  if (metadata?.errors?.length) throw new Error(metadata.errors.map(error => error.message).join('; '));
  const images = new heif.HeifDecoder().decode(raw);
  if (images.length !== 1) {
    images.forEach(image => image.free());
    throw new Error('Probe requires one HEIC image');
  }
  try {
    const image = images[0];
    const canvas = document.createElement('canvas');
    canvas.width = image.get_width();
    canvas.height = image.get_height();
    const context = canvas.getContext('2d');
    const pixels = context.createImageData(canvas.width, canvas.height);
    await new Promise((resolve, reject) => image.display(pixels, display => display
      ? resolve() : reject(new Error('HEIC display failed'))));
    context.putImageData(pixels, 0, 0);
    const output = document.createElement('canvas');
    const scale = Math.min(1, 1600 / Math.max(canvas.width, canvas.height));
    output.width = Math.round(canvas.width * scale);
    output.height = Math.round(canvas.height * scale);
    output.getContext('2d').drawImage(canvas, 0, 0, output.width, output.height);
    const jpeg = await new Promise(resolve => output.toBlob(resolve, 'image/jpeg', 0.86));
    if (!jpeg) throw new Error('JPEG encoding failed');
    const after = await exifr.parse(jpeg, {reviveValues: false});
    return {
      dimensions: [canvas.width, canvas.height],
      context: captureContext(metadata),
      outputDimensions: [output.width, output.height],
      corners: [[50,50], [canvas.width-51,50], [50,canvas.height-51],
        [canvas.width-51,canvas.height-51]].map(([x,y]) => [...context.getImageData(x,y,1,1).data].slice(0,3)),
      jpegBytes: jpeg.size, jpegType: jpeg.type,
      outputHasExif: after != null && Object.keys(after).length !== 0,
    };
  } finally {
    images.forEach(image => image.free());
  }
}
