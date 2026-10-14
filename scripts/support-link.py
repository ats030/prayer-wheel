"""Render an optional external support link at build time, without payment JS."""
import html
from urllib.parse import urlsplit


def render(source, config):
    start, end = '<!-- SUPPORT:START -->', '<!-- SUPPORT:END -->'
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError('Expected exactly one support template')
    before, rest = source.split(start)
    template, after = rest.split(end)
    if template.count('class="support" hidden') != 1 or template.count('class="btn support-link"') != 1:
        raise ValueError('Support template changed; update the renderer before building')
    url = config.get('url')
    if url is None or url == '':
        return before + start + template + end + after
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 or 127 <= ord(c) <= 159 for c in url):
        raise ValueError('Support URL must be a HTTPS URL without whitespace')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.port == 0:
        raise ValueError('Support URL must use HTTPS without credentials')
    if config.get('usageConfirmed') is not True:
        raise ValueError('Confirm provider eligibility and the published support page before enabling')
    template = template.replace('class="support" hidden', 'class="support"', 1)
    template = template.replace('class="btn support-link"', 'class="btn support-link" href="' + html.escape(url, quote=True) + '"', 1)
    return before + start + template + end + after
