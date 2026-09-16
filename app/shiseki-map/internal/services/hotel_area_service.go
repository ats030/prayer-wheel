package services

import (
	"net/url"
	"os"
)

// jisPrefectureCode maps Japanese prefecture names to their two-digit JIS
// X 0401 administrative codes. Jalan's public area-listing pages use this
// code (times 10000, e.g. 130000 for Tokyo) as the URL path, so this map
// lets us build a destination URL from an shiseki's prefecture name alone,
// without any Jalan API access.
var jisPrefectureCode = map[string]string{
	"北海道": "01", "青森県": "02", "岩手県": "03", "宮城県": "04", "秋田県": "05",
	"山形県": "06", "福島県": "07", "茨城県": "08", "栃木県": "09", "群馬県": "10",
	"埼玉県": "11", "千葉県": "12", "東京都": "13", "神奈川県": "14", "新潟県": "15",
	"富山県": "16", "石川県": "17", "福井県": "18", "山梨県": "19", "長野県": "20",
	"岐阜県": "21", "静岡県": "22", "愛知県": "23", "三重県": "24", "滋賀県": "25",
	"京都府": "26", "大阪府": "27", "兵庫県": "28", "奈良県": "29", "和歌山県": "30",
	"鳥取県": "31", "島根県": "32", "岡山県": "33", "広島県": "34", "山口県": "35",
	"徳島県": "36", "香川県": "37", "愛媛県": "38", "高知県": "39", "福岡県": "40",
	"佐賀県": "41", "長崎県": "42", "熊本県": "43", "大分県": "44", "宮崎県": "45",
	"鹿児島県": "46", "沖縄県": "47",
}

// HotelAreaService builds an affiliate link to Jalan's public,
// prefecture-level hotel-listing page (e.g. https://www.jalan.net/130000/)
// and wraps it through the A8.net redirect used for the (now-disabled)
// Jalan Web Service integration. Unlike JalanService, it needs no Jalan API
// key: the destination URL is built entirely from a prefecture name, and
// only the A8.net tracking id (JALAN_A8MAT) is required.
type HotelAreaService struct {
	a8mat string
}

// NewHotelAreaService builds a HotelAreaService from JALAN_A8MAT in the
// environment. It returns nil when JALAN_A8MAT is unset so callers can skip
// wiring the route: a plain (non-affiliate) link would not earn revenue, so
// there is nothing worth showing until an A8.net program id is configured.
func NewHotelAreaService() *HotelAreaService {
	a8mat := os.Getenv("JALAN_A8MAT")
	if a8mat == "" {
		return nil
	}
	return &HotelAreaService{a8mat: a8mat}
}

// NewHotelAreaServiceForTest builds a HotelAreaService with a caller-supplied
// a8mat value, for use by handler tests.
func NewHotelAreaServiceForTest(a8mat string) *HotelAreaService {
	return &HotelAreaService{a8mat: a8mat}
}

// AreaSearchLink returns an A8.net-wrapped link to Jalan's hotel-listing
// page for the given prefecture, and whether the prefecture was recognized.
func (s *HotelAreaService) AreaSearchLink(prefecture string) (string, bool) {
	code, ok := jisPrefectureCode[prefecture]
	if !ok {
		return "", false
	}
	destURL := "https://www.jalan.net/" + code + "0000/"
	return s.affiliateWrap(destURL), true
}

// affiliateWrap mirrors JalanService.affiliateWrap: it turns a destination
// URL into an A8.net tracking link via a8ejpredirect.
func (s *HotelAreaService) affiliateWrap(destURL string) string {
	if destURL == "" || s.a8mat == "" {
		return destURL
	}
	v := url.Values{}
	v.Set("a8mat", s.a8mat)
	v.Set("a8ejpredirect", destURL)
	return "https://px.a8.net/svt/ejp?" + v.Encode()
}
