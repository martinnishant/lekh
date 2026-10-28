"""Money, ratio and date parsing for Indian retail credit documents.

Everything downstream depends on getting `1.40 L`, `1,40,000/-`, `Rs. 140000.00`
and `1.4 lakh` to the same integer, and on refusing to guess when the document
is ambiguous. A parser that silently returns a number for garbage is worse than
an exception: it manufactures evidence.
"""
from __future__ import annotations

import datetime as _dt
import re

_UNITS = {
    "cr": 1e7, "crore": 1e7, "crores": 1e7,
    "l": 1e5, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5, "lakhs.": 1e5,
    "k": 1e3, "thousand": 1e3,
}

_MONEY_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>crores?|cr|lakhs?|lakh|lacs?|lac|l|k|thousand)?",
    re.IGNORECASE,
)

_PCT_RE = re.compile(r"(?P<num>\d{1,3}(?:\.\d+)?)\s*%")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class ParseError(ValueError):
    """Raised instead of returning a plausible-looking wrong number."""


def parse_money(text: str) -> float:
    """Parse an Indian-formatted money string into rupees.

    >>> parse_money("Rs. 52,00,000/-")
    5200000.0
    >>> parse_money("1.40 L")
    140000.0
    >>> parse_money("1.4 lakh")
    140000.0
    """
    if text is None:
        raise ParseError("empty money string")
    cleaned = text.strip()
    cleaned = re.sub(r"(?i)^\s*(?:rs\.?|inr|₹)\s*", "", cleaned)
    cleaned = cleaned.replace("₹", "").replace("/-", "").strip()
    m = _MONEY_RE.search(cleaned)
    if not m:
        raise ParseError(f"not a money string: {text!r}")
    num = float(m.group("num").replace(",", ""))
    unit = (m.group("unit") or "").lower()
    if unit:
        if unit not in _UNITS:
            raise ParseError(f"unknown money unit {unit!r} in {text!r}")
        num *= _UNITS[unit]
    return round(num, 2)


def parse_pct(text: str) -> float:
    """Return a percentage as a fraction: '62%' -> 0.62."""
    m = _PCT_RE.search(text or "")
    if not m:
        raise ParseError(f"not a percentage: {text!r}")
    return round(float(m.group("num")) / 100.0, 6)


def parse_date(text: str) -> _dt.date:
    """Parse '12 May 2026', '12/05/2026', '2026-05-12'."""
    s = (text or "").strip()
    for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ParseError(f"not a date: {text!r}")


def inr(n: float) -> str:
    """Indian digit grouping: 5200000 -> '52,00,000'."""
    neg = n < 0
    n = abs(round(float(n)))
    s = str(int(n))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts) + "," + tail
    return ("-" if neg else "") + out


def pct(x: float, places: int = 1) -> str:
    return f"{x * 100:.{places}f}%"
