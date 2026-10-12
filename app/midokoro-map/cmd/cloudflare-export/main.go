// cloudflare-export produces public API snapshots using the existing domain handlers.
// It never fetches Wikipedia or invokes the local model.
package main

import (
	"crypto/sha256"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"midokoro-map/internal/omatsuri"
	omatsuriServices "midokoro-map/internal/omatsuri/services"
	"midokoro-map/internal/onsen"
	onsenServices "midokoro-map/internal/onsen/services"
	"midokoro-map/internal/shiseki"
	"midokoro-map/internal/tokusan"
	tokusanServices "midokoro-map/internal/tokusan/services"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

func main() {
	data := flag.String("data", "data", "public data directory")
	out := flag.String("out", "cloudflare/assets/_data", "output directory")
	flag.Parse()
	for _, kind := range []string{"omatsuri", "onsen", "shiseki", "tokusan"} {
		os.Setenv(kindEnv(kind)+"_SUMMARY_DISABLE", "1")
	}
	os.Setenv("MIDOKORO_DATA_DIR", *data)
	os.Unsetenv("MIDOKORO_PUBLIC_ORIGIN") // snapshots contain ordinary links only
	builders := map[string]func(string) (http.Handler, error){"omatsuri": omatsuri.NewHandler, "onsen": onsen.NewHandler, "shiseki": shiseki.NewHandler, "tokusan": tokusan.NewHandler}
	names := map[string]string{"omatsuri": "festivals", "onsen": "onsen", "shiseki": "shiseki", "tokusan": "tokusan"}
	for _, kind := range []string{"omatsuri", "onsen", "shiseki", "tokusan"} {
		h, err := builders[kind](*data)
		if err != nil {
			log.Fatal(err)
		}
		body := get(h, "/api/"+names[kind]+"/")
		write(*out, kind+"/list.json", body)
		cacheBody, err := os.ReadFile(filepath.Join(*data, kind, "summaries.json"))
		if err != nil {
			log.Fatal(err)
		}
		var cache map[string]string
		if err := json.Unmarshal(cacheBody, &cache); err != nil {
			log.Fatal(err)
		}
		normalizers := map[string]func(string) string{"onsen": onsenServices.NormalizeStoredSection, "omatsuri": omatsuriServices.NormalizeStoredSection, "tokusan": tokusanServices.NormalizeStoredSection}
		if normalize := normalizers[kind]; normalize != nil {
			for key, value := range cache {
				// Heading maps are a different cache contract and must remain unchanged.
				if value == "なし" || !strings.HasPrefix(strings.TrimSpace(value), "{") || strings.Contains(value, `"summary"`) {
					cache[key] = normalize(value)
				}
			}
		}
		cacheBody, err = json.Marshal(cache)
		if err != nil {
			log.Fatal(err)
		}
		write(*out, kind+"/normalized-cache.json", cacheBody)
		var rows []map[string]any
		if err := json.Unmarshal(body, &rows); err != nil || len(rows) == 0 {
			log.Fatalf("%s: empty or invalid list", kind)
		}
		// QID and site-ID indices use small shards to keep Worker CPU bounded.
		shards := map[byte]map[string]any{}
		prefectures := map[string]bool{}
		for _, row := range rows {
			if prefecture, ok := row["prefecture"].(string); ok && prefecture != "" {
				prefectures[prefecture] = true
			}
			for _, field := range []string{"qid", "id"} {
				if id, ok := row[field].(string); ok && id != "" {
					shard := bucket(id)
					if shards[shard] == nil {
						shards[shard] = map[string]any{}
					}
					if _, exists := shards[shard][id]; !exists {
						shards[shard][id] = row
					}
				}
			}
			if kind == "tokusan" && row["description"] != nil && row["description"] != "" {
				id := row["qid"].(string)
				shard := bucket(id)
				// These official-source sections require no network and preserve all fallback rules.
				shards[shard]["sections:"+id] = json.RawMessage(get(h, "/api/sections/"+id))
			}
		}
		for prefecture := range prefectures {
			key := fmt.Sprintf("%x", sha256.Sum256([]byte(prefecture)))
			write(*out, kind+"/prefectures/"+key+".json", get(h, "/api/"+names[kind]+"/prefecture/"+url.PathEscape(prefecture)))
		}
		for i := 0; i < 64; i++ {
			shard := shards[byte(i)]
			if shard == nil {
				shard = map[string]any{}
			}
			b, _ := json.Marshal(shard)
			write(*out, fmt.Sprintf("%s/items/%02x.json", kind, i), b)
		}
		fmt.Printf("%s: %d public records\n", kind, len(rows))
	}
	// Natural-monument summaries (geo tab) have no list API; publish their cache only.
	geoCache := map[string]string{}
	if body, err := os.ReadFile(filepath.Join(*data, "geo", "summaries.json")); err == nil {
		if err := json.Unmarshal(body, &geoCache); err != nil {
			log.Fatal(err)
		}
	} else if !os.IsNotExist(err) {
		log.Fatal(err)
	}
	geoBody, err := json.Marshal(geoCache)
	if err != nil {
		log.Fatal(err)
	}
	write(*out, "geo/normalized-cache.json", geoBody)
	fmt.Printf("geo: %d cached summaries\n", len(geoCache))
}

func kindEnv(s string) string {
	return map[string]string{"omatsuri": "OMATSURI", "onsen": "ONSEN", "shiseki": "SHISEKI", "tokusan": "TOKUSAN"}[s]
}
func bucket(s string) byte {
	var n uint32
	for _, b := range []byte(s) {
		n = n*31 + uint32(b)
	}
	return byte(n % 64)
}
func get(h http.Handler, path string) []byte {
	r := httptest.NewRecorder()
	h.ServeHTTP(r, httptest.NewRequest("GET", path, nil))
	if r.Code != 200 {
		log.Fatalf("export %s: HTTP %d: %s", path, r.Code, r.Body.String())
	}
	return r.Body.Bytes()
}
func write(root, name string, b []byte) {
	p := filepath.Join(root, name)
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		log.Fatal(err)
	}
	if err := os.WriteFile(p, b, 0644); err != nil {
		log.Fatal(err)
	}
}
