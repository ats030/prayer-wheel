import {assembleProviderPayload} from './provider-payload.mjs';

const MAX_PHOTO = 2 * 1024 * 1024, MAX_REPLY = 2 * 1024 * 1024;
const inputError = () => new Error('写真の送信形式を確認してください。写真を選び直してください。');

// Preserve exactly the fields consumed by the authoritative result parser.
// Candidate text is never truncated, summarized or trusted in the browser.
export function compactGeminiReply(reply) {
  const candidate=reply?.candidates?.[0];
  if(!candidate||typeof candidate!=='object'||Array.isArray(candidate))return {candidates:[]};
  const parts=candidate.content?.parts;
  const compact={candidates:[{finishReason:candidate.finishReason,content:{parts:Array.isArray(parts)
    ?parts.filter(part=>part&&typeof part==='object'&&!Array.isArray(part)&&part.text).map(part=>({text:part.text}))
    :parts}}]};
  // Python's MAX_TOKENS diagnostic consumes this single usage field.
  if(reply.usageMetadata&&Object.hasOwn(reply.usageMetadata,'thoughtsTokenCount'))
    compact.usageMetadata={thoughtsTokenCount:reply.usageMetadata.thoughtsTokenCount};
  return compact;
}

// Same bounded header policy as prepared_photos.jpeg_dimensions. These are
// already browser-prepared JPEGs, never the original HEIC/EXIF-bearing files.
function checkJpeg(raw) {
  if (!raw.length || raw.length > MAX_PHOTO || raw[0] !== 255 || raw[1] !== 216 ||
      raw.at(-2) !== 255 || raw.at(-1) !== 217) throw inputError();
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
      dimensions = true;
    }
    if (marker === 218) {if (dimensions && length >= 6) return; break;}
    cursor += length;
  }
  throw inputError();
}

function detail(data) {
  const value = data?.detail;
  if (typeof value === 'string') return value;
  const notes = Array.isArray(value?.problems) ? value.problems.map(problem => problem.message).join(' ') : '';
  return (value?.message || '調べられませんでした') + (notes ? ' ' + notes : '');
}

async function sameOriginJSON(fetcher, path, data) {
  const response = await fetcher(path, {method: 'POST', credentials: 'same-origin', redirect: 'error',
    headers: {'content-type': 'application/json'}, body: JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(detail(result));
  return result;
}

async function replyJSON(response) {
  if (!response.body) throw new Error('Geminiの応答を読み取れませんでした');
  const reader = response.body.getReader(), chunks = [];
  let size = 0;
  try {
    while (true) {
      const item = await reader.read();
      if (item.done) break;
      size += item.value.length;
      if (size > MAX_REPLY) {await reader.cancel(); throw new Error('Geminiの応答を読み取れませんでした');}
      chunks.push(item.value);
    }
  } finally {reader.releaseLock();}
  const raw = new Uint8Array(size);
  let cursor = 0;
  for (const chunk of chunks) {raw.set(chunk, cursor); cursor += chunk.length;}
  const data = JSON.parse(new TextDecoder().decode(raw));
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('Geminiの応答を読み取れませんでした');
  return data;
}

export async function identifyWithBrowserGemini(form, fetcher = fetch) {
  const field = name => String(form.get(name) || '');
  const key = field('request_api_key').trim(), model = field('request_model');
  const files = form.getAll('files');
  if (field('request_provider') !== 'gemini' || field('use_plantnet') === 'true' ||
      !key || key.length > 512 || !/^[a-zA-Z0-9._-]+$/.test(model)) throw new Error('Geminiの設定を確認してください');
  if (files.length < 1 || files.length > 3 || files.some(file => !(file instanceof Blob) ||
      file.type !== 'image/jpeg' || !file.size || file.size > MAX_PHOTO)) throw inputError();
  const context = {model, count: files.length, client_photos: field('client_photos')};
  // The server checks login, rate/model and reports before provider HTTP. No
  // API key or photo bytes are included in either same-origin request.
  const template = await sameOriginJSON(fetcher, '/api/gemini/prepare', {...context,
    location: field('location'), observed_date: field('observed_date'), size: field('size')});
  const images = [];
  for (const file of files) {
    const raw = new Uint8Array(await file.arrayBuffer());
    checkJpeg(raw);
    if (typeof raw.toBase64 === 'function') images.push(raw.toBase64());
    else {
      const chunks = [];
      for (let cursor = 0; cursor < raw.length; cursor += 32768) chunks.push(String.fromCharCode(...raw.subarray(cursor, cursor + 32768)));
      images.push(btoa(chunks.join('')));
    }
  }
  const payload = assembleProviderPayload('gemini', template, images);
  let response;
  try {
    response = await fetcher('https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent', {
      method: 'POST', credentials: 'omit', mode: 'cors', redirect: 'error', referrerPolicy: 'no-referrer',
      headers: {'x-goog-api-key': key, 'content-type': 'application/json'},
      body: JSON.stringify(payload), signal: AbortSignal.timeout(180000),
    });
  } catch {throw new Error('Gemini APIに接続できませんでした');}
  if (!response.ok) {
    await response.body?.cancel();
    if ([401, 403].includes(response.status)) throw new Error('GeminiのAPIキーを確認してください');
    if (response.status === 429) throw new Error('Geminiの利用上限またはレート制限に達しました');
    throw new Error('Gemini APIで識別できませんでした（' + response.status + '）');
  }
  let reply;
  try {reply = await replyJSON(response);} catch {throw new Error('Geminiの応答を読み取れませんでした');}
  // Keep normalization, independent taxonomy/evidence and protected-species
  // checks in the existing authoritative pipeline before displaying/saving.
  return sameOriginJSON(fetcher, '/api/gemini/result', {...context, reply: JSON.stringify(compactGeminiReply(reply))});
}
