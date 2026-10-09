// Called only from the authenticated ASGI /identify handler. No public router.
const MAX_PHOTO = 2 * 1024 * 1024;
export const MAX_WIRE = 3 * Math.ceil(MAX_PHOTO / 3) * 4 + 32768;

export function jpegDimensions(raw) {
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

export async function validatePayload(blob, expectedJSON, count) {
  if (!(blob instanceof Blob) || blob.type !== 'application/json' || !blob.size || blob.size > MAX_WIRE ||
      !Number.isInteger(count) || count < 1 || count > 3) throw new TypeError('template');
  const wire = await blob.text();
  const payload = JSON.parse(wire), expected = JSON.parse(expectedJSON);
  // Canonical browser JSON excludes duplicate keys and ambiguous encodings.
  if (JSON.stringify(payload) !== wire) throw new TypeError('template');
  const parts = payload.contents?.[0]?.parts;
  if (!Array.isArray(parts) || parts.length !== count + 1) throw new TypeError('template');
  for (const part of parts.slice(0, count)) {
    if (Object.keys(part).join() !== 'inline_data' ||
        Object.keys(part.inline_data).join() !== 'mime_type,data' ||
        part.inline_data.mime_type !== 'image/jpeg') throw new TypeError('photo');
    const encoded = part.inline_data.data;
    if (typeof encoded !== 'string' || !encoded.length || encoded.length > Math.ceil(MAX_PHOTO / 3) * 4 ||
        encoded.length % 4 !== 0 || /[^A-Za-z0-9+/=]/.test(encoded)) throw new TypeError('photo');
    const raw = Uint8Array.fromBase64(encoded, {lastChunkHandling: 'strict'});
    jpegDimensions(raw);
  }
  payload.contents[0].parts = [parts[count]];
  if (JSON.stringify(payload) !== JSON.stringify(expected)) throw new TypeError('template');
}

export async function identify(blob, expectedJSON, count, model, key, fetcher = fetch) {
  try {await validatePayload(blob, expectedJSON, count);}
  catch {return JSON.stringify({error: 'input'});}
  // Neither the endpoint nor the model is taken from the uploaded JSON.
  if (!/^[a-zA-Z0-9._-]+$/.test(model) || !key || key.length > 512) return JSON.stringify({error: 'input'});
  try {
    const response = await fetcher('https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent', {
      method: 'POST', body: blob.stream(), redirect: 'error',
      headers: {'x-goog-api-key': key, 'content-type': 'application/json'},
      signal: AbortSignal.timeout(180000),
    });
    if (!response.ok) {await response.body?.cancel(); return JSON.stringify({status: response.status});}
    // Bound provider output before crossing the Python FFI boundary.
    const reader = response.body.getReader(), chunks = [];
    let length = 0;
    try {
      while (true) {
        const item = await reader.read();
        if (item.done) break;
        length += item.value.length;
        if (length > 2 * 1024 * 1024) {await reader.cancel(); throw new Error('response');}
        chunks.push(item.value);
      }
    } finally {reader.releaseLock();}
    const bytes = new Uint8Array(length); let cursor = 0;
    for (const chunk of chunks) {bytes.set(chunk, cursor); cursor += chunk.length;}
    const data = JSON.parse(new TextDecoder().decode(bytes));
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('response');
    return JSON.stringify({status: response.status, data});
  } catch {return JSON.stringify({error: 'connection'});}
}
