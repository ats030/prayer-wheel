# 生きものノート (ikimono-note) Design Guide

## Direction

生きものノート (internally ikimono-note) is a phone-first field tool for all ages. It keeps the stack's
compact layout discipline but reads as daylight fieldwork rather than a console:
a light canvas, one green accent, and the photograph and identification
candidates as the visual focus. It must feel careful rather than authoritative:
model output is always presented as a candidate that the user should compare
with the subject.

## Audience

- No age restriction. Copy targets a reader around upper primary school:
  everyday words instead of jargon ("似ている生きもの" not "識別候補",
  "決め手が足りない理由" not "確証がない理由"), no furigana, no baby talk.
- One word per concept, across every screen. The capture and history screens say
  調べる (not 識別/判定), 記録 (not 履歴), 誤差 (not 精度), 図鑑データ (not
  図鑑データベース), and Ollama — the actual name of the thing, not ローカルLLM or
  ローカルAI. A vague label hides where the photo goes; "Ollama" says it, and the
  status line and the settings radio then agree with each other and with reality.
  Photo EXIF is 写真の情報, never 記録, because 記録 already means the
  on-device history. Settings and the legal pages may keep 識別 for precision,
  but when they quote a control they quote its actual label.
- The same vocabulary binds server error messages. A `detail=` string that says
  画像 or 計算資源 while the screen says 写真 and 使うAI makes one thing look like
  two. Tests assert the banned words never appear in `detail=` / `VisionError()`.
