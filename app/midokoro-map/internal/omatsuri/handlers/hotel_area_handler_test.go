package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"midokoro-map/internal/omatsuri/services"
)

func TestHotelAreaNearbyHotels_LargeAreaNameAndFallback(t *testing.T) {
	h := NewHotelAreaHandler(services.NewHotelAreaServiceForTest(""))
	for _, test := range []struct{ query, wantName, wantURL string }{
		{"prefecture=神奈川県&lrg_code=141600&lrg_name=箱根&sml_code=141602&sml_name=箱根", "箱根の宿を探す（じゃらん）", "https://www.jalan.net/140000/LRG_141600/SML_141602/"},
		{"prefecture=神奈川県&lrg_code=141600&lrg_name=箱根", "箱根の宿を探す（じゃらん）", "https://www.jalan.net/140000/LRG_141600/"},
		{"prefecture=神奈川県&lrg_code=091400&lrg_name=誤った地域", "神奈川県の宿を探す（じゃらん）", "https://www.jalan.net/140000/"},
	} {
		req := httptest.NewRequest(http.MethodGet, "/api/hotel-area/nearby?"+test.query, nil)
		w := httptest.NewRecorder()
		h.NearbyHotels(w, req)
		var body hotelAreaResponse
		if err := json.NewDecoder(w.Body).Decode(&body); err != nil || len(body.Hotels) != 1 {
			t.Fatalf("response decode failed: %v body=%s", err, w.Body.String())
		}
		if body.Hotels[0].Name != test.wantName || body.Hotels[0].DetailURL != test.wantURL {
			t.Errorf("hotel = %+v, want name=%q url=%q", body.Hotels[0], test.wantName, test.wantURL)
		}
	}
}
