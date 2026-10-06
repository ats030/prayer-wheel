package services

import (
	"database/sql"
	"strings"

	_ "modernc.org/sqlite"
)

type Onsen struct {
	QID                 string   `json:"qid"`
	LabelJA             string   `json:"label_ja"`
	LabelEN             string   `json:"label_en"`
	Prefecture          string   `json:"prefecture"`
	Latitude            float64  `json:"latitude"`
	Longitude           float64  `json:"longitude"`
	JalanLRGCode        string   `json:"jalan_lrg_code,omitempty"`
	JalanLRGName        string   `json:"jalan_lrg_name,omitempty"`
	JalanSMLCode        string   `json:"jalan_sml_code,omitempty"`
	JalanSMLName        string   `json:"jalan_sml_name,omitempty"`
	Description         string   `json:"description"`
	TitleJA             string   `json:"title_ja,omitempty"`
	SpringTypeRaw       string   `json:"spring_type_raw,omitempty"`
	SpringTypeSource    string   `json:"spring_type_source,omitempty"`
	OperatingStatus     string   `json:"operating_status,omitempty"`
	OperatingStatusNote string   `json:"operating_status_note,omitempty"`
	SpringTypes         []string `json:"spring_types"`
}

type OnsenService struct {
	db *sql.DB
}

const baseSchema = `
CREATE TABLE IF NOT EXISTS onsen (
	id              INTEGER PRIMARY KEY,
	qid             TEXT NOT NULL UNIQUE,
	label_ja        TEXT NOT NULL,
	label_en        TEXT NOT NULL DEFAULT '',
	prefecture      TEXT NOT NULL DEFAULT '',
	latitude        REAL NOT NULL,
	longitude       REAL NOT NULL,
	description          TEXT NOT NULL DEFAULT '',
	title_ja             TEXT NOT NULL DEFAULT '',
	spring_type_raw      TEXT NOT NULL DEFAULT '',
	spring_type_source   TEXT NOT NULL DEFAULT '',
	operating_status     TEXT NOT NULL DEFAULT 'unknown',
	operating_status_note TEXT NOT NULL DEFAULT '',
	jalan_lrg_code TEXT NOT NULL DEFAULT '',
	jalan_lrg_name TEXT NOT NULL DEFAULT ''
	,jalan_sml_code TEXT NOT NULL DEFAULT ''
	,jalan_sml_name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS spring_types (
	id   INTEGER PRIMARY KEY,
	name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS onsen_springs (
	onsen_id INTEGER NOT NULL REFERENCES onsen(id),
	type_id  INTEGER NOT NULL REFERENCES spring_types(id),
	PRIMARY KEY (onsen_id, type_id)
);
`

const onsenColumns = "o.id, o.qid, o.label_ja, o.label_en, o.prefecture," +
	" o.latitude, o.longitude, o.description, o.title_ja, o.spring_type_raw, o.spring_type_source," +
	" o.operating_status, o.operating_status_note, o.jalan_lrg_code, o.jalan_lrg_name, o.jalan_sml_code, o.jalan_sml_name"

func NewOnsenService(dbPath string) (*OnsenService, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	if _, err := db.Exec(baseSchema); err != nil {
		db.Close()
		return nil, err
	}
	if _, err := db.Exec("SELECT 1 FROM onsen LIMIT 1"); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureSpringTypeRawColumn(db); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureSpringTypeSourceColumn(db); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureOperatingStatusColumn(db); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureOperatingStatusNoteColumn(db); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureColumn(db, "jalan_lrg_code", "TEXT NOT NULL DEFAULT ''"); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureColumn(db, "jalan_lrg_name", "TEXT NOT NULL DEFAULT ''"); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureColumn(db, "jalan_sml_code", "TEXT NOT NULL DEFAULT ''"); err != nil {
		db.Close()
		return nil, err
	}
	if err := ensureColumn(db, "jalan_sml_name", "TEXT NOT NULL DEFAULT ''"); err != nil {
		db.Close()
		return nil, err
	}
	return &OnsenService{db: db}, nil
}

