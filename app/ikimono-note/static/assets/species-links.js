/* 候補名の扱いと外部リンクの組み立て。撮影画面と記録画面の両方が読む。
 *
 * 言語の出し分けや旧値の互換をそれぞれの画面に置くと、片方だけ直して
 * ずれる。ルールはここ1か所にまとめる。
 */

/* 端末内の記録には旧値 "和名未登録" が残るため、両方を同義に扱う */
function noJapaneseName(name) {
  return name === "日本語名なし" || name === "和名未登録";
}

/* 画面に出す和名。古い記録に残る旧値も、いまの表記で見せる */
function commonNameLabel(candidate) {
  if (candidate?.taxonomy_source === "gbif" && noJapaneseName(candidate?.common_name_ja))
    return String(candidate.scientific_name || "候補") + "（和名未確認）";
  if (noJapaneseName(candidate?.common_name_ja)) return "日本語名なし";
  return String(candidate?.common_name_ja || "").trim() || "候補";
}

/* 表示や検索に使う名前。和名がなければ学名へ落とす */
function displayName(candidate) {
  const japanese = noJapaneseName(candidate?.common_name_ja)
    ? ""
    : String(candidate?.common_name_ja || "").trim();
  return japanese || String(candidate?.scientific_name || "").trim();
}

/* 和名があれば日本語版、無ければ学名で英語版へ。生物の学名記事は英語版のほうが揃っている。
   記事の有無は問い合わせず検索URLにする。記事があればそこへ直行し、無ければ検索結果が出る */
function wikipediaUrl(candidate) {
  const japanese = noJapaneseName(candidate?.common_name_ja)
    ? ""
    : String(candidate?.common_name_ja || "").trim();
  const term = japanese || String(candidate?.scientific_name || "").trim();
  if (!term) return "";
  return "https://" + (japanese ? "ja" : "en") + ".wikipedia.org/w/index.php?search=" + encodeURIComponent(term);
}

/* 図鑑を検索 (一般の検索エンジン) */
function sourceUrl(name) {
  return "https://www.google.com/search?q=" + encodeURIComponent(name + " 生物 図鑑");
}

/* 代替照合の出典とライセンスは、保存した記録からも確認できるようにする。 */
function taxonomySourceHtml(candidate) {
  if (!candidate?.taxonomy_url) return "";
  const escape = value => String(value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[ch]);
  const gbif = candidate.taxonomy_source === "gbif";
  return '<a target="_blank" rel="noopener noreferrer" href="'+escape(candidate.taxonomy_url)+'">'
    +(gbif ? 'Catalogue of Life（GBIF）' : 'iNaturalist')+' ↗</a>'
    +(gbif ? '<span class="muted">分類情報：Bánkiほか / Catalogue of Life Foundation / GBIF（抜粋・整形）。'
      +'<a target="_blank" rel="noopener noreferrer" href="https://www.gbif.org/dataset/7ddf754f-d193-4cc9-b351-99906754a03b">データ出典</a> · '
      +'<a target="_blank" rel="noopener noreferrer" href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></span>' : '');
}

/* 分類群ごとの参考資料。iNaturalist が返した iconic taxon で振り分ける。
   これらは人が読んで確かめるための外部サイトで、内容を取り込むことはしない */
function animalReference(candidate, category) {
  if (category !== "動物") return null;
  const scientific = String(candidate?.scientific_name || "").trim();
  if (!scientific) return null;
  const q = encodeURIComponent(scientific);
  const parts = scientific.split(/\s+/);
  const group = candidate?.animal_group;
  if (group === "Mammalia") return {label: "Animal Diversity Web", url: "https://animaldiversity.org/search/?q=" + q};
  if (group === "Aves") return {label: "Cornell All About Birds", url: "https://www.allaboutbirds.org/guide/search?q=" + q};
  if (group === "Actinopterygii" || group === "Chondrichthyes")
    return {label: "FishBase", url: "https://www.fishbase.se/summary/" + encodeURIComponent(scientific.replaceAll(" ", "-")) + ".html"};
  if (group === "Amphibia" && parts.length > 1)
    return {label: "AmphibiaWeb", url: "https://amphibiaweb.org/cgi/amphib_query?where-genus=" + encodeURIComponent(parts[0]) + "&where-species=" + encodeURIComponent(parts[1])};
  if (group === "Reptilia" && parts.length > 1)
    return {label: "Reptile Database", url: "https://reptile-database.reptarium.cz/advanced_search?genus=" + encodeURIComponent(parts[0]) + "&species=" + encodeURIComponent(parts[1]) + "&submit=Search"};
  return {label: "GBIF", url: "https://www.gbif.org/species/search?q=" + q};
}

/* 提供元の呼び名。設定画面は正式名 (OpenAI API) を出すが、記録とステータス表示は
   短い形で揃える。記録に "local" のような内部IDが出ないようにするのが目的 */
const PROVIDER_LABELS = {local: "Ollama", openai: "OpenAI", anthropic: "Anthropic", gemini: "Gemini"};
function providerLabel(value) {
  return PROVIDER_LABELS[value] || String(value || "");
}

/* APIキーの置き場。既定は「この端末に残す」(localStorage) で、タブを閉じても消えない。
   共用端末では残したくないので、その場かぎり (sessionStorage) に切り替えられる。
   どちらに置いても、キーはサーバーへ保存されず、判定のときだけ送られる。 */
const KEEP_KEYS_FLAG = "species-keep-keys";

function keepingKeys() {
  try { return localStorage.getItem(KEEP_KEYS_FLAG) !== "0"; } catch (error) { return false; }
}

function setKeepingKeys(keep) {
  try {
    localStorage.setItem(KEEP_KEYS_FLAG, keep ? "1" : "0");
    if (!keep) {
      /* 残さない設定にしたら、すでに端末へ書いたぶんはその場かぎりへ移す */
      for (const name of ["openai", "anthropic", "gemini", "plantnet"]) {
        const stored = localStorage.getItem("species-key-" + name);
        if (stored) { sessionStorage.setItem("species-key-" + name, stored); localStorage.removeItem("species-key-" + name); }
      }
    }
  } catch (error) { /* 保存できない環境ではその場かぎりのまま */ }
}

function readApiKey(name) {
  try { return localStorage.getItem("species-key-" + name) || sessionStorage.getItem("species-key-" + name) || ""; }
  catch (error) { return ""; }
}

function writeApiKey(name, value) {
  try {
    const store = keepingKeys() ? localStorage : sessionStorage;
    store.setItem("species-key-" + name, value);
    (keepingKeys() ? sessionStorage : localStorage).removeItem("species-key-" + name);
  } catch (error) { /* 保存できなくても、その回の判定には使える */ }
}

function clearApiKey(name) {
  try { localStorage.removeItem("species-key-" + name); sessionStorage.removeItem("species-key-" + name); }
  catch (error) { /* 何もしない */ }
}
