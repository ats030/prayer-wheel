package services

import (
	"encoding/json"
	"os"
	"strings"
)

type Festival struct {
	QID        string  `json:"qid"`
	LabelJA    string  `json:"label_ja"`
	LabelEN    string  `json:"label_en"`
	Prefecture string  `json:"prefecture"`
	Latitude   float64 `json:"latitude"`
	Longitude  float64 `json:"longitude"`
}

type FestivalService struct {
	festivals []Festival
}

func NewFestivalService(dataPath string) (*FestivalService, error) {
	data, err := os.ReadFile(dataPath)
	if err != nil {
		return nil, err
	}

	var festivals []Festival
	err = json.Unmarshal(data, &festivals)
	if err != nil {
		return nil, err
	}

	return &FestivalService{festivals: festivals}, nil
}

func (s *FestivalService) GetAll() []Festival {
	return s.festivals
}

func (s *FestivalService) GetByPrefecture(prefecture string) []Festival {
	var result []Festival
	prefLower := strings.ToLower(prefecture)
	for _, f := range s.festivals {
		if strings.ToLower(f.Prefecture) == prefLower {
			result = append(result, f)
		}
	}
	return result
}

func (s *FestivalService) GetByQID(qid string) *Festival {
	for _, f := range s.festivals {
		if f.QID == qid {
			return &f
		}
	}
	return nil
}

func (s *FestivalService) GetByID(qid string) *Festival {
	return s.GetByQID(qid)
}
