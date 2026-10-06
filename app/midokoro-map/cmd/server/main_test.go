package main

import (
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
 "net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestUnifiedRoutesPreserveSnapshots(t *testing.T) {
	data := t.TempDir()
	fixtures := []struct{ kind, file, table, route string }{
		{"omatsuri", "festivals.db", "festival", "festivals"},
		{"onsen", "onsen.db", "onsen", "onsen"},
		{"shiseki", "shiseki.db", "shiseki", "shiseki"},
		{"tokusan", "tokusan.db", "tokusan", "tokusan"},
	}
	expected := map[string]int{}
	for _, fixture := range fixtures {
		source := filepath.Join("../../data", fixture.kind, fixture.file)
		bytes, err := os.ReadFile(source)
		if err != nil {
			t.Fatal(err)
		}
		target := filepath.Join(data, fixture.kind, fixture.file)
		if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(target, bytes, 0600); err != nil {
			t.Fatal(err)
		}
		db, err := sql.Open("sqlite", source)
		if err != nil {
			t.Fatal(err)
		}
		var count int
		err = db.QueryRow("SELECT COUNT(*) FROM " + fixture.table).Scan(&count)
		db.Close()
		if err != nil {
			t.Fatal(err)
		}
		expected[fixture.kind] = count
	}
	t.Setenv("MIDOKORO_AFFILIATE_ORIGINS", "")
	t.Setenv("TOKUSAN_AMAZON_URL", "")
	handler, err := newHandler(data, "../../frontend", publicConfig{DefaultKind: "onsen", AffiliateOrigins: []string{}})
	if err != nil {
		t.Fatal(err)
	}
	request := func(path string) *httptest.ResponseRecorder {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path, nil))
		return response
	}
	for _, fixture := range fixtures {
		response := request("/api/" + fixture.kind + "/" + fixture.route + "/")
		if response.Code != 200 {
			t.Fatalf("%s: %d", fixture.kind, response.Code)
		}
		var rows []map[string]any
		if err := json.Unmarshal(response.Body.Bytes(), &rows); err != nil {
			t.Fatal(err)
		}
		if len(rows) != expected[fixture.kind] || len(rows) == 0 {
			t.Fatalf("%s: got %d, want %d", fixture.kind, len(rows), expected[fixture.kind])
		}
  prefecture,_:=rows[0]["prefecture"].(string)
  if prefecture!="" {
   escaped:=strings.ToLower(url.PathEscape(prefecture))
   filtered:=request("/api/"+fixture.kind+"/"+fixture.route+"/prefecture/"+escaped)
   if filtered.Code!=200 {t.Fatalf("%s encoded prefecture route: %d",fixture.kind,filtered.Code)}
   var subset []map[string]any
   if err:=json.Unmarshal(filtered.Body.Bytes(),&subset);err!=nil {t.Fatal(err)}
   if len(subset)==0 {t.Fatalf("%s prefecture data lost",fixture.kind)}
   for _,row:=range subset {if row["prefecture"]!=prefecture {t.Fatalf("%s filter mismatch",fixture.kind)}}
  }
		if fixture.kind == "tokusan" {
			for _, row := range rows {
				if row["affiliate_url"] != "" && row["affiliate_url"] != nil {
					t.Fatal("unregistered origin contains advertising URL")
				}
			}
		}
	}
	for _, path := range []string{"/api/onsen/shiseki/", "/data/shiseki/shiseki.db", "/assets/tokusan/tokusan.db", "/missing.js"} {
		if response := request(path); response.Code != 404 {
			t.Fatalf("%s: got %d", path, response.Code)
		}
	}
	for _, path := range []string{"/", "/health", "/changelog", "/vendor/leaflet.js", "/assets/onsen/view.html"} {
		if response := request(path); response.Code != 200 {
			t.Fatalf("%s: got %d", path, response.Code)
		}
	}
	config := request("/api/config")
	if config.Header().Get("Cache-Control") != "no-store" || !strings.Contains(config.Body.String(), `"defaultKind":"onsen"`) {
		t.Fatal(config.Body.String())
	}
	t.Setenv("MIDOKORO_PUBLIC_ORIGIN", "https://maps.example")
	t.Setenv("MIDOKORO_AFFILIATE_ORIGINS", "https://maps.example")
	t.Setenv("JALAN_A8MAT", "test-tracking")
	t.Setenv("TOKUSAN_AMAZON_URL", "https://www.amazon.co.jp/s?k={query}&tag=test-22")
	advertised, err := newHandler(data, "../../frontend", publicConfig{DefaultKind: "shiseki", AffiliateOrigins: []string{"https://maps.example"}})
	if err != nil {
		t.Fatal(err)
	}
	for _, origin := range []string{"https://maps.example", "http://localhost:8533", "https://unregistered.example"} {
		allowed := origin == "https://maps.example"
		for _, kind := range []string{"onsen", "omatsuri", "shiseki"} {
			response := httptest.NewRecorder()
			advertised.ServeHTTP(response, httptest.NewRequest("GET", origin+"/api/"+kind+"/hotel-area/nearby?prefecture=%E7%86%8A%E6%9C%AC%E7%9C%8C", nil))
			if response.Code != 200 || strings.Contains(response.Body.String(), "px.a8.net") != allowed {
				t.Fatalf("hotel %s %s: %d %s", origin, kind, response.Code, response.Body.String())
			}
		}
		response := httptest.NewRecorder()
		advertised.ServeHTTP(response, httptest.NewRequest("GET", origin+"/api/tokusan/tokusan/", nil))
		if response.Code != 200 || strings.Contains(response.Body.String(), "tag=test-22") != allowed {
			t.Fatalf("Amazon %s: code %d, advertisement=%v", origin, response.Code, strings.Contains(response.Body.String(), "tag=test-22"))
		}
	}

}

func TestDefaultCategoryConfig(t *testing.T) {
	t.Setenv("MIDOKORO_DEFAULT_KIND", "")
	config, err := readConfig()
	if err != nil || config.DefaultKind != "shiseki" {
		t.Fatal(config, err)
	}
	t.Setenv("MIDOKORO_DEFAULT_KIND", "tokusan")
	config, err = readConfig()
	if err != nil || config.DefaultKind != "tokusan" {
		t.Fatal(config, err)
	}
	t.Setenv("MIDOKORO_DEFAULT_KIND", "invalid")
	if _, err := readConfig(); err == nil {
		t.Fatal("invalid default must fail startup")
	}
}