// ensureColumn backfills a TEXT column on a database built before it existed.
func ensureColumn(db *sql.DB, name, def string) error {
	var n int
	if err := db.QueryRow(
		"SELECT COUNT(*) FROM pragma_table_info('onsen') WHERE name=?", name,
	).Scan(&n); err != nil {
		return err
	}
	if n > 0 {
		return nil
	}
	_, err := db.Exec("ALTER TABLE onsen ADD COLUMN " + name + " " + def)
	return err
}

// ensureSpringTypeRawColumn backfills the spring_type_raw column on databases
// built before the column existed.
func ensureSpringTypeRawColumn(db *sql.DB) error {
	return ensureColumn(db, "spring_type_raw", "TEXT NOT NULL DEFAULT ''")
}

// ensureSpringTypeSourceColumn backfills the spring_type_source column on
// databases built before the column existed.
func ensureSpringTypeSourceColumn(db *sql.DB) error {
	return ensureColumn(db, "spring_type_source", "TEXT NOT NULL DEFAULT ''")
}

func ensureOperatingStatusColumn(db *sql.DB) error {
	return ensureColumn(db, "operating_status", "TEXT NOT NULL DEFAULT 'unknown'")
}

func ensureOperatingStatusNoteColumn(db *sql.DB) error {
	return ensureColumn(db, "operating_status_note", "TEXT NOT NULL DEFAULT ''")
}

func (s *OnsenService) Close() error {
	return s.db.Close()
}

// collect runs the given query and joins in the normalized spring types.
func (s *OnsenService) collect(query string, args ...any) ([]Onsen, error) {
	rows, err := s.db.Query(query+" ORDER BY o.label_ja COLLATE NOCASE", args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := make([]Onsen, 0)
	idToIndex := make(map[int]int)
	for rows.Next() {
		var o Onsen
		var id int
		if err := rows.Scan(&id, &o.QID, &o.LabelJA, &o.LabelEN, &o.Prefecture,
			&o.Latitude, &o.Longitude, &o.Description, &o.TitleJA,
			&o.SpringTypeRaw, &o.SpringTypeSource,
			&o.OperatingStatus, &o.OperatingStatusNote, &o.JalanLRGCode, &o.JalanLRGName, &o.JalanSMLCode, &o.JalanSMLName); err != nil {
			return nil, err
		}
		idToIndex[id] = len(result)
		o.SpringTypes = []string{}
		result = append(result, o)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}

	// Load spring type names per onsen for the collected rows.
	if len(idToIndex) > 0 {
		idIn := make([]string, len(idToIndex))
		i := 0
		for id := range idToIndex {
			idIn[i] = itoa(id)
			i++
		}
		placeholders := strings.Join(idIn, ",")
		typeRow := "SELECT os.onsen_id, st.name FROM onsen_springs os" +
			" JOIN spring_types st ON st.id = os.type_id" +
			" WHERE os.onsen_id IN (" + placeholders + ") ORDER BY st.name"
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
				result[idx].SpringTypes = append(result[idx].SpringTypes, name)
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

func (s *OnsenService) GetAll() []Onsen {
	list, _ := s.GetAllChecked()
	return emptyIfNil(list)
}

func (s *OnsenService) GetAllChecked() ([]Onsen, error) {
	return s.collect("SELECT " + onsenColumns + " FROM onsen o")
}

func (s *OnsenService) GetByPrefecture(prefecture string) []Onsen {
	list, _ := s.collect(
		"SELECT "+onsenColumns+" FROM onsen o WHERE o.prefecture = ?", prefecture)
	return emptyIfNil(list)
}

func (s *OnsenService) GetByQID(qid string) *Onsen {
	list, _ := s.collect("SELECT "+onsenColumns+" FROM onsen o WHERE o.qid = ?", qid)
	if len(list) == 0 {
		return nil
	}
	return &list[0]
}

func (s *OnsenService) GetByID(qid string) *Onsen {
	return s.GetByQID(qid)
}

func (s *OnsenService) GetAllOnsenWithDescriptions() []Onsen {
	return s.GetAll()
}

func (o *Onsen) HasSpringType(tag string) bool {
	for _, t := range o.SpringTypes {
		if strings.EqualFold(t, tag) {
			return true
		}
	}
	return false
}

func emptyIfNil(list []Onsen) []Onsen {
	if list == nil {
		return []Onsen{}
	}
	return list
}
