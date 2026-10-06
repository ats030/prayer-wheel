package services

import (
	"net/url"
	"testing"
)

func TestAmazonSearchURL(t *testing.T) {
	template := "https://www.amazon.co.jp/s?k={query}&tag=test-22"
	label := "南部せんべい & 岩手"
	u, err := url.Parse(amazonSearchURL(template, label))
	if err != nil || u.Query().Get("k") != label || u.Query().Get("tag") != "test-22" {
		t.Fatalf("query must preserve the item name and associate tag: %v", u)
	}
	for _, invalid := range []string{"", "http://www.amazon.co.jp/s?k={query}&tag=test-22", "https://evil.example/s?k={query}&tag=test-22", "https://www.amazon.co.jp.evil.example/s?k={query}&tag=test-22", "https://user:pass@www.amazon.co.jp/s?k={query}&tag=test-22", "https://www.amazon.co.jp/s?k={query}", "https://www.amazon.co.jp/s?k=fixed&tag=test-22", "https://www.amazon.co.jp/dp/x?k={query}&tag=test-22"} {
		if got := amazonSearchURL(invalid, label); got != "" {
			t.Errorf("accepted invalid template: %s", invalid)
		}
	}
}

func TestAffiliateExplicitDisable(t *testing.T) {
	t.Setenv("TOKUSAN_AMAZON_URL", "")
	if affiliateTemplate() != "" {
		t.Fatal("empty explicit configuration must disable local fallback")
	}
}

func TestAmazonProductSearchWithoutAffiliate(t *testing.T) {
	u, err := url.Parse(amazonProductSearchURL("わかさいも & 北海道"))
	if err != nil || u.Query().Get("k") != "わかさいも & 北海道" || u.Query().Has("tag") {
		t.Fatal("ordinary search must preserve the item name without an associate tag")
	}
	if amazonSearchURL("", "わかさいも") != "" {
		t.Fatal("an unset affiliate template must not create an affiliate link")
	}
}

func TestFurusatoSearchPreservesKeywords(t *testing.T) {
	label := "茶 & 菓子/詰合せ?#"
	u, err := url.Parse(furusatoSearchURL(label, "京都府"))
	if err != nil {
		t.Fatal(err)
	}
	if u.Scheme != "https" || u.Host != "search.rakuten.co.jp" || u.Path != "/search/mall/ふるさと納税 "+label+" 京都府/" || u.RawQuery != "" || u.Fragment != "" {
		t.Fatalf("keywords escaped into URL structure: %s", u)
	}
	for _, pair := range [][2]string{{"", "北海道"}, {"メロン", ""}, {" ", "北海道"}} {
		if furusatoSearchURL(pair[0], pair[1]) != "" {
			t.Fatal("incomplete origin/name must not produce a search link")
		}
	}
}
