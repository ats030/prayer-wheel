// Read the app's single-photo ZIP contract in the browser.
// Read central-directory metadata and stream decompression; never extract paths.
const LIMIT = 15 * 1024 * 1024;
const decoder = new TextDecoder('utf-8', {fatal: true});
const crcTable = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  let value = i;
  for (let bit = 0; bit < 8; bit++) value = value & 1 ? (value >>> 1) ^ 0xedb88320 : value >>> 1;
  crcTable[i] = value >>> 0;
}
function crc32(raw) {
  let value = 0xffffffff;
  for (const byte of raw) value = crcTable[(value ^ byte) & 255] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}
function invalid(reason) { throw new Error(`ZIPを読み取れませんでした: ${reason}`); }

export async function readPhotoZip(raw) {
  if (raw.length > LIMIT || raw.length < 22) invalid('archive size');
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  let end = -1;
  for (let cursor = raw.length-22; cursor >= Math.max(0, raw.length-65557); cursor--) {
    if (view.getUint32(cursor, true) === 0x06054b50
        && cursor+22+view.getUint16(cursor+20, true) === raw.length) {
      end = cursor; break;
    }
  }
  if (end < 0) invalid('end record');
  const count = view.getUint16(end+10, true);
  const centralSize = view.getUint32(end+12, true);
  const centralStart = view.getUint32(end+16, true);
  if (view.getUint16(end+4, true) !== 0 || view.getUint16(end+6, true) !== 0
      || view.getUint16(end+8, true) !== count || count > 64
      || centralStart+centralSize !== end) invalid('multi-disk, ZIP64 or directory bounds');
  const entries = [];
  let cursor = centralStart;
  for (let index = 0; index < count; index++) {
    if (cursor+46 > end || view.getUint32(cursor, true) !== 0x02014b50) invalid('central header');
    const nameLength = view.getUint16(cursor+28, true);
    const extraLength = view.getUint16(cursor+30, true);
    const commentLength = view.getUint16(cursor+32, true);
    const next = cursor+46+nameLength+extraLength+commentLength;
    if (next > end || nameLength === 0) invalid('filename bounds');
    const name = decoder.decode(raw.subarray(cursor+46, cursor+46+nameLength));
    if (view.getUint16(cursor+34, true) !== 0) invalid('entry disk');
    entries.push({name, flags: view.getUint16(cursor+8, true), method: view.getUint16(cursor+10, true),
      crc: view.getUint32(cursor+16, true), compressed: view.getUint32(cursor+20, true),
      size: view.getUint32(cursor+24, true), attributes: view.getUint32(cursor+38, true),
      offset: view.getUint32(cursor+42, true)});
    cursor = next;
  }
  if (cursor !== end) invalid('directory length');
  const files = entries.filter(entry => !entry.name.endsWith('/')
    && !entry.name.startsWith('__MACOSX/') && entry.name.split('/').at(-1) !== '.DS_Store');
  if (files.length !== 1) invalid('one photograph required');
  const entry = files[0];
  const parts = entry.name.split('/');
  if (!parts.at(-1) || parts.at(-1).length > 200 || entry.name.startsWith('/')
      || parts.includes('..') || entry.name.includes('\\')
      || ((entry.attributes >>> 16) & 0xf000) === 0xa000) invalid('unsafe path or symlink');
  if ((entry.flags & 1) !== 0 || ![0,8].includes(entry.method) || entry.size > LIMIT) invalid('encryption, method or photo size');
  const offset = entry.offset;
  if (offset+30 > centralStart || view.getUint32(offset, true) !== 0x04034b50) invalid('local header');
  const localNameLength = view.getUint16(offset+26, true);
  const start = offset+30+localNameLength+view.getUint16(offset+28, true);
  if (start+entry.compressed > centralStart || view.getUint16(offset+8, true) !== entry.method
      || view.getUint16(offset+6, true) !== entry.flags
      || decoder.decode(raw.subarray(offset+30, offset+30+localNameLength)) !== entry.name) invalid('local/central mismatch');
  const compressed = raw.subarray(start, start+entry.compressed);
  let photo;
  if (entry.method === 0) photo = compressed;
  else {
    const reader = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();
    const chunks = [];
    let size = 0;
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.length;
        if (size > LIMIT || size > entry.size) invalid('decompressed size');
        chunks.push(chunk.value);
      }
    } finally { await reader.cancel().catch(() => {}); }
    photo = new Uint8Array(size);
    let position = 0;
    for (const chunk of chunks) { photo.set(chunk, position); position += chunk.length; }
  }
  if (photo.length !== entry.size || crc32(photo) !== entry.crc) invalid('size or CRC');
  return {name: parts.at(-1), photo};
}
