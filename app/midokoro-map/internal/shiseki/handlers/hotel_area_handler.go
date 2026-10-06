package handlers

import (
	"encoding/json"
	"net/http"

	"midokoro-map/internal/shiseki/services"
)

type HotelAreaHandler struct {
	service *services.HotelAreaService
}

func NewHotelAreaHandler(service *services.HotelAreaService) *HotelAreaHandler {
	return &HotelAreaHandler{service: service}
}

type hotelAreaHotel struct {
	Name      string `json:"name"`
	DetailURL string `json:"detail_url"`
}

type hotelAreaResponse struct {
	Hotels []hotelAreaHotel `json:"hotels"`
}

// NearbyHotels returns a single "search hotels in this prefecture" affiliate
// link, built from the prefecture query parameter. It replaces the
// lat/lng-based, per-hotel Jalan Web Service search (see JalanHandler),
// which is disabled because Jalan API key registration has been closed
// since 2020-02-25.
func (h *HotelAreaHandler) NearbyHotels(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if h.service == nil {
		http.Error(w, "Hotel area link is not configured", http.StatusServiceUnavailable)
		return
	}

	prefecture := r.URL.Query().Get("prefecture")
	if prefecture == "" {
		http.Error(w, "prefecture parameter is required", http.StatusBadRequest)
		return
	}

	lrgCode := r.URL.Query().Get("lrg_code")
	lrgName := r.URL.Query().Get("lrg_name")
	smlCode := r.URL.Query().Get("sml_code")
	smlName := r.URL.Query().Get("sml_name")
	link, ok := h.service.AreaSearchLink(prefecture, lrgCode, smlCode)
	if !ok {
		http.Error(w, "unknown prefecture", http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(hotelAreaResponse{Hotels: []hotelAreaHotel{
		{Name: areaLabel(prefecture, lrgName, smlName, h.service.IsLargeArea(prefecture, lrgCode), h.service.IsSmallArea(lrgCode, smlCode)) + "の宿を探す（じゃらん）", DetailURL: link},
	}})
}

func areaLabel(prefecture, lrgName, smlName string, validLRG, validSML bool) string {
	if validLRG && validSML && smlName != "" {
		return smlName
	}
	if validLRG && lrgName != "" {
		return lrgName
	}
	return prefecture
}
