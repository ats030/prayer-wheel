package services

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"strings"

	_ "modernc.org/sqlite"
)

type Venue struct {
	Name          string  `json:"name"`
	Address       string  `json:"address,omitempty"`
	Latitude      float64 `json:"latitude"`
	Longitude     float64 `json:"longitude"`
	Source        string  `json:"source"`
	CoordinateSrc string  `json:"coordinate_source,omitempty"`
	Precision     string  `json:"precision,omitempty"`
}

type Festival struct {
	QID                         string           `json:"qid"`
	LabelJA                     string           `json:"label_ja"`
	LabelEN                     string           `json:"label_en"`
	Prefecture                  string           `json:"prefecture"`
	Latitude                    float64          `json:"latitude"`
	Longitude                   float64          `json:"longitude"`
	Date                        string           `json:"date"`
	Description                 string           `json:"description"`
	WikipediaTitle              string           `json:"wikipedia_title,omitempty"`
	Venue                       *Venue           `json:"venue,omitempty"`
	Occurrence                  []map[string]any `json:"occurrences,omitempty"`
	AnnualSchedule              []map[string]any `json:"annual_schedule,omitempty"`
	CulturalRelaw               *map[string]any  `json:"cultural_relaw,omitempty"`
	Categories                  []string         `json:"categories"`
	DescriptionSource           string           `json:"description_source,omitempty"`
	CoordinateSource            string           `json:"coordinate_source,omitempty"`
	CoordinatePrefecture        string           `json:"coordinate_prefecture,omitempty"`
	CoordinateValidationSource  string           `json:"coordinate_validation_source,omitempty"`
	JALANLRGCode                string           `json:"jalan_lrg_code,omitempty"`
	JALANLRGName                string           `json:"jalan_lrg_name,omitempty"`
	JALANSMLCode                string           `json:"jalan_sml_code,omitempty"`
	JALANSMLName                string           `json:"jalan_sml_name,omitempty"`
}

type FestivalService struct {
	db *sql.DB
}

const festivalBaseSchema = `
CREATE TABLE IF NOT EXISTS festival (
    id              INTEGER PRIMARY KEY,
    qid             TEXT NOT NULL UNIQUE,
    label_ja        TEXT NOT NULL,
    label_en        TEXT NOT NULL DEFAULT '',
    prefecture      TEXT NOT NULL DEFAULT '',
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    date            TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    wikipedia_title TEXT NOT NULL DEFAULT '',
    venue_json      TEXT NOT NULL DEFAULT '',
    occurrences_json  TEXT NOT NULL DEFAULT '',
    annual_schedule_json TEXT NOT NULL DEFAULT '',
    cultural_relaw_json TEXT NOT NULL DEFAULT '',
    description_source TEXT NOT NULL DEFAULT '',
    coordinate_source TEXT NOT NULL DEFAULT '',
    coordinate_prefecture TEXT NOT NULL DEFAULT '',
    coordinate_validation_source TEXT NOT NULL DEFAULT '',
    jalan_lrg_code  TEXT NOT NULL DEFAULT '',
    jalan_lrg_name  TEXT NOT NULL DEFAULT '',
    jalan_sml_code  TEXT NOT NULL DEFAULT '',
    jalan_sml_name  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_festival_prefecture ON festival (prefecture);
CREATE TABLE IF NOT EXISTS category_types (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS festival_categories (
    festival_id INTEGER NOT NULL REFERENCES festival(id),
    type_id     INTEGER NOT NULL REFERENCES category_types(id),
    PRIMARY KEY (festival_id, type_id)
);
CREATE INDEX IF NOT EXISTS idx_festival_categories_type ON festival_categories (type_id);
`

const festivalColumns =
	"f.id, f.qid, f.label_ja, f.label_en, f.prefecture," +
	" f.latitude, f.longitude, f.date, f.description, f.wikipedia_title," +
	" f.venue_json, f.occurrences_json, f.annual_schedule_json, f.cultural_relaw_json," +
	" f.description_source, f.coordinate_source, f.coordinate_prefecture," +
	" f.coordinate_validation_source," +
	" f.jalan_lrg_code, f.jalan_lrg_name, f.jalan_sml_code, f.jalan_sml_name"

func NewFestivalService(dbPath string) (*FestivalService, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	if _, err := db.Exec(festivalBaseSchema); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec("SELECT 1 FROM festival LIMIT 1"); err != nil {
		db.Close()
		return nil, err
	}
	return &FestivalService{db: db}, nil
}

func (s *FestivalService) Close() error {
	return s.db.Close()
}

