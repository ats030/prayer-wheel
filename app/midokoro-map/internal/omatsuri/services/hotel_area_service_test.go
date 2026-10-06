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

func TestAreaSearchLink_JalanCodesDifferingFromJIS(t *testing.T) {
	svc := NewHotelAreaServiceForTest("")
	for _, tc := range []struct{ prefecture, lrg, sml string }{
		{"山梨県", "150100", "150105"}, {"長野県", "160600", "160605"},
		{"新潟県", "171700", "171705"}, {"富山県", "180800", "180805"},
		{"石川県", "192600", "192605"}, {"福井県", "200300", "200302"},
		{"静岡県", "210400", "210402"}, {"岐阜県", "220500", "220502"},
	} {
		want := "https://www.jalan.net/" + tc.lrg[:2] + "0000/LRG_" + tc.lrg + "/SML_" + tc.sml + "/"
		if got, ok := svc.AreaSearchLink(tc.prefecture, tc.lrg, tc.sml); !ok || got != want {
			t.Errorf("%s link = %q, %v; want %q", tc.prefecture, got, ok, want)
		}
	}
}
