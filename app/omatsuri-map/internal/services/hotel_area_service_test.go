package services

import "testing"

func TestAreaSearchLink_LargeAreaAndFallback(t *testing.T) {
	svc := NewHotelAreaServiceForTest("")
	for _, test := range []struct{ prefecture, lrg, want string }{
		{"神奈川県", "141600", "https://www.jalan.net/140000/LRG_141600/"},
		{"神奈川県", "091400", "https://www.jalan.net/140000/"},
		{"茨城県", "", "https://www.jalan.net/100000/"},
		{"栃木県", "", "https://www.jalan.net/080000/"},
		{"群馬県", "", "https://www.jalan.net/090000/"},
	} {
		got, ok := svc.AreaSearchLink(test.prefecture, test.lrg, "")
		if !ok || got != test.want {
			t.Errorf("AreaSearchLink(%q, %q) = %q, %v; want %q", test.prefecture, test.lrg, got, ok, test.want)
		}
	}
}

func TestAreaSearchLink_SmallArea(t *testing.T) {
	svc := NewHotelAreaServiceForTest("")
	link, ok := svc.AreaSearchLink("神奈川県", "141600", "141602")
	if !ok || link != "https://www.jalan.net/140000/LRG_141600/SML_141602/" {
		t.Fatalf("small-area link = %q, %v", link, ok)
	}
}
