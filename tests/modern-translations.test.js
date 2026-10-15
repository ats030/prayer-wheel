import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { modernTranslations } from '../modern-translations.js';

test('every source passage has exactly one nonempty modern translation', () => {
  const { chunks } = JSON.parse(readFileSync(new URL('../data/sutra.json', import.meta.url), 'utf8'));
  assert.equal(modernTranslations.size, chunks.length);
  assert.deepEqual([...modernTranslations.keys()].sort(), chunks.map(c => c.text).sort());
  for (const { text } of chunks) assert.ok(modernTranslations.get(text).trim(), text);
});