- Split the audience in failures. The user gets what to do next ("少し待ってから
  もう一度お試しください"); the operator gets the cause, in the journal — env var
  names, token counts, `finishReason`. Putting the operator's half on screen
  hands a public visitor a variable they cannot set; putting the user's half
  only on screen leaves the operator guessing. Both halves, separate channels.
- Terms and privacy state the all-ages position explicitly and place the
  API-key contract and the cost with the account holder, not the child.
- Nothing about the safety position softens for the younger reader; it gets
  louder. Plain-language warnings replace clinical ones.

## Visual system

- Near-white canvas with a faint green cast, white panels, hairline borders,
  and one green accent. `prefers-color-scheme: dark` swaps the same token names
  to a dark-green-tinted set; no page defines a color only inside the dark
  block, and `color-scheme: light dark` is declared on every page.
- The reader can override the device setting. `theme.js` runs synchronously in
  `<head>` — before any style — and stamps `data-theme="light"|"dark"` on the
  root from `localStorage`, so a chosen theme never flashes the other one. Dark
  tokens are therefore declared twice per page: inside
  `@media(prefers-color-scheme:dark){:root:not([data-theme="light"])}` and again
  in `:root[data-theme="dark"]`, so an explicit choice wins in both directions.
  The toggle cycles 自動 → ライト → ダーク; 自動 clears the stored key and hands
  control back to the device. It also swaps the `theme-color` meta, because the
  media-based ones follow the OS and would otherwise contradict the choice.
- The toggle sits with the other header actions on every page and keeps its
  44px target. Below 390px only its icon remains — the label is the first thing
  to fold, never the button.
- Filled controls use `--on-accent` so the accent keeps contrast in both themes.
- System sans typography, 4px spacing grid, 8px controls, and 12px cards.
- No decorative gradients, oversized headings, or unrelated imagery. The one
  ornament is the ⚠ mark on the safety card.
- Confidence is expressed with plain text and a restrained meter, never a green
  "correct" state — the accent is the app's own color, not a verdict.

## Interaction

識別候補は schema-first で観察点・類似種との識別点・矛盾を分離する。学名の完全一致だけを表示の必須条件とし、写真上の証拠が不足する候補は「確証なし」と不足理由を表示する。自己申告スコアは証拠ありで60%、証拠不足で30%、矛盾ありで20%を上限とする。画面上の観察点はAI抽出で未検証と明示する。

- The main screen uses a Workbench flow: capture, preview, then full-width results. Camera and library inputs are the primary actions and have 44px touch targets.
- Optional capture context and advanced identification controls stay in closed disclosures until requested. After an image is selected, the capture target compresses so the preview and identify action become the visual priority.
- Safety guidance is one flat warning region rather than nested cards.
- Each candidate owns its advert, inside its own block, labelled with that candidate's name, on both the result screen and inside a history record's detail. Reading a record back is the same act as reading the result, so attribution cannot be decided one way on one screen and another way on the other. The history detail keeps its own rule about *when* — nothing is requested until the record is opened — because a list of fifty records must not fetch anything. This is the third arrangement and the reasoning is worth keeping. First a single shelf rotated between candidates, so the products drifted onto the second or third guess with nothing on screen saying so. Then the shelf was pinned to the first candidate but still sat after every candidate, which made the link an ordering convention the reader had to know. Putting the shelf inside the candidate settles attribution by position, and the name in the label settles it again in words.
- The cost of that is real: adverts now appear beside candidates the app itself marks 決め手なし at 30%. The label naming the candidate is what keeps this honest — the reader is told exactly which guess the products are attached to, next to the badge saying that guess is unproven. Nothing about the shelf implies the candidate is confirmed, and the shelf stays below the evidence and the identification links, never above them.
- A shelf carries both the picture cards and the link into Amazon's own search results. The API returns at most four items for one phrasing of one query; a different phrasing returns different things, so cards alone present a dead end as if it were the whole shelf. The 広告 disclosure appears exactly once per shelf — the label carries it when cards are present, the link carries it when it stands alone — because repeating it twice in four lines reads as noise and stops being read.
- Product queries and the food-word exclusion live in `products.js`, shared by both screens. They were written for the history screen only, so the capture screen — the one that carries the safety card saying 食べられるかは判定しません — was the screen searching bare species names and getting たんぽぽ茶 back. A rule that exists on one screen and not the other is the same as not having it.
- Per-identification the shelves share one request budget (six calls, at most two per shelf) and fill in order. Without a per-shelf share the first candidate spent every query angle and the third never loaded; without a total cap, three candidates times five angles would be fifteen calls per identification. Collected products are remembered across shelves so the generic 分類+図鑑 that matches anything does not fill all three.
- The safety region opens with a lead sentence addressed to the whole audience, then splits into three equal questions the app refuses to answer or cannot answer alone: 食べられるか, さわってよいか, 持ち帰ってよいか. Touch safety is stated because rash-causing plants and stinging animals are not separable from a photograph.
- The chosen image is previewed before identification.
- Identification runs behind a job and the browser holds only a ticket. A request that lives exactly as long as the tab means a refresh, a stray back gesture, or a phone locking the screen throws away a minute of Ollama's work with nothing to show for it. The ticket sits in localStorage; reopening the screen resumes polling and the answer lands as if nothing happened.
- The job store holds results, never photographs. Image bytes exist inside the running job and are dropped when it returns, so the time a photo spends on the server is what it always was — the length of one identification. Results wait at most ten minutes for collection and never touch disk; a restart loses them, and the screen then says to try again. The privacy page states this, because a result waiting on the server is a fact a reader is entitled to before they upload.
- Waiting is shown where the answer will appear, not only in the status line under the capture controls — after a refresh nobody scrolls down to find out whether anything is happening. It counts seconds, because a still spinner and a hung process look identical for the sixty seconds Ollama takes, and it says the screen can be closed.
- Whatever the browser needs to write the record — the shrunk photographs, the typed context, the rounded coordinate — is put with the ticket before the request goes out. After a refresh the chosen files and the form fields are gone, so a record built from what is on screen at that moment would lose exactly the photographs the previous change went to trouble to keep.
- Identification disables duplicate submission.
- Empty, loading, result, and error states do not shift the main capture controls.
- Strict mode automatically checks VLM scientific names against iNaturalist and hides non-exact matches.
- VLM candidates label photo observations as unverified AI extraction, cap the displayed score, and separate observations from discriminating features.
- Specialist plant candidates retain their Pl@ntNet source, and exact VLM agreement is labeled as two independent paths.
- If every candidate is rejected, the result asks for additional identifying photos instead of filling the gap with a guess.
- Whatever the result still leaves unsettled — もっと確かめたいこと, 決め手が足りない理由, or no candidate at all — is followed in the same block by the two ways to answer it: カメラで撮って足す and 写真を選んで足す. Advice about what to photograph is only advice until the camera is one press away, and the reader is standing in front of the subject while they read it. The block is shown whenever anything is left to check, not only when a candidate lacks decisive evidence.
- Added photos join the current selection instead of replacing it, up to the same three. The first frame is usually the whole organism; replacing it with the close-up the guide asked for would restart identification from less than it had. Identification is still one explicit press of 名前を調べる — adding a photo scrolls there and says so rather than spending a request on its own.
- Affiliate product-search templates expand the verified candidate name plus identification category into {query}. When configured, Amazon Creators API may replace that fallback with up to four returned product cards containing an image, title, and detail-page URL; each link is labeled as advertising and never influences generation or ranking.
- When affiliate advertising is enabled, it remains visible; only aggregate impressions and clicks are stored.
- Images are processed in memory, EXIF metadata is stripped, and nothing is saved.
- Before stripping EXIF, the local server may propose its capture date and GPS rounded to four decimals. The disclosure opens so users can review or edit these values before they are sent as identification context.
- Identification history is owned by the browser: at most 50 records, result fields, reviewed context, rounded coordinates, and a 1600px-max JPEG of every photo sent are stored in IndexedDB. There is no history API or server-side history file.
- Every photo that went into an identification is kept, not just the first. Keeping one made the close-up a reader deliberately added disappear the moment the answer came back, and made 調べ直す re-run on less than the original question. Stored photos match `vision.MAX_EDGE`, the size the server reduces to before sending anything to a model: smaller would handicap 調べ直す, which re-sends what was kept, and larger would be thrown away on the way out. The list keeps showing one thumbnail because the row has room for one; the rest appear in the detail, where clicking enlarges them like the list thumbnail does.
- Records follow the account, not the browser. Both screens write to Google Drive, and each mode writes its own file: `ikimono-note-operator.json` for the operator screen, `ikimono-note.json` for the public one. The operator screen used to be barred from writing at all, on the grounds that trial shots would become indistinguishable from visitors' records — but what mixed them was sharing one file, not writing as such, and the bar left the operator's own records stranded in whichever browser made them. Separate files keep both properties.
- A linked browser pulls once when a screen opens, before anything can be written. Writes are last-writer-wins and merging only happens on read, so leaving the pull to a button in settings means a second device that identifies one thing first replaces the whole file with its single record. Pulling on open makes every later automatic save write the union. It is one pull per tab — fifty records with thumbnails run to a few megabytes, so moving between screens must not re-fetch them.
- The pull is silent. A visitor who did not press anything gets no red text when the file is not there yet, which is the ordinary state of a browser that has never saved; the operator gets it in the console. A pulled record list redraws itself, because the list was already on screen when the records arrived.
- A record can be examined again from inside its own detail, with photos added. The result screen already lets a reader answer もっと確かめたいこと while standing in front of the subject; a record read later deserves the same answer, because dissatisfaction with a result usually arrives after leaving the field and looking at it properly. Only the first photo survives as a 960px thumbnail, so at most two may be added — the server takes three. The stored photo goes first: it is usually the whole organism, and what gets added is the close-up.
- Examining again never overwrites. The earlier record stays and the new one is added beside it, so the two can be compared; that is the same rule the existing もう一度調べる button follows.
- Deleting always asks first, and says what goes. Clearing everything and closing the account already asked; the per-row 削除 did not, and it sat next to もう一度調べる in a two-button column on a phone. What a single press destroys grew when records started keeping every photo, so the question names the record, says the photos go with it, and says it cannot be undone. The one deletion that does not ask is the automatic trim past fifty records — nobody pressed it.
- When the browser is linked to Drive the question adds that the record goes from there too, and only then. Deleting schedules the same automatic save as adding, which writes the shorter list over the file; a reader who thinks they are tidying one device would otherwise find out afterwards. A browser that never connected is not told about a service it does not use.
- The row shows the small thumbnail and the click opens the full photograph. They are different files for a reason — fifty rows decoding 1600px images to fill an 80px box is waste, and an 80px source blown up to fill the screen is the thing a reader actually complains about. Pointing both at the same image gets one of the two wrong; this got shipped once, pointing the lightbox at the 320px copy.
- The Drive JSON carries a 320px thumbnail per record and a reference; the full 1600px photographs are separate Drive files, one per photo. Packing full photographs into one document made a file that every tab downloaded whole on open and every new record re-uploaded whole — fifty records of three at 1600px is over 60MB. Split, the document is 1.3MB with a picture on every record, uploads cover only what changed, and a device downloads a record's photographs when someone opens that record. The first estimate of what photos cost was measured on 500px sample images that were never downscaled and was four times too small; the split is what makes the true size a non-issue rather than a budget to ration.
- Uploads are throttled to a handful per save. Adding one record must not push fifty records' backlog through the network at once; the remainder goes with the next save, and a record already uploaded is never uploaded again because its file ids are kept with it.
- Photo files carry the record id in their name so they can be swept without the reference list. When records go, their files go with them on the next save; `drive.file` means the sweep can only ever see files this app created.
- A restore must never erase a photograph. Records restore by id and overwrite, and the incoming document deliberately carries no full photographs, so restoring keeps whatever the browser already holds and only fills in what is missing.
- Each row in the list says how sure the record was, in the same words the detail uses. A row that prints the candidate's name in bold and nothing else turns a 30% 決め手なし guess into a species the reader believes they identified. The result screen never does this; the list was the one place that did, and it is the place read weeks later, when the memory of how unsure it was has gone.
- A record that produced no candidate says so. Falling back to the category made 「菌類」 read as the name of the thing found; the category moves to the marks beside the title, where it is a fact about the search rather than an answer.
- 種の保存法 designation appears in the row, not only inside the record. It is the one legally consequential fact the app knows, and requiring a click to reach it put it further away than the advertising.
- Nothing the app needs at runtime may depend on a writable disk or on CPU continuing after a response, because the public deployment will not have either. Affiliate configuration falls back to environment variables when the settings file is absent, user records already have a Firestore path beside the SQLite one, and identification can be told to answer synchronously. Each of these is a property of the app's shape rather than of any one host, which is what makes the choice of host cheap and reversible.
- The environment fills gaps; it does not overrule the file. An operator who saves a setting and watches an environment variable put it back would rightly conclude that saving is broken.
- The browser does not need to be told which mode the server is in. A response carrying a ticket is polled; a response carrying the answer is the answer. One less thing to configure in two places and get wrong in one.
- The capture screen writes history; `/history` is the only screen that reads it. The capture screen keeps no second, hidden copy of the list — a panel nobody can open is a place for failures to go unseen, so a failed write surfaces in the same status line the identification uses.
- Location history never loads a third-party map automatically, on any screen. `/history` shows the privacy note and a button; only the press loads Leaflet and requests OpenStreetMap tiles, with visible attribution and an explicit warning that the rounded coordinate leaves the browser. With no located record the button is disabled and says so.
- Leaflet is vendored under `static/vendor/` rather than pulled from a CDN, so opening the history page cannot hand a visitor's address to a third party the privacy policy never named. Its BSD-2-Clause license text ships alongside it.
- No page carries an inline `<style>`, an inline `<script>`, a `style` attribute, or an `on*` handler. Every page's CSS and JS lives in `/assets/<page>.css` and `/assets/<page>.js`, which is what lets the CSP drop `'unsafe-inline'` — the app hands visitors' API keys to the browser, so a stray injection must not be able to run. Values computed at runtime (the confidence meter's width) go through the CSSOM, never a `style` attribute string. Adding an inline block anywhere silently breaks that page under CSP; tests assert the absence.
- Geolocation is requested only after an explicit button press, kept in browser memory for the current page, reduced to an accuracy label in the result, and never added to identification requests or storage.
- The app never grants collection or edibility. It lists unresolved owner, protected-area, ordinance, and protected-species checks and links to authoritative Japanese guidance.
- The coordinate is never turned into a regulation verdict, not even a hedged "規制区域の可能性". Two of the four checks the card lists have no national machine-readable source at all — landowner and municipal ordinance — so the set can never be closed, and the park layer that does permit commercial use is a 2015 vintage digitised from 1:50,000 planning maps whose own publisher says to phone the regional office for the real boundary. Showing the two that can be drawn would make the unanswered two invisible: a card with no warning on it reads as "nothing to worry about", which is the one sentence this app must never say. The survey of every candidate source is recorded in `docs/tool-license-collection-regulation-data.yaml` so the question is not reopened from memory.
- The one check that does not need the coordinate is the species itself. 環境省's 種の保存法 list (458 国内希少野生動植物種 plus 3 緊急指定種) ships in the repo and is matched against the scientific name the app already verified against iNaturalist — no request leaves the device for it, and the name is not sent anywhere new. The result screen and the history screen both carry it, because the day someone decides to take the thing home is not always the day they photographed it.
- The designation is stated as a fact and linked to 環境省; the app does not summarise what the law forbids. 特定第二種 restricts only collection for sale or distribution, so a single sentence covering all 461 entries would be wrong for 40 of them. The subtype is displayed for the same reason. The safety card's 「持ち帰ってよいか：確認が必要」 is unchanged — one national list is not the whole question.
- A candidate with no designation shows nothing at all. Silence is not "not protected": the match is exact by scientific name, so a taxon designated at subspecies level does not match its species, and prefectural ordinances designate their own species entirely outside this list. Rendering an "指定なし" state would turn three different situations into one reassuring label.
- Optional specialist services remain hidden until configured and require an explicit per-request photo-sharing choice.
- Settings are reachable from the header and use a dedicated page with a clear
  return path. API keys are write-only in the UI; configured state and allowed model choices remain visible.
- The operator's own key may not be lent to strangers while the app is for all ages. Gemini's terms bar use "as part of a website, application, or other service … directed towards or likely to be accessed by individuals under the age of 18", and this app says in three places that it has no age limit. Under BYOK the person who accepted those terms is the adult who brought the key; the moment the server supplies the key, the operator is the one using the API inside a children's app. A paid tier does not fix it — that changes only how submitted content is used, not who may use it. The trial exists in the code and is switched off.
- A stranger can be given a few identifications on the operator's key, or none, and nothing in between is silently possible. BYOK means a visitor who has not brought a key cannot use the app at all; removing the login would only move the wall one screen later. The trial is off by default because it spends the operator's quota on people they have never met, and it refuses to switch on when no operator key exists — a count without a key would look enabled and do nothing.
- When the trial is on, the capture screen and identification leave the login wall; the records and settings screens do not. What a visitor needs in order to decide whether the app is worth an account is the thing itself, not their history.
- Public mode keeps each visitor's provider and model choice in localStorage,
  but API keys only in sessionStorage. Keys are submitted with an identification
  request and are never written to server settings or browser history.
- Public mode makes operator settings read-only, rejects arbitrary Ollama URLs,
  and disables operator-funded local inference unless explicitly enabled.
- External-provider copy states where photographs are sent; Gemini also distinguishes unpaid data-improvement handling from paid-service handling.
- Gemini identification performs a bounded observe, compare-lookalikes, reject-contradictions pass before schema-constrained output; high thinking is preferred for accuracy, while the independent taxonomy gate still treats the photo match as unverified.
- Animal candidates include a sex estimate only when at least one directly visible, species-specific sexual-dimorphism feature is supplied. Otherwise the UI says undetermined; plants are out of scope. The estimate remains explicitly model-derived and requires comparison with a taxon-appropriate external reference.
- Animal reference links are routed by iNaturalist's verified iconic taxon: ADW for mammals, Cornell for birds, FishBase for fishes, AmphibiaWeb for amphibians, Reptile Database for reptiles, and GBIF otherwise. These sites are linked for human review only; their content is not scraped or treated as automatic proof.

## Responsive behavior

- One column below 760px; capture and preview share the Workbench columns above it, with results spanning both columns.
- Content never requires horizontal scrolling.
- Focus indicators remain visible and motion respects reduced-motion settings.
