# Cloud Run用ビルド。modernc.org/sqlite は pure-Go 実装のため CGO 不要。
FROM golang:1.25-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -o /out/app-server ./cmd/server

FROM gcr.io/distroless/static-debian12
WORKDIR /app
COPY --from=build /out/app-server ./app-server
COPY frontend ./frontend
# Cloud Run は LLM を呼ばない(SHISEKI_SUMMARY_DISABLE=1)ので、ローカルで
# cmd/summary-warm が生成した要約を同梱して配信する。
COPY data/summaries.json ./data/summaries.json
USER nonroot:nonroot
EXPOSE 8080
ENV PORT=8080
ENTRYPOINT ["/app/app-server"]
