# 識別精度の評価

アプリの表示は「あてはまり度 60%」「決め手なし」など確信度を細かく出すが、その数字が
実態と合っているかは測らないと分からない。安全カードに「まちがえることがあります」と
書く以上、どのくらい間違えるのかは運営者が把握しておく。

## 検証はOllamaで行う

既定は `--provider local`。外部APIは無料枠に**モデルごとの日次上限**があり、評価を1回
回すだけで公開版の利用者ぶんの枠を削ってしまう。実際、gemini-3.6-flash で30枚を流した
ところ10枚で日次上限に達した (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`)。

外部プロバイダーとの比較が必要なときだけ `--provider gemini` のように明示する。その場合も
中断した続きから再開できる (成功ぶんは結果ファイルから引き継ぐ)。

## データセット

iNaturalist の research-grade 観察から、**CC0 の写真だけ**を集めた30枚。日本 (place_id
6737) に絞り、植物・昆虫・鳥・菌類・は虫類/両生類を6枚ずつ。1種1枚。

ライセンス判断は `~/ai-workflow/tool-license-registry.yaml` に記録済み (conditional)。
条件は CC0 に限ること。`fetch_dataset.py` は `photo_license=cc0` で絞ったうえで、
レスポンスの `license_code` を1枚ずつ再検証し、CC0 以外は保存しない。

画像は再取得できるので `~/cache/species-eval/images` に置き、リポジトリには
`dataset.json` (observation_id と正解ラベル) だけを残す。

```bash
uv run --with httpx python eval/fetch_dataset.py --per-group 6
```

正解ラベルは research-grade 観察の taxon。**これも人間のコミュニティ同定であって絶対では
ない**ので、数%のラベル誤りが混じる前提で読む。

## 測定

```bash
uv run --with httpx --with pillow python eval/run_eval.py --label local-baseline
uv run --with httpx --with pillow python eval/run_eval.py --use-plantnet --label local-plantnet
```

本番と同じ `pipeline.identify_all` を通す。評価だけ別の手順を組むと、測った数字が
アプリの実際の挙動と静かにずれるため。

| 指標 | 意味 |
|---|---|
| top1 / top3 | 第1候補 / 上位3候補に正解の学名が入るか |
| genus | 上位3候補のいずれかが正解と同じ属か |
| family_or_above | 属が外れていても、上位分類が正解の系統と重なるか |
| rejected | 候補を1件も出さなかった割合 |
| mean_confidence_when_answered | 答えたときの平均確信度。top1 と大きく離れていれば校正がずれている |

結果は `results/<label>.json`。要約と1枚ごとの内訳が入る。

## 読み方の注意

- 30枚は傾向を見るには足りるが、数ポイントの差を断定できる量ではない。
- 分類群ごとに難易度が違う。全体の数字だけでなく `rows` の group 別を見る。
- `rejected` が高いのは必ずしも悪くない。誤断定を避けた結果なら設計どおり。
  `top1_percent_when_answered` と併せて見る。

## 測定結果

### Pl@ntNet 併用の効果 (植物20枚・Ollama・同一写真)

| | Top-1 | Top-3 | 属 | 科以上 | 棄却 |
|---|---|---|---|---|---|
| ローカル単独 | 0% | 0% | 0% | 85% | 15% |
| Pl@ntNet 併用 | **45%** | 50% | **65%** | **100%** | 0% |

専門識別は20件すべてで実行された。Top-1 が入れ替わったのは9枚で、**すべて併用側が正解**。
併用にして外した写真は1枚もなかった。

結論: Pl@ntNet 経路は残す (ats030-xzxs)。Ollama単独では植物の種同定がほぼ
成立せず (属レベルでも 0%)、専門識別が精度の大半を担っている。

### 分類群ごと (Ollama単独・30枚)

| 分類群 | Top-1 | 科以上 | 棄却 |
|---|---|---|---|
| 鳥 | 33% | 67% | 33% |
| 菌類 | 17% | 67% | 33% |
| は虫類・両生類 | 17% | 83% | 17% |
| 植物 | 0% | 83% | 17% |
| 昆虫 | 0% | 67% | 33% |

### プロバイダー比較 (同一10枚)

| | Top-1 | 属 | 科以上 | 中央値 |
|---|---|---|---|---|
| ローカル (gemma4:31b) | 10% | 20% | 90% | 61.5s |
| Gemini 3.6 Flash | 30% | 40% | 90% | 18.1s |

Gemini 側は無料枠の日次上限で10枚までしか回せていない。傾向以上の主張はできない。

## Gemini の無料枠はモデルごとに違う

`gemini-3.6-flash` は1日20リクエストしか通らない (2026-08-11 実測、429 の
`GenerateRequestsPerDayPerProjectPerModel-FreeTier` に `quotaValue: 20`)。30枚の
評価が完走できず、公開版の既定にはできない。`gemini-3.5-flash-lite` は30枚を
完走している (Top-1 36.7%)。

同じ10枚で比べたときの精度に差は出ていないため、無料枠の広さで Flash-Lite を
既定にした。枠は予告なく変わるので、既定を変える前にこの数字を測り直すこと。

## thinkingLevel は high のまま

同じ日・同じコードで gemini-3.5-flash-lite を30枚ずつ測った (2026-08-11)。

| thinkingLevel | Top-1 | Top-3 | 属 | 科以上 | 中央値 | 棄権 |
|---|---|---|---|---|---|---|
| high | 40.0% | 40.0% | 53.3% | 96.7% | 10.5秒 | 3.3% |
| medium | 26.7% | 33.3% | 50.0% | 90.0% | 6.8秒 | 10.0% |

medium は3.7秒速いが、Top-1 が13.3ポイント落ち、棄権が3倍に増える。全ての指標で
high が上回っているので high を既定に据え置く。ただし30枚での13.3ポイントは4件差
であり、偶然の幅を完全には否定できない。据え置きの判断としては足りるが、逆の
結論 (medium へ下げる) を出すには枚数が要る。

thinkingLevel を記録していなかったため、これ以前の gemini 結果がどちらの条件
だったか確かめられない。run_eval は config.thinking_level を残すようにした。
