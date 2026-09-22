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
