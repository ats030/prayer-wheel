/* 商品カードの組み立て。撮影画面と記録画面の両方が読む。
 *
 * 以前は productCard が2画面に別々に書かれ、食品の除外と切り口の使い分けは
 * 記録画面にしかなかった。安全カードが「食べられるかは判定しません」と言っている
 * のは撮影画面のほうなので、除外が要るのもそちら側だった。1か所にまとめる。
 */

/* 「食べられるかは判定しません」と言っている隣に食品を並べない。誤同定のとき
   危険な後押しになる。語による除外なので完全ではないが、明らかなものは落とす */
const EDIBLE_WORDS = ["茶", "ティー", "食用", "乾燥", "天日干し", "サプリ", "パウダー", "粉末",
                      "エキス", "おやつ", "フード", "ドリンク", "健康食品", "コーヒー",
                      "はちみつ", "ハーブティー"];

function looksEdible(title) {
  const text = String(title || "");
  return EDIBLE_WORDS.some(word => text.includes(word));
}

function shuffle(items) {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function productCard(product) {
  return '<a class="product-card" href="' + esc(product.url) + '" target="_blank"'
    + ' rel="sponsored noopener noreferrer" aria-label="広告: ' + esc(product.title) + '">'
    + '<img class="product-image" src="' + esc(product.image) + '" alt="" loading="lazy"'
    + ' referrerpolicy="no-referrer">'
    + '<span class="product-title">' + esc(product.title) + '</span></a>';
}

/* 種名を先に試し、汎用の図鑑は最後の逃げ道にする。
   「分類+図鑑」は必ずヒットするので、先に置くとどの候補でも同じ図鑑が並ぶ。
   Books に絞る切り口を混ぜると、その種を扱った本へ寄る。
   種名だけで引くと食品が上位に来る (タンポポ → たんぽぽ茶) ので、用途を添えて
   観察・栽培の周辺へ寄せる。 */
function productQueries(name, scientificName, category) {
  const grow = category === "動物" ? "飼育" : category === "菌類" ? "きのこ 栽培" : "育て方";
  const specific = [];
  if (name) {
    specific.push({ q: name, index: "Books" });
    specific.push({ q: name + " 観察", index: "All" });
    specific.push({ q: name + " " + grow, index: "All" });
  }
  const scientific = String(scientificName || "").trim();
  if (scientific && scientific !== name) specific.push({ q: scientific, index: "Books" });
  const generic = category
    ? [{ q: category + " 図鑑", index: "Books", generic: true },
       { q: category + " 観察 ルーペ", index: "All", generic: true }]
    : [];
  return [...shuffle(specific).slice(0, 3), ...generic];
}

/* 候補ごとに棚を持つので、集めた品は候補をまたいで覚えておく。覚えないと、
   どの候補でも当たる「分類+図鑑」が3つの棚に並んで同じ本だらけになる。
   予算は棚をまたいだ通し。候補3件×切り口5つを全部試すと、識別1回で商品APIを
   15回叩くことになる。
   一棚あたりの上限も要る。通しの予算だけだと、最初の候補が切り口を使い切り、
   3番目の候補が1回も引けないまま検索リンクのままになる (実測でそうなった)。 */
function productBudget(maxRequests = 6, perShelf = 2) {
  return { seen: new Set(), left: maxRequests, perShelf };
}

async function loadProductShelf(shell, subject, budget) {
  if (shell.dataset.loaded) return;
  shell.dataset.loaded = "1";
  const found = { specific: [], generic: [] };
  let used = 0;
  for (const query of productQueries(subject.name, subject.scientific, subject.category)) {
    const enough = found.specific.length + Math.min(found.generic.length, 2) >= 4;
    if (enough || budget.left <= 0 || used >= budget.perShelf) break;
    budget.left--;
    used++;
    try {
      const response = await fetch("/api/amazon/products?q=" + encodeURIComponent(query.q)
        + "&index=" + encodeURIComponent(query.index));
      if (!response.ok) continue;
      const data = await response.json();
      for (const product of (Array.isArray(data.products) ? data.products : [])) {
        /* 同じ品が別URLで返ることがあるので、題名でも重複を見る */
        const key = String(product?.title || "").trim();
        if (!product?.url || budget.seen.has(product.url) || budget.seen.has(key)
            || looksEdible(product.title)) continue;
        budget.seen.add(product.url);
        budget.seen.add(key);
        found[query.generic ? "generic" : "specific"].push(product);
      }
    } catch (error) { /* 次の切り口を試す */ }
  }
  /* 分類群の一般書は枠を埋めるための保険。多くても2件までにして、
     その種に固有の品が押しのけられないようにする */
  const collected = [...shuffle(found.specific), ...shuffle(found.generic).slice(0, 2)].slice(0, 4);
  if (!collected.length) return false;
  shell.innerHTML = '<div class="affiliate-label">広告 · ' + esc(subject.label || "関連商品")
    + '</div><div class="product-grid">' + collected.map(productCard).join("") + '</div>';
  shell.querySelectorAll(".product-card").forEach(link => {
    link.onclick = () => fetch("/api/affiliate/click", { method: "POST", keepalive: true }).catch(() => {});
  });
  return true;
}
