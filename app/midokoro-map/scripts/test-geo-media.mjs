// Run: node --test scripts/test-geo-media.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {photoHtml, sectionsHtml, hasSummary} from '../frontend/assets/geo/media.mjs';

const NO_IMAGE = '<p class="detail-image-status">表示できる画像が登録されていません。</p>';
const NO_LICENSE = '<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';
const LINK = 'target="_blank" rel="noopener noreferrer"';

test('missing or non-http photo shows the no-image status', () => {
  assert.equal(photoHtml(null, '玄武洞'), NO_IMAGE);
  assert.equal(photoHtml({url: ''}, '玄武洞'), NO_IMAGE);
  assert.equal(photoHtml({url: 'javascript:alert(1)', license: 'CC0'}, '玄武洞'), NO_IMAGE);
});

test('photo without a license is not shown', () => {
  assert.equal(photoHtml({url: 'https://upload.wikimedia.org/a.jpg', license: ''}, '玄武洞'), NO_LICENSE);
});

test('licensed photo has creator, linked license and source', () => {
  const html = photoHtml({url: 'https://upload.wikimedia.org/a.jpg', license: 'CC BY-SA 4.0', licenseUrl: 'https://creativecommons.org/licenses/by-sa/4.0/',
    creator: 'Taro <Yamada>', sourceUrl: 'https://commons.wikimedia.org/wiki/File:A.jpg'}, '玄武洞');
  assert.equal(html, '<figure class="detail-photo"><img class="detail-image" src="https://upload.wikimedia.org/a.jpg" alt="玄武洞の写真" loading="lazy">'
    + `<figcaption>Taro &lt;Yamada&gt; · <a href="https://creativecommons.org/licenses/by-sa/4.0/" ${LINK}>CC BY-SA 4.0</a>`
    + ` · <a href="https://commons.wikimedia.org/wiki/File:A.jpg" ${LINK}>出典</a></figcaption></figure>`);
});

test('caption omits missing creator, unlinked license and non-http source', () => {
  const html = photoHtml({url: 'https://upload.wikimedia.org/a.jpg', license: 'CC0', licenseUrl: '', creator: '', sourceUrl: 'ftp://x'}, 'A&B');
  assert.equal(html, '<figure class="detail-photo"><img class="detail-image" src="https://upload.wikimedia.org/a.jpg" alt="A&amp;Bの写真" loading="lazy"><figcaption>CC0</figcaption></figure>');
});

test('sections render summaries in slot order with an AI note', () => {
  const html = sectionsHtml({source_url: 'https://ja.wikipedia.org/wiki/%E7%8E%84%E6%AD%A6%E6%B4%9E',
    access: {summary: 'JR駅から徒歩15分。'}, history: {summary: ' 溶岩が冷えて<柱状節理>ができた。 '}, remains: {raw_omitted: true}, highlights: {summary: ''}});
  assert.equal(html, '<section class="detail-section"><h3>成り立ち</h3><p class="detail-summary">溶岩が冷えて&lt;柱状節理&gt;ができた。</p></section>'
    + '<section class="detail-section"><h3>アクセス</h3><p class="detail-summary">JR駅から徒歩15分。</p></section>'
    + `<p class="detail-source">要約はAIが<a href="https://ja.wikipedia.org/wiki/%E7%8E%84%E6%AD%A6%E6%B4%9E" ${LINK}>Wikipedia</a>の記事（CC BY-SA 4.0）から作成しました。</p>`);
});

test('note without a usable source URL is plain text', () => {
  assert.equal(sectionsHtml({source_url: 'javascript:x', remains: {summary: '柱状節理。'}}),
    '<section class="detail-section"><h3>特徴・見どころ</h3><p class="detail-summary">柱状節理。</p></section>'
    + '<p class="detail-source">要約はAIがWikipediaの記事（CC BY-SA 4.0）から作成しました。</p>');
});

test('no summaries render nothing', () => {
  assert.equal(sectionsHtml(null), '');
  assert.equal(sectionsHtml({history: {raw_omitted: true}, access: {summary: '  '}}), '');
});

test('hasSummary is true only when a slot has text', () => {
  assert.equal(hasSummary(null), false);
  assert.equal(hasSummary({history: {raw_omitted: true}, highlights: {summary: ' '}}), false);
  assert.equal(hasSummary({highlights: {summary: '1931年指定。'}}), true);
});
