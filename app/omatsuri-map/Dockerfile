# Cloud Run用ビルド。外部DB不要(frontend/festivals.jsonを直接読み込み)。
FROM golang:1.25-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -o /out/omatsuri-map-server ./cmd/server

FROM gcr.io/distroless/static-debian12
WORKDIR /app
COPY --from=build /out/omatsuri-map-server ./omatsuri-map-server
COPY frontend ./frontend
COPY data/summaries.json ./data/summaries.json
COPY favicon.svg ./favicon.svg
USER nonroot:nonroot
EXPOSE 8080
ENV PORT=8080
ENTRYPOINT ["/app/omatsuri-map-server"]
