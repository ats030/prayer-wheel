import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';

const expected = JSON.parse(await readFile(new URL('./fixtures/expected.json', import.meta.url)));
const browser = await chromium.launch({headless: true});
try {
  // Both sides of UTC exercise calendar-date preservation.
  for (const timezoneId of ['Asia/Tokyo', 'America/Los_Angeles']) {
    const context = await browser.newContext({timezoneId});
    try {
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto('http://127.0.0.1:8791/');
      await page.waitForFunction(() => typeof window.probe === 'function');
      for (const [name, reference] of Object.entries(expected)) {
        const result = await page.evaluate(name => window.probe(`fixtures/${name}`), name);
        assert.deepEqual(result.dimensions, reference.dimensions, name);
        assert.deepEqual(result.context, reference.context ?? {
          observed_date: reference.observed_date, latitude: reference.latitude,
          longitude: reference.longitude,
        }, name);
        const scale = 1600 / Math.max(...reference.dimensions);
        assert.deepEqual(result.outputDimensions, reference.dimensions.map(size => Math.round(size * scale)), name);
        assert.equal(result.jpegType, 'image/jpeg');
        assert.ok(result.jpegBytes > 0);
        assert.equal(result.outputHasExif, false, name);
        result.corners.forEach((color, index) => color.forEach((channel, component) => {
          assert.ok(Math.abs(channel - reference.corners[index][component]) <= 8,
            `${name}: orientation corner ${index}: ${color} vs ${reference.corners[index]}`);
        }));
        console.log(JSON.stringify({timezoneId, name, result}));
      }
      const broken = await page.evaluate(async () => {
        try { await window.probe('fixtures/broken.heic'); return {rejected: false}; }
        catch (error) { return {rejected: true, message: error.message}; }
      });
      assert.equal(broken.rejected, true);
      assert.ok(broken.message);
      for (const zip of ['stored', 'deflated']) {
        const unpacked = await page.evaluate(zip => window.probeZip(`fixtures/${zip}.zip`), zip);
        assert.equal(unpacked.name, 'orientation-6.heic');
        assert.equal(unpacked.digest, expected['orientation-6.heic'].sha256);
        assert.deepEqual(unpacked.result.dimensions, expected['orientation-6.heic'].dimensions);
        assert.deepEqual(unpacked.result.context, {
          observed_date: '2026-10-07', latitude: 35.5, longitude: 139.75,
        });
        assert.equal(unpacked.result.outputHasExif, false);
      }
      for (const zip of ['multiple', 'traversal', 'corrupt']) {
        const rejected = await page.evaluate(async zip => {
          try { await window.probeZip(`fixtures/${zip}.zip`); return false; }
          catch { return true; }
        }, zip);
        assert.equal(rejected, true, zip);
      }
      assert.deepEqual(errors, []);
    } finally { await context.close(); }
  }
  console.log('PASS: HEIC date/GPS, 8 orientations, native corners, missing metadata, broken input, JPEG/EXIF removal, stored/deflated ZIP, SHA-256, ZIP rejection, two timezones');
} finally { await browser.close(); }
