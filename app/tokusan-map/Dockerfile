FROM golang:1.25 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/app-server ./cmd/server

FROM gcr.io/distroless/static:nonroot
WORKDIR /app
COPY --from=build /out/app-server /app/app-server
COPY frontend/ /app/frontend/
COPY data/summaries.json /app/data/summaries.json
ENV PORT=8080
EXPOSE 8080
ENTRYPOINT ["/app/app-server"]
