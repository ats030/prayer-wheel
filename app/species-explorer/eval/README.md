# 識別精度の評価

アプリの表示は「あてはまり度 60%」「決め手なし」など確信度を細かく出すが、その数字が
実態と合っているかは測らないと分からない。安全カードに「まちがえることがあります」と
書く以上、どのくらい間違えるのかは運営者が把握しておく。

## 検証はローカルLLMで行う

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
