// Frozen acceptance oracle from a64a8fac, before the bounded header optimization.
const MAX_WIRE = 3 * Math.ceil((2 * 1024 * 1024) / 3) * 4 + 32768;
const MAX_PHOTO = 2 * 1024 * 1024;
export async function legacyValidate(blob, expectedJSON, count) {
  if (!(blob instanceof Blob) || blob.type !== 'application/json' || !blob.size || blob.size > MAX_WIRE ||
      !Number.isInteger(count) || count < 1 || count > 3) throw new TypeError('template');
  const wire = await blob.text();
  const payload = JSON.parse(wire), expected = JSON.parse(expectedJSON);
  if (JSON.stringify(payload) !== wire) throw new TypeError('template');
  const parts = payload.contents?.[0]?.parts;
  if (!Array.isArray(parts) || parts.length !== count + 1) throw new TypeError('template');
  for (const part of parts.slice(0, count)) {
    if (Object.keys(part).join() !== 'inline_data' || Object.keys(part.inline_data).join() !== 'mime_type,data' ||
        part.inline_data.mime_type !== 'image/jpeg') throw new TypeError('photo');
    const encoded = part.inline_data.data;
    if (typeof encoded !== 'string' || !encoded.length || encoded.length > Math.ceil(MAX_PHOTO / 3) * 4 ||
        encoded.length % 4 !== 0 || /[^A-Za-z0-9+/=]/.test(encoded)) throw new TypeError('photo');
    jpegDimensions(Uint8Array.fromBase64(encoded, {lastChunkHandling: 'strict'}));
  }
  payload.contents[0].parts = [parts[count]];
  if (JSON.stringify(payload) !== JSON.stringify(expected)) throw new TypeError('template');
}

function jpegDimensions(raw) {
  const invalid = () => {throw new TypeError('photo');};
  if (!raw.length || raw.length > MAX_PHOTO || raw[0] !== 255 || raw[1] !== 216 ||
      raw.at(-2) !== 255 || raw.at(-1) !== 217) invalid();
  let cursor = 2, dimensions;
  const word = offset => (raw[offset] << 8) | raw[offset + 1];
  for (let index = 0; index < 128; index++) {
    if (cursor + 4 > Math.min(raw.length, 65536) || raw[cursor] !== 255) break;
    while (cursor < raw.length && raw[cursor] === 255) cursor++;
    if (cursor + 3 > raw.length) break;
    const marker = raw[cursor++], length = word(cursor);
    if (length < 2 || cursor + length > Math.min(raw.length, 65536)) break;
    if (marker === 254 || (marker >= 224 && marker <= 239 && marker !== 224 && marker !== 226)) break;
    if (marker === 192 || marker === 194) {
      if (dimensions || length !== 17 || raw[cursor + 2] !== 8 || raw[cursor + 7] !== 3) break;
      const height = word(cursor + 3), width = word(cursor + 5);
      if (width < 1 || width > 1600 || height < 1 || height > 1600) break;
      dimensions = [width, height];
    }
    if (marker === 218) {
      if (dimensions && length >= 6) return dimensions;
      break;
    }
    cursor += length;
  }
  invalid();
}

