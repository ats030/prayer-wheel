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
