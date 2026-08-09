# Species Explorer

植物・動物の写真を最大3枚と任意の撮影地域・日付・大きさから、ローカルVLMまたは登録したOpenAI・Anthropic APIで観察し、識別候補を最大3件表示する実証版です。 候補名は任意でiNaturalistの分類データと照合できます。 Pl@ntNet APIキーを登録すると、明示的に選択した植物写真だけを植物専用識別と比較できます。
画像はメモリ上で縮小・再エンコードしてEXIFを除去し、保存しません。

```bash
cd /home/ats030
uv run uvicorn --app-dir /home/ats030/app/species-explorer main:app --host 0.0.0.0 --port 8523
```

計算資源、APIキー、使用モデルは画面上部の「設定」から変更できます。ローカルモデルはOllamaにインストール済みで画像入力に対応するものを自動表示します。APIキーは `~/.config/species-explorer/settings.json` に権限 `0600` で保存し、画面には再表示しません。

```bash
uv run --with pytest pytest -q
```

識別結果は観察の補助であり、食用・毒性・安全性の判断には使用できません。
