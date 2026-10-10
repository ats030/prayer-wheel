package services

// NormalizeStoredSection uses the same recovery and sanitization as the public Go API.
func NormalizeStoredSection(value string) string {
	return encodeSectionContent(decodeSectionContent(value))
}
