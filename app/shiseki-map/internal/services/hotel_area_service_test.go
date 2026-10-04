package services

import (
	"net/url"
	"os"
	"strings"
	"testing"
)

func TestNewHotelAreaService_UnconfiguredReturnsNil(t *testing.T) {
	old, had := os.LookupEnv("JALAN_A8MAT")
	os.Unsetenv("JALAN_A8MAT")
	defer func() {
		if had {
			os.Setenv("JALAN_A8MAT", old)
		}
	}()

	if svc := NewHotelAreaService(); svc != nil {
		t.Fatalf("Expected nil when JALAN_A8MAT is unset, got %+v", svc)
	}
}

func TestNewHotelAreaService_ConfiguredReturnsService(t *testing.T) {
	old, had := os.LookupEnv("JALAN_A8MAT")
	os.Setenv("JALAN_A8MAT", "test-a8mat")
	defer func() {
		if had {
			os.Setenv("JALAN_A8MAT", old)
		} else {
			os.Unsetenv("JALAN_A8MAT")
		}
	}()

	if svc := NewHotelAreaService(); svc == nil {
		t.Fatal("Expected non-nil service when JALAN_A8MAT is set")
	}
}

func TestAreaSearchLink_UnknownPrefectureReturnsFalse(t *testing.T) {
	svc := NewHotelAreaServiceForTest("test-a8mat")

	if _, ok := svc.AreaSearchLink("存在しない県", "", ""); ok {
		t.Fatal("Expected ok=false for an unrecognized prefecture")
	}
}

func TestAreaSearchLink_KnownPrefectureWrapsA8Link(t *testing.T) {
	svc := NewHotelAreaServiceForTest("test-a8mat")

	link, ok := svc.AreaSearchLink("東京都", "", "")
	if !ok {
		t.Fatal("Expected ok=true for 東京都")
	}

	parsed, err := url.Parse(link)
	if err != nil {
		t.Fatalf("Link is not a valid URL: %v", err)
	}
	if parsed.Host != "px.a8.net" {
		t.Errorf("Host = %q, want px.a8.net", parsed.Host)
	}
	q := parsed.Query()
	if q.Get("a8mat") != "test-a8mat" {
		t.Errorf("a8mat = %q, want test-a8mat", q.Get("a8mat"))
	}
	if !strings.Contains(q.Get("a8ejpredirect"), "https://www.jalan.net/130000/") {
		t.Errorf("a8ejpredirect = %q, want it to contain https://www.jalan.net/130000/", q.Get("a8ejpredirect"))
	}
}

func TestAreaSearchLink_WithoutA8matReturnsPlainURL(t *testing.T) {
	svc := NewHotelAreaServiceForTest("")

	link, ok := svc.AreaSearchLink("東京都", "", "")
	if !ok {
		t.Fatal("Expected ok=true for 東京都")
	}
	if link != "https://www.jalan.net/130000/" {
		t.Errorf("link = %q, want the plain destination URL", link)
	}
}

func TestAreaSearchLink_LargeAreaAndPrefectureFallback(t *testing.T) {
	svc := NewHotelAreaServiceForTest("")
	link, ok := svc.AreaSearchLink("神奈川県", "141600", "")
	if !ok || link != "https://www.jalan.net/140000/LRG_141600/" {
		t.Fatalf("large-area link = %q, %v", link, ok)
	}
	link, ok = svc.AreaSearchLink("神奈川県", "091400", "")
	if !ok || link != "https://www.jalan.net/140000/" {
		t.Fatalf("mismatched LRG should fall back, got %q, %v", link, ok)
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

func TestAreaSearchLink_MultiPrefectureSiteUsesAssignedRegion(t *testing.T) {
	svc := NewHotelAreaServiceForTest("")
	got, ok := svc.AreaSearchLink("２県以上", "141600", "141602")
	if !ok || got != "https://www.jalan.net/140000/LRG_141600/SML_141602/" {
		t.Fatalf("multi-prefecture region link = %q, %v", got, ok)
	}
	if !svc.IsLargeArea("２県以上", "141600") {
		t.Fatal("assigned region should be recognized for its label")
	}
	for _, code := range []string{"", "xx1600", "14xx00", "141602", "991600"} {
		if _, ok := svc.AreaSearchLink("２県以上", code, ""); ok {
			t.Errorf("invalid multi-prefecture assignment %q was accepted", code)
		}
	}
	if _, ok := svc.AreaSearchLink("unknown", "141600", "141602"); ok {
		t.Fatal("unknown prefectures should still be rejected")
	}
}

func TestAreaSearchLink_UsesJalanCodesForNorthKanto(t *testing.T) {
	svc := NewHotelAreaServiceForTest("")
	for prefecture, want := range map[string]string{
		"茨城県": "https://www.jalan.net/100000/",
		"栃木県": "https://www.jalan.net/080000/",
		"群馬県": "https://www.jalan.net/090000/",
	} {
		got, ok := svc.AreaSearchLink(prefecture, "", "")
		if !ok || got != want {
			t.Errorf("%s link = %q, %v; want %q", prefecture, got, ok, want)
		}
	}
}
