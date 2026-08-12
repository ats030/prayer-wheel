# 生きものノート 公開版。Cloud Run 向け。
#
# 公開版は Ollama を使わない (IKIMONO_PUBLIC_LOCAL=0) ので、GPU も大きなメモリも
# 要らない。実測でメモリ 98MB、永続データ 24KB。小さい構成で足りる。
FROM python:3.13-slim

# Pillow の JPEG/PNG 処理に必要な共有ライブラリだけ入れる
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo libopenjp2-7 zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存を先に入れる。アプリのコードだけ変えたときに、この層を再利用できる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY static ./static

# 公開版として動かす。運営者用の設定保存は 403 で拒否される
ENV IKIMONO_PUBLIC_MODE=1 \
    IKIMONO_PUBLIC_LOCAL=0 \
    IKIMONO_PUBLIC_AFFILIATE=0 \
    PORT=8080 \
    PYTHONUNBUFFERED=1

# 素性の分からない相手にファイルを触らせない
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8080
# Cloud Run は PORT を渡してくる。固定せず、そこへ合わせる
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT} --timeout-graceful-shutdown 5 --no-access-log
