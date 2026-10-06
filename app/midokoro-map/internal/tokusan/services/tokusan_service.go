package services

import (
	"database/sql"
	"encoding/json"
	"net/url"
	"strings"

	_ "modernc.org/sqlite"
)

type Tokusan struct {
	// QID is the legacy API key; official-source items use a stable local-* ID.
	QID                  string   `json:"qid"`
	LabelJA              string   `json:"label_ja"`
	LabelEN              string   `json:"label_en,omitempty"`
	Place                string   `json:"place"`
	Prefecture           string   `json:"prefecture"`
	City                 string   `json:"city,omitempty"`
	Latitude             float64  `json:"latitude"`
	Longitude            float64  `json:"longitude"`
	Evidence             string   `json:"evidence,omitempty"`
	Confidence           float64  `json:"confidence"`
	SourceURL            string   `json:"source_url,omitempty"`
	SourceName           string   `json:"source_name,omitempty"`
	Description          string   `json:"description,omitempty"`
	ProductionArea       string   `json:"production_area,omitempty"`
	CoordinateKind       string   `json:"coordinate_kind,omitempty"`
	CoordinateLabel      string   `json:"coordinate_label,omitempty"`
	CoordinateSourceURL  string   `json:"coordinate_source_url,omitempty"`
	CoordinateSourceName string   `json:"coordinate_source_name,omitempty"`
	RegionIDs            []string `json:"region_ids"`
	RegionScope          string   `json:"region_scope"`
	AffiliateURL         string   `json:"affiliate_url,omitempty"`
	ShoppingURL          string   `json:"shopping_url,omitempty"`
	FurusatoSearchURL    string   `json:"furusato_search_url,omitempty"`
	Category             string   `json:"category,omitempty"`
	// Maker は生産者・ブランド・製造元の一覧。空文字列は表示しない。
	Maker string `json:"maker,omitempty"`
	// PrefectureLevel indicates a prefectural representative coordinate, not geographic coverage.
	PrefectureLevel bool `json:"prefecture_level"`
}

type TokusanService struct {
	db        *sql.DB
	affiliate string
}

func NewTokusanService(dbPath string) (*TokusanService, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		db.Close()
		return nil, err
	}
	var count int
	if err := db.QueryRow("SELECT COUNT(*) FROM tokusan").Scan(&count); err != nil {
		db.Close()
		return nil, err
	}
	if count == 0 {
		db.Close()
		return nil, sql.ErrNoRows
	}
	return &TokusanService{db: db, affiliate: affiliateTemplate()}, nil
}

func (s *TokusanService) Close() error {
	return s.db.Close()
}

// WithoutAdvertising shares the immutable database without changing the
// advertising configuration used by requests on registered origins.
func (s *TokusanService) WithoutAdvertising() *TokusanService {
	copy := *s
	copy.affiliate = ""
	return &copy
}

func (s *TokusanService) collect(query string, args ...any) ([]Tokusan, error) {
	rows, err := s.db.Query(query+" ORDER BY t.label_ja COLLATE NOCASE", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make([]Tokusan, 0)
	for rows.Next() {
		var t Tokusan
		var regionIDs string
		if err := rows.Scan(&t.QID, &t.LabelJA, &t.LabelEN, &t.Place, &t.Prefecture,
			&t.City, &t.Latitude, &t.Longitude, &t.Evidence, &t.Confidence, &t.SourceURL,
			&t.Category, &t.Maker, &t.PrefectureLevel, &t.SourceName, &t.Description, &t.ProductionArea,
			&t.CoordinateKind, &t.CoordinateLabel, &t.CoordinateSourceURL, &t.CoordinateSourceName, &regionIDs, &t.RegionScope); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(regionIDs), &t.RegionIDs); err != nil {
			return nil, err
		}
		t.AffiliateURL = amazonSearchURL(s.affiliate, t.LabelJA)
		t.ShoppingURL = amazonProductSearchURL(t.LabelJA)
		t.FurusatoSearchURL = furusatoSearchURL(t.LabelJA, t.Prefecture)
		result = append(result, t)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

func (s *TokusanService) GetAll() []Tokusan {
	list, _ := s.collect("SELECT qid, label_ja, label_en, place, prefecture," +
		" city, lat, lng, evidence, confidence, source_url, category, maker, prefecture_level, source_name, description, production_area, coordinate_kind, coordinate_label, coordinate_source_url, coordinate_source_name, region_ids, region_scope FROM tokusan t")
	if list == nil {
		list = []Tokusan{}
	}
	return list
}

func (s *TokusanService) GetByPrefecture(prefecture string) []Tokusan {
	list, _ := s.collect("SELECT qid, label_ja, label_en, place, prefecture,"+
		" city, lat, lng, evidence, confidence, source_url, category, maker, prefecture_level, source_name, description, production_area, coordinate_kind, coordinate_label, coordinate_source_url, coordinate_source_name, region_ids, region_scope FROM tokusan t WHERE t.prefecture = ?", prefecture)
	if list == nil {
		list = []Tokusan{}
	}
	return list
}

func (s *TokusanService) GetByQID(qid string) *Tokusan {
	if qid == "" {
		return nil
	}
	list, _ := s.collect("SELECT qid, label_ja, label_en, place, prefecture,"+
		" city, lat, lng, evidence, confidence, source_url, category, maker, prefecture_level, source_name, description, production_area, coordinate_kind, coordinate_label, coordinate_source_url, coordinate_source_name, region_ids, region_scope FROM tokusan t WHERE t.qid = ?", qid)
	if len(list) == 0 {
		return nil
	}
	return &list[0]
}

// GetHistory returns the official-source history text for one item, or "".
// It stays out of Tokusan so the list payload does not carry long texts.
func (s *TokusanService) GetHistory(qid string) string {
	var history string
	if err := s.db.QueryRow("SELECT history FROM tokusan WHERE qid = ?", qid).Scan(&history); err != nil {
		return ""
	}
	return history
}

// GetProduction returns the official-source production method (製造方法) text
// for one item, or "". It stays out of Tokusan for the same reason as
// GetHistory: the list payload must not carry long texts.
func (s *TokusanService) GetProduction(qid string) string {
	var production string
	if err := s.db.QueryRow("SELECT production FROM tokusan WHERE qid = ?", qid).Scan(&production); err != nil {
		return ""
	}
	return production
}

// WikipediaTitle returns the Japanese Wikipedia article title encoded in
// SourceURL, or "" when SourceURL is not a ja.wikipedia.org article link.
func (t Tokusan) WikipediaTitle() string {
	const prefix = "https://ja.wikipedia.org/wiki/"
	if !strings.HasPrefix(t.SourceURL, prefix) {
		return ""
	}
	title, err := url.PathUnescape(strings.TrimPrefix(t.SourceURL, prefix))
	if err != nil {
		return ""
	}
	return strings.ReplaceAll(title, "_", " ")
}
