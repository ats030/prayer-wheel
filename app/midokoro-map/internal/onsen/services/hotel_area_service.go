package services

import "midokoro-map/internal/shared"

type HotelAreaService = shared.HotelAreaService

var NewHotelAreaService = shared.NewHotelAreaService
var NewHotelAreaServiceForTest = shared.NewHotelAreaServiceForTest

func NewHotelAreaServiceWithID(value string) *HotelAreaService {
	return shared.NewHotelAreaServiceForTest(value)
}
