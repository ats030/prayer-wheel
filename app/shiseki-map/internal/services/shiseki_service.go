package services

import (
	"database/sql"
	"strings"

	_ "modernc.org/sqlite"
)

type Shiseki struct {
	QID               string   `json:"qid"`
	LabelJA           string   `json:"label_ja"`
	LabelEN           string   `json:"label_en"`
	Prefecture        string   `json:"prefecture"`
	Latitude          float64  `json:"latitude"`
	Longitude         float64  `json:"longitude"`
	Description       string   `json:"description"`
	TitleJA           string   `json:"title_ja,omitempty"`
	Era               string   `json:"era,omitempty"`
	Designation       string   `json:"designation,omitempty"`
	DesignationLabel  string   `json:"designation_label,omitempty"`
	DesignationSource string   `json:"designation_source,omitempty"`
	HeritageID        string   `json:"heritage_id,omitempty"`
	SourceURL         string   `json:"source_url,omitempty"`
	Categories        []string `json:"categories"`
}

type ShisekiService struct {
	db *sql.DB
}

const baseSchema = `
CREATE TABLE IF NOT EXISTS shiseki (
	id              INTEGER PRIMARY KEY,
	qid             TEXT NOT NULL UNIQUE,
	label_ja        TEXT NOT NULL,
	label_en        TEXT NOT NULL DEFAULT '',
	prefecture      TEXT NOT NULL DEFAULT '',
	latitude        REAL NOT NULL,
	longitude       REAL NOT NULL,
	description          TEXT NOT NULL DEFAULT '',
	title_ja             TEXT NOT NULL DEFAULT '',
	era               TEXT NOT NULL DEFAULT '',
	designation     TEXT NOT NULL DEFAULT 'unknown',
	designation_label TEXT NOT NULL DEFAULT '',
	designation_source TEXT NOT NULL DEFAULT '',
	heritage_id TEXT NOT NULL DEFAULT '',
	source_url TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS categories (
	id   INTEGER PRIMARY KEY,
	name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS shiseki_categories (
	shiseki_id INTEGER NOT NULL REFERENCES shiseki(id),
	type_id  INTEGER NOT NULL REFERENCES categories(id),
	PRIMARY KEY (shiseki_id, type_id)
);
`

const shisekiColumns = "o.id, o.qid, o.label_ja, o.label_en, o.prefecture," +
	" o.latitude, o.longitude, o.description, o.title_ja, o.era," +
	" o.designation, o.designation_label, o.designation_source, o.heritage_id, o.source_url"

func NewShisekiService(dbPath string) (*ShisekiService, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	if _, err := db.Exec(baseSchema); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec("SELECT 1 FROM shiseki LIMIT 1"); err != nil {
		db.Close()
		return nil, err
	}
	return &ShisekiService{db: db}, nil
}

// ensureColumn backfills a TEXT column on a database built before it existed.
func ensureColumn(db *sql.DB, name, def string) error {
	var n int
	if err := db.QueryRow(
		"SELECT COUNT(*) FROM pragma_table_info('shiseki') WHERE name=?", name,
	).Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		return nil
	}
	_, err := db.Exec("ALTER TABLE shiseki ADD COLUMN " + name + " " + def)
	return err
}

func (s *ShisekiService) Close() error {
	return s.db.Close()
}

// collect runs the given query and joins in normalized categories.
func (s *ShisekiService) collect(query string, args ...any) ([]Shiseki, error) {
	rows, err := s.db.Query(query+" ORDER BY o.label_ja COLLATE NOCASE", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make([]Shiseki, 0)
	idToIndex := make(map[int]int)
	for rows.Next() {
		var o Shiseki
		var id int
		if err := rows.Scan(&id, &o.QID, &o.LabelJA, &o.LabelEN, &o.Prefecture,
			&o.Latitude, &o.Longitude, &o.Description, &o.TitleJA,
			&o.Era, &o.Designation, &o.DesignationLabel, &o.DesignationSource,
			&o.HeritageID, &o.SourceURL); err != nil {
			return nil, err
		}
		idToIndex[id] = len(result)
		o.Categories = []string{}
		result = append(result, o)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// Load category names per shiseki for the collected rows.
	if len(idToIndex) > 0 {
		idIn := make([]string, len(idToIndex))
		i := 0
		for id := range idToIndex {
			idIn[i] = itoa(id)
			i++
		}
		placeholders := strings.Join(idIn, ",")
		typeRow := "SELECT os.shiseki_id, st.name FROM shiseki_categories os" +
			" JOIN categories st ON st.id = os.type_id" +
			" WHERE os.shiseki_id IN (" + placeholders + ") ORDER BY st.name"
		typeRows, err := s.db.Query(typeRow)
		if err != nil {
			return nil, err
		}
		defer typeRows.Close()
		for typeRows.Next() {
			var id int
			var name string
			if err := typeRows.Scan(&id, &name); err != nil {
				return nil, err
			}
			if idx, ok := idToIndex[id]; ok {
				result[idx].Categories = append(result[idx].Categories, name)
			}
		}
		if err := typeRows.Err(); err != nil {
			return nil, err
		}
	}
	return result, nil
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}

func (s *ShisekiService) GetAll() []Shiseki {
	list, _ := s.collect("SELECT " + shisekiColumns + " FROM shiseki o")
	return emptyIfNil(list)
}

func (s *ShisekiService) GetByPrefecture(prefecture string) []Shiseki {
	list, _ := s.collect(
		"SELECT "+shisekiColumns+" FROM shiseki o WHERE o.prefecture = ?", prefecture)
	return emptyIfNil(list)
}

func (s *ShisekiService) GetByQID(qid string) *Shiseki {
	list, _ := s.collect("SELECT "+shisekiColumns+" FROM shiseki o WHERE o.qid = ?", qid)
	if len(list) == 0 {
		return nil
	}
	return &list[0]
}

func (s *ShisekiService) GetByID(qid string) *Shiseki {
	return s.GetByQID(qid)
}

func (s *ShisekiService) GetAllShisekiWithDescriptions() []Shiseki {
	return s.GetAll()
}

func (o *Shiseki) HasCategory(tag string) bool {
	for _, t := range o.Categories {
		if strings.EqualFold(t, tag) {
			return true
		}
	}
	return false
}

func emptyIfNil(list []Shiseki) []Shiseki {
	if list == nil {
		return []Shiseki{}
	}
	return list
}
