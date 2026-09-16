package services

// wikimediaUserAgent identifies this application to the Wikimedia APIs
// (Wikipedia, Wikidata, Wikimedia Commons).
//
// Wikimedia's User-Agent policy requires a descriptive agent string that
// includes contact information. A bare product token such as "shiseki-map/1.0"
// is treated as non-compliant and receives a far smaller anonymous rate-limit
// budget: measured against ja.wikipedia.org on 2026-09-14, sequential requests
// started returning HTTP 429 after 10 requests with the bare token, while the
// same burst succeeded 70/70 with the contact URL below.
//
// The detail panel issues several Wikimedia requests per shiseki (article
// content, section headings, section body, and Commons attribution), so the
// bare token exhausted the budget after a few detail-panel opens and made the
// 歴史 / アクセス sections disappear partway through a browsing session.
const wikimediaUserAgent = "shiseki-map/1.0 (https://github.com/ats030/shiseki-map)"
