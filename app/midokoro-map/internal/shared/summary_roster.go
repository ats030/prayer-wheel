package shared

import (
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"fmt"
	_ "modernc.org/sqlite"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
)

var summaryDBs = map[string]struct{ File, Query string }{
	"shiseki":  {"shiseki.db", "SELECT COALESCE(NULLIF(site_id,''),qid) FROM shiseki"},
	"onsen":    {"onsen.db", "SELECT qid FROM onsen"},
	"omatsuri": {"festivals.db", "SELECT qid FROM festival"},
	"tokusan":  {"tokusan.db", "SELECT qid FROM tokusan"},
}

func SummaryDatabaseHashes(dataDir string) (map[string]string, error) {
	hashes := map[string]string{}
	for kind, spec := range summaryDBs {
		hash, _, err := summaryDatabaseSnapshot(filepath.Join(dataDir, kind, spec.File), spec.Query)
		if err != nil {
			return nil, err
		}
		hashes[kind] = hash
	}
	return hashes, nil
}

// Hash schema and rows in one read transaction. SQLite resolves committed WAL
// updates inside this snapshot; hashing only the main file would miss them.
func summaryDatabaseSnapshot(path, idQuery string) (string, []string, error) {
	path, err := filepath.Abs(path)
	if err != nil {
		return "", nil, err
	}
	u := url.URL{Scheme: "file", Path: path, RawQuery: "mode=ro"}
	db, err := sql.Open("sqlite", u.String())
	if err != nil {
		return "", nil, err
	}
	defer db.Close()
	tx, err := db.Begin()
	if err != nil {
		return "", nil, err
	}
	defer tx.Rollback()
	hasher := sha256.New()
	encoder := json.NewEncoder(hasher)
	rows, err := tx.Query("SELECT type,name,COALESCE(sql,'') FROM sqlite_schema ORDER BY type,name")
	if err != nil {
		return "", nil, err
	}
	var tables []string
	for rows.Next() {
		var typ, name, schema string
		if err = rows.Scan(&typ, &name, &schema); err != nil {
			rows.Close()
			return "", nil, err
		}
		if err = encoder.Encode([]string{typ, name, schema}); err != nil {
			rows.Close()
			return "", nil, err
		}
		if typ == "table" {
			tables = append(tables, name)
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return "", nil, err
	}
	for _, table := range tables {
		quoted := "\"" + strings.ReplaceAll(table, "\"", "\"\"") + "\""
		rows, err = tx.Query("SELECT * FROM " + quoted + " LIMIT 0")
		if err != nil {
			return "", nil, err
		}
		columns, e := rows.Columns()
		rows.Close()
		if e != nil {
			return "", nil, e
		}
		if err = encoder.Encode([]any{table, columns}); err != nil {
			return "", nil, err
		}
		order := make([]string, len(columns))
		for i := range order {
			order[i] = strconv.Itoa(i + 1)
		}
		rows, err = tx.Query("SELECT * FROM " + quoted + " ORDER BY " + strings.Join(order, ","))
		if err != nil {
			return "", nil, err
		}
		for rows.Next() {
			values := make([]any, len(columns))
			dest := make([]any, len(columns))
			for i := range values {
				dest[i] = &values[i]
			}
			if err = rows.Scan(dest...); err != nil {
				rows.Close()
				return "", nil, err
			}
			if err = encoder.Encode(values); err != nil {
				rows.Close()
				return "", nil, err
			}
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return "", nil, err
		}
	}
	rows, err = tx.Query(idQuery)
	if err != nil {
		return "", nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			return "", nil, err
		}
		ids = append(ids, id)
	}
	if err = rows.Err(); err != nil {
		return "", nil, err
	}
	return fmt.Sprintf("%x", hasher.Sum(nil)), ids, nil
}

// Require the exact database revision and every ID served by the live API.
// This blocks stale artifacts even when the changed roster has the same count.
func (p PublishedSummaries) ValidateDatabases(dataDir string) error {
	for kind, spec := range summaryDBs {
		hash, ids, err := summaryDatabaseSnapshot(filepath.Join(dataDir, kind, spec.File), spec.Query)
		if err != nil {
			return err
		}
		if p.SourceDBHashes[kind] != hash {
			return fmt.Errorf("%s database changed since summary export", kind)
		}
		seen := map[string]bool{}
		for _, id := range ids {
			if id == "" || seen[id] || p.Items[kind][id] == nil {
				return fmt.Errorf("%s database ID %q missing or duplicated", kind, id)
			}
			seen[id] = true
		}
		if len(seen) != len(p.Items[kind]) {
			return fmt.Errorf("%s publication includes removed database IDs", kind)
		}
	}
	return nil
}
