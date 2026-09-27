package services

import (
	"database/sql"
	"net/url"
	"strings"

	_ "modernc.org/sqlite"
)

type Tokusan struct {
	QID        string  `json:"qid"`
	LabelJA    string  `json:"label_ja"`
	LabelEN    string  `json:"label_en,omitempty"`
	Place      string  `json:"place"`
	Prefecture string  `json:"prefecture"`
	City       string  `json:"city,omitempty"`
	Latitude   float64 `json:"latitude"`
	Longitude  float64 `json:"longitude"`
	Evidence   string  `json:"evidence,omitempty"`
	Confidence float64 `json:"confidence"`
	SourceURL  string  `json:"source_url,omitempty"`
	Category   string  `json:"category,omitempty"`
	// PrefectureLevel は産地が都道府県までしか分からず、座標が都道府県庁であることを示す。
	PrefectureLevel bool `json:"prefecture_level"`
}

type TokusanService struct {
	db *sql.DB
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
	return &TokusanService{db: db}, nil
}

func (s *TokusanService) Close() error {
	return s.db.Close()
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
		if err := rows.Scan(&t.QID, &t.LabelJA, &t.LabelEN, &t.Place, &t.Prefecture,
			&t.City, &t.Latitude, &t.Longitude, &t.Evidence, &t.Confidence, &t.SourceURL,
			&t.Category, &t.PrefectureLevel); err != nil {
			return nil, err
		}
		result = append(result, t)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	return result, nil
}

func (s *TokusanService) GetAll() []Tokusan {
	list, _ := s.collect("SELECT qid, label_ja, label_en, place, prefecture," +
		" city, lat, lng, evidence, confidence, source_url, category, prefecture_level FROM tokusan t")
	if list == nil {
		list = []Tokusan{}
	}
	return list
}

func (s *TokusanService) GetByPrefecture(prefecture string) []Tokusan {
	list, _ := s.collect("SELECT qid, label_ja, label_en, place, prefecture,"+
		" city, lat, lng, evidence, confidence, source_url, category, prefecture_level FROM tokusan t WHERE t.prefecture = ?", prefecture)
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
		" city, lat, lng, evidence, confidence, source_url, category, prefecture_level FROM tokusan t WHERE t.qid = ?", qid)
	if len(list) == 0 {
		return nil
	}
	return &list[0]
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
