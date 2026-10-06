FROM golang:1.25-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -trimpath -o /out/app-server ./cmd/server
FROM gcr.io/distroless/static-debian12
WORKDIR /app
COPY --from=build /out/app-server ./app-server
COPY --chown=nonroot:nonroot frontend ./frontend
COPY --chown=nonroot:nonroot data ./data
USER nonroot:nonroot
EXPOSE 8080
ENV PORT=8080
ENTRYPOINT ["/app/app-server"]
