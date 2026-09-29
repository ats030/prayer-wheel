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