func (s *FestivalService) collect(query string, args ...any) ([]Festival, error) {
	rows, err := s.db.Query(query + " ORDER BY f.label_ja COLLATE NOCASE", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]Festival, 0)
	idToIndex := make(map[int]int)
	for rows.Next() {
		var f Festival
		var id int
		var venueJSON, occJSON, annJSON, culJSON string
		if err := rows.Scan(
			&id, &f.QID, &f.LabelJA, &f.LabelEN, &f.Prefecture,
			&f.Latitude, &f.Longitude, &f.Date, &f.Description, &f.WikipediaTitle,
			&venueJSON, &occJSON, &annJSON, &culJSON,
			&f.DescriptionSource, &f.CoordinateSource, &f.CoordinatePrefecture,
			&f.CoordinateValidationSource,
			&f.JALANLRGCode, &f.JALANLRGName, &f.JALANSMLCode, &f.JALANSMLName,
		); err != nil {
			return nil, err
		}
		idToIndex[id] = len(out)
		f.Categories = []string{}
		if f.Venue = decodeVenue(venueJSON); f.Venue == nil {
			f.Venue = nil
		}
		if f.Occurrence = decodeMaps(occJSON); f.Occurrence == nil {
			f.Occurrence = nil
		}
		if f.AnnualSchedule = decodeMaps(annJSON); f.AnnualSchedule == nil {
			f.AnnualSchedule = nil
		}
		if f.CulturalRelaw = decodeAnyMap(culJSON); f.CulturalRelaw == nil {
			f.CulturalRelaw = nil
		}
		out = append(out, f)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	if len(idToIndex) > 0 {
		idIn := make([]string, 0, len(idToIndex))
		for id := range idToIndex {
			idIn = append(idIn, fmt.Sprint(id))
		}
		in := strings.Join(idIn, ",")
		tagRows, err := s.db.Query(
			"SELECT fc.festival_id, ct.name FROM festival_categories fc" +
				" JOIN category_types ct ON ct.id = fc.type_id" +
				" WHERE fc.festival_id IN (" + in + ")",
		)
		if err != nil {
			return nil, err
		}
		defer tagRows.Close()
		for tagRows.Next() {
			var id int
			var name string
			if err := tagRows.Scan(&id, &name); err != nil {
				return nil, err
			}
			if idx, ok := idToIndex[id]; ok {
				out[idx].Categories = append(out[idx].Categories, name)
			}
		}
		if err := tagRows.Err(); err != nil {
			return nil, err
		}
	}
	return out, nil
}

func (s *FestivalService) GetAll() []Festival {
	list, _ := s.collect("SELECT " + festivalColumns + " FROM festival f")
	return emptyIfNil(list)
}

func (s *FestivalService) GetByPrefecture(prefecture string) []Festival {
	list, _ := s.collect(
		"SELECT "+festivalColumns+" FROM festival f WHERE f.prefecture = ?", prefecture)
	return emptyIfNil(list)
}

func (s *FestivalService) GetByQID(qid string) *Festival {
	list, _ := s.collect("SELECT "+festivalColumns+" FROM festival f WHERE f.qid = ?", qid)
	if len(list) == 0 {
		return nil
	}
	return &list[0]
}

func (s *FestivalService) GetByID(qid string) *Festival {
	return s.GetByQID(qid)
}

func (s *FestivalService) GetAllFestivalsWithDescriptions() []Festival {
	return s.GetAll()
}

func (s *FestivalService) GetCategories() []string {
	rows, err := s.db.Query("SELECT name FROM category_types ORDER BY name")
	if err != nil {
		return []string{}
	}
	defer rows.Close()
	out := make([]string, 0)
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return []string{}
		}
		out = append(out, name)
	}
	if err := rows.Err(); err != nil {
		return []string{}
	}
	return out
}

func (f *Festival) HasCategory(tag string) bool {
	for _, c := range f.Categories {
		if strings.EqualFold(c, tag) {
			return true
		}
	}
	return false
}

func decodeVenue(raw string) *Venue {
	if raw == "" || raw == "null" {
		return nil
	}
	var v Venue
	if err := json.Unmarshal([]byte(raw), &v); err != nil {
		return nil
	}
	return &v
}

func decodeMaps(raw string) []map[string]any {
	if raw == "" || raw == "null" {
		return nil
	}
	var m []map[string]any
	if err := json.Unmarshal([]byte(raw), &m); err != nil {
		return nil
	}
	return m
}

func decodeAnyMap(raw string) *map[string]any {
	if raw == "" || raw == "null" {
		return nil
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(raw), &m); err != nil {
		return nil
	}
	return &m
}

func emptyIfNil(list []Festival) []Festival {
	if list == nil {
		return []Festival{}
	}
	return list
}
