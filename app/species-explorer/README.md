# Species Explorer

植物・動物の写真をローカルVLMで観察し、識別候補を最大3件表示する実証版です。
画像はメモリ上で縮小・再エンコードしてEXIFを除去し、保存しません。

```bash
cd /home/ats030
uv run uvicorn --app-dir /home/ats030/app/species-explorer main:app --host 0.0.0.0 --port 8523
```

既定モデルは `gemma4:12b` です。`SPECIES_MODEL` と `OLLAMA_URL` で変更できます。

```bash
uv run --with pytest pytest -q
```

識別結果は観察の補助であり、食用・毒性・安全性の判断には使用できません。
