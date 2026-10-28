"""Year ranges, year lists and numeric dates: digit runs shaped like phone numbers that are not phone numbers.

Shared by the reader's profile redaction and the candidate evidence contact filter, so the two never drift apart.
A run counts as dates only when dates are all it holds: "2019 - 2021" is dates, "+44 20 1999 2010" is a phone number.
"""
from __future__ import annotations

import re

YEAR_RANGE = re.compile(r"(?<!\d)(?:19|20)\d{2}\s*[\-‐-―−/]\s*(?:(?:19|20)\d{2}|\d{2}|present|current|now)(?!\d)", re.I)
YEAR_LIST = re.compile(r"(?<!\d)(?:(?:19|20)\d{2}[\s,;/|\-]+)+(?:19|20)\d{2}(?!\d)")
DATE_NUM = re.compile(r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}(?!\d)|(?<!\d)(?:19|20)\d{2}-\d{2}-\d{2}(?!\d)")
DATES = (DATE_NUM, YEAR_RANGE, YEAR_LIST)          # full dates first: YEAR_RANGE would take "2026-09" of "2026-09-24"


def blank_dates(text: str) -> str:
    """The text with every year range, year list and date replaced by same-length filler (positions are kept)."""
    for rx in DATES:
        text = rx.sub(lambda m: "Y" * len(m.group(0)), text)
    return text


def only_dates(run: str) -> bool:
    """True when every digit in the run belongs to a year range, year list or date."""
    return not any(c.isdigit() for c in blank_dates(run))
