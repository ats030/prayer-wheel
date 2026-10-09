// Called only from the authenticated ASGI /identify handler. No public router.
const MAX_PHOTO = 2 * 1024 * 1024;
export const MAX_WIRE = 3 * Math.ceil(MAX_PHOTO / 3) * 4 + 32768;

export function jpegDimensions(raw) {
  return jpegHeaderDimensions(raw, raw.length, raw);
}

function jpegHeaderDimensions(raw, totalLength, tail) {
  const invalid = () => {throw new TypeError('photo');};
  if (!raw.length || totalLength > MAX_PHOTO || raw[0] !== 255 || raw[1] !== 216 ||
      tail.at(-2) !== 255 || tail.at(-1) !== 217) invalid();
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
  const expected = JSON.parse(expectedJSON);
  const parts = expected.contents?.[0]?.parts;
  if (!Array.isArray(parts) || parts.length !== 1) throw new TypeError('template');
  // A unique marker locates this exact parts value even if the prompt contains
  // JSON fragments. Only the small authoritative template is parsed/generated.
  const canonical = JSON.stringify(expected);
  let marker = '__ikimono_photo_parts__';
  while (canonical.includes(marker)) marker += '_';
  expected.contents[0].parts = marker;
  const frame = JSON.stringify(expected), token = JSON.stringify(marker);
  const offset = frame.indexOf(token);
  const prefix = frame.slice(0, offset) + '[';
  const suffix = ',' + JSON.stringify(parts[0]) + ']' + frame.slice(offset + token.length);
  // Separate ASCII photos from the small Unicode template. Do not widen every
  // photo character into one multi-MB UTF-16 string or schedule per-chunk work.
  const raw = new Uint8Array(await blob.arrayBuffer()), encoder = new TextEncoder();
  // Preserve BOM bytes as U+FEFF so canonical/ASCII checks can reject them.
  const decoder = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true});
  let cursor = 0;
  const consume = text => {
    const length = encoder.encode(text).length;
    if (cursor + length > raw.length || decoder.decode(raw.subarray(cursor, cursor + length)) !== text) throw new TypeError('template');
    cursor += length;
  };
  consume(prefix);
  for (let index = 0; index < count; index++) {
    if (index) consume(',');
    consume('{"inline_data":{"mime_type":"image/jpeg","data":"');
    const end = raw.indexOf(34, cursor), length = end - cursor;
    if (end < 0 || !length || length > Math.ceil(MAX_PHOTO / 3) * 4 || length % 4) throw new TypeError('photo');
    const encoded = decoder.decode(raw.subarray(cursor, end));
    if (/[^A-Za-z0-9+/=]/.test(encoded)) throw new TypeError('photo');
    const equals = encoded.indexOf('=');
    if (equals !== -1 && (equals < length - 2 || !/^={1,2}$/.test(encoded.slice(equals)))) throw new TypeError('photo');
    const padding = equals === -1 ? 0 : length - equals;
    // Strict final chunks validate padding/unused bits and both EOI bytes.
    jpegHeaderDimensions(Uint8Array.fromBase64(encoded.slice(0, Math.ceil(65536 / 3) * 4), {lastChunkHandling: 'strict'}),
      length / 4 * 3 - padding, Uint8Array.fromBase64(encoded.slice(-8), {lastChunkHandling: 'strict'}));
    cursor = end; consume('"}}');
  }
  if (raw.length - cursor !== encoder.encode(suffix).length) throw new TypeError('template');
  consume(suffix);
}

// Binary-upload candidate. The caller must authorize the request and supply
// the server's template; this helper never accepts a client-selected prompt.
export async function prepareBinaryPayload(files, expectedJSON) {
  if (!Array.isArray(files) || files.length < 1 || files.length > 3 ||
      files.some(file => !(file instanceof Blob) || file.type !== 'image/jpeg' ||
        !file.size || file.size > MAX_PHOTO)) throw new TypeError('photo');
  if (typeof expectedJSON !== 'string' || expectedJSON.length > 32768) throw new TypeError('template');
  const template = JSON.parse(expectedJSON), parts = template.contents?.[0]?.parts;
  if (!Array.isArray(parts) || parts.length !== 1) throw new TypeError('template');
  const canonical = JSON.stringify(template);
  let marker = '__ikimono_binary_parts__';
  while (canonical.includes(marker)) marker += '_';
  template.contents[0].parts = marker;
  const frame = JSON.stringify(template), token = JSON.stringify(marker), offset = frame.indexOf(token);
  const chunks = [frame.slice(0, offset), '['];
  for (const [index, file] of files.entries()) {
    const raw = new Uint8Array(await file.arrayBuffer());
    jpegDimensions(raw);
    if (index) chunks.push(',');
    chunks.push('{"inline_data":{"mime_type":"image/jpeg","data":"', raw.toBase64(), '"}}');
  }
  chunks.push(',', JSON.stringify(parts[0]), ']', frame.slice(offset + token.length));
  const payload = new Blob(chunks, {type: 'application/json'});
  if (payload.size > MAX_WIRE) throw new TypeError('template');
  return payload;
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
