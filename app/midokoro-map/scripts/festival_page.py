"""Render one static page per festival from dated, sourced facts only (no generated text)."""
from datetime import date
from html import escape
from urllib.parse import quote, urlsplit

from festival_calendar import ORIGIN, period


def render_page(festival, today):
    raise NotImplementedError
