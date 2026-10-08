import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';

const expected = JSON.parse(await readFile(new URL('./fixtures/quality-expected.json', import.meta.url)));
const browser = await chromium.launch({headless: true});
const results = [], mismatches = [], numericMismatches = [];
try {
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:8791/');
  const rounded = await page.evaluate(async () => {
    const {roundOneDecimal} = await import('./round.mjs');
    return [14.95, 24.95, 9.95, 49.95, 0.25, 0.75, 0, -0.25].map(roundOneDecimal);
  });
  assert.deepEqual(rounded, [14.9, 24.9, 9.9, 50, 0.2, 0.8, 0, -0.2]);
  for (const [name, reference] of Object.entries(expected)) {
    const result = await page.evaluate(async name => {
      const {judgeCanvas} = await import('./quality.mjs');
      const response = await fetch(`fixtures/${name}`);
      if (!response.ok) throw new Error(`Fixture HTTP ${response.status}`);
      const bitmap = await createImageBitmap(await response.blob());
      try {
        const canvas = document.createElement('canvas');
        canvas.width = bitmap.width; canvas.height = bitmap.height;
        canvas.getContext('2d').drawImage(bitmap, 0, 0);
        return {corrected: judgeCanvas(canvas), canvasBaseline: judgeCanvas(canvas, false)};
      } finally { bitmap.close(); }
    }, name);
    for (const field of ['width', 'height', 'pixels', 'brightness', 'contrast', 'sharpness']) {
      const actual = result.corrected.measured[field];
      const expectedValue = reference.measured[field];
      if (!Number.isFinite(actual) || Math.abs(actual - expectedValue) > 0.1) {
        numericMismatches.push({name, field, expected: expectedValue, actual});
      }
    }
    const same = JSON.stringify(result.corrected.problems) === JSON.stringify(reference.problems)
      && result.corrected.ok === reference.ok && result.corrected.level === reference.level;
    if (!same) mismatches.push(name);
    results.push({name, sameDecision: same, reference, browser: result.corrected, canvasBaseline: result.canvasBaseline});
  }
  // Report discrepancies as evidence; do not turn a failed compatibility verdict into a test pass.
  await writeFile(new URL('./fixtures/quality-comparison.json', import.meta.url), JSON.stringify(results, null, 2)+'\n');
  console.log(JSON.stringify({fixtures: results.length, mismatches, numericMismatches,
    maxSharpnessDifference: Math.max(...results.map(r => Math.abs(r.reference.measured.sharpness-r.browser.measured.sharpness))),
    canvasBaselineMismatches: results.filter(r => JSON.stringify(r.canvasBaseline.problems) !== JSON.stringify(r.reference.problems)).map(r => r.name),
    canvasBaselineMaxSharpnessDifference: Math.max(...results.map(r => Math.abs(r.reference.measured.sharpness-r.canvasBaseline.measured.sharpness))),
    report: 'fixtures/quality-comparison.json'}));
  if (mismatches.length || numericMismatches.length) process.exitCode = 2;
} finally { await browser.close(); }
