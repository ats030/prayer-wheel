package services

import "testing"

func TestProductionCoordinatesAcrossQueries(t *testing.T) {
	s, err := NewTokusanService("../../frontend/tokusan.db")
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	all := s.GetAll()
	if len(all) != 1919 {
		t.Fatalf("catalog count = %d", len(all))
	}
	var flower *Tokusan
	for i := range all {
		if all[i].LabelJA == "豊橋花穂" {
			flower = &all[i]
		}
	}
	if flower == nil {
		t.Fatal("missing 豊橋花穂")
	}
	if flower.PrefectureLevel || flower.CoordinateLabel != "豊橋市" || flower.CoordinateKind != "municipality_office" || flower.Latitude != 34.769199 || flower.Longitude != 137.391469 {
		t.Fatalf("unexpected production point: %+v", flower)
	}
	if flower.CoordinateSourceURL == "" || flower.CoordinateSourceName == "" || flower.ProductionArea == "" {
		t.Fatal("missing evidence")
	}
	if flower.RegionScope != "regional" || len(flower.RegionIDs) != 2 || flower.RegionIDs[0] != "23-06" || flower.RegionIDs[1] != "23-07" {
		t.Fatalf("lost multi-region membership: %+v", flower)
	}
	one := s.GetByQID(flower.QID)
	if one == nil || one.CoordinateLabel != flower.CoordinateLabel {
		t.Fatal("QID query lost point")
	}
	found := false
	for _, item := range s.GetByPrefecture("愛知県") {
		if item.QID == flower.QID {
			found = item.CoordinateKind == flower.CoordinateKind
		}
	}
	if !found {
		t.Fatal("prefecture query lost point")
	}
}
