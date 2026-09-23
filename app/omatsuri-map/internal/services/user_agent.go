package services

// wikimediaUserAgent identifies this application to the Wikimedia APIs
// (Wikipedia, Wikidata, Wikimedia Commons).
//
// Wikimedia's User-Agent policy requires a descriptive agent string that
// includes contact information. A bare product token such as "omatsuri-map/1.0"
// is treated as non-compliant and receives a far smaller anonymous rate-limit
// budget. The detail panel issues several Wikimedia requests per festival
// (article content, section headings, section body, and Commons attribution),
// so the bare token would exhaust the budget after a few detail-panel opens and
// make sections disappear partway through a browsing session.
const wikimediaUserAgent = "omatsuri-map/1.0 (https://github.com/ats030/omatsuri-map)"
