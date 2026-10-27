"""Date-window resolution for phrases in the question.

"Last week" is the honest calendar window: the 7 days ending yesterday.
Relative windows end yesterday; explicit dates may run up to today.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

ISO = r"(\d{4}-\d{2}-\d{2})"
_ISO_RE = re.compile(ISO)
_RANGE_RE = re.compile(rf"(?:from|between)?\s*{ISO}\s*(?:to|and|-|–|through|until)\s*{ISO}", re.I)
_SINCE_RE = re.compile(rf"\bsince\s+{ISO}", re.I)
_LAST_N_RE = re.compile(r"\b(?:last|past|previous)\s+(\d{1,3})\s+days?\b", re.I)
_LAST_N_WEEKS_RE = re.compile(r"\b(?:last|past|previous)\s+(\d{1,2})\s+weeks?\b", re.I)
_WEEK_RE = re.compile(r"\b(?:last|past|previous)\s+week\b|\bthis\s+week\b|\blast\s+7\s+days\b", re.I)
_YESTERDAY_RE = re.compile(r"\byesterday\b", re.I)
_THIS_MONTH_RE = re.compile(r"\bthis\s+month\b", re.I)
_LAST_MONTH_RE = re.compile(r"\b(?:last|past|previous)\s+month\b", re.I)
_THIS_YEAR_RE = re.compile(r"\bthis\s+year\b", re.I)
_LAST_YEAR_RE = re.compile(r"\blast\s+year\b", re.I)
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTH_RE = re.compile(
    r"\b(?:in|during|for|of)?\s*(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b\.?\s*(\d{4})?",
    re.I,
)
_YEAR_RE = re.compile(r"\b(?:in|during|for)\s+(20\d{2})\b", re.I)


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    label: str = ""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def prior(self) -> "Window":
        n = self.days
        return Window(self.start - timedelta(days=n), self.start - timedelta(days=1), "preceding window")

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "label": self.label}

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


def default_window(today: date) -> Window:
    end = today - timedelta(days=1)
    return Window(end - timedelta(days=6), end, "last week (7 days ending yesterday)")


def has_explicit_dates(question: str) -> bool:
    return bool(_ISO_RE.search(question) or _MONTH_RE.search(question) or _YEAR_RE.search(question))


def resolve(question: str, today: date) -> Window | None:  # noqa: C901 - a phrase table
    q = question.strip()
    yesterday = today - timedelta(days=1)

    if m := _RANGE_RE.search(q):
        start, end = _parse(m.group(1)), _parse(m.group(2))
        if start and end and start <= end:
            return Window(start, min(end, today), f"{start} to {end}")
    if m := _SINCE_RE.search(q):
        start = _parse(m.group(1))
        if start and start <= today:
            return Window(start, today, f"since {start}")
    if m := _LAST_N_RE.search(q):
        n = max(1, int(m.group(1)))
        return Window(yesterday - timedelta(days=n - 1), yesterday, f"last {n} days (ending yesterday)")
    if m := _LAST_N_WEEKS_RE.search(q):
        n = max(1, int(m.group(1))) * 7
        return Window(yesterday - timedelta(days=n - 1), yesterday, f"last {n // 7} weeks (ending yesterday)")
    if _WEEK_RE.search(q):
        if re.search(r"\bthis\s+week\b", q, re.I):
            monday = today - timedelta(days=today.weekday())
            start = min(monday, yesterday)
            return Window(start, yesterday, "this week (to yesterday)")
        return default_window(today)
    if _YESTERDAY_RE.search(q):
        return Window(yesterday, yesterday, "yesterday")
    if _THIS_MONTH_RE.search(q):
        start = today.replace(day=1)
        return Window(min(start, yesterday), yesterday, "this month (to yesterday)")
    if _LAST_MONTH_RE.search(q):
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        return Window(end.replace(day=1), end, "last month")
    if _THIS_YEAR_RE.search(q):
        return Window(min(today.replace(month=1, day=1), yesterday), yesterday, "this year (to yesterday)")
    if _LAST_YEAR_RE.search(q):
        y = today.year - 1
        return Window(date(y, 1, 1), date(y, 12, 31), f"{y}")
    if m := _MONTH_RE.search(q):
        month = _MONTHS[m.group(1).lower()]
        year = int(m.group(2)) if m.group(2) else _latest_year_for_month(month, today)
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        if start <= today:
            return Window(start, min(end, today), f"{calendar.month_name[month]} {year}")
    if m := _YEAR_RE.search(q):
        y = int(m.group(1))
        if y <= today.year:
            return Window(date(y, 1, 1), min(date(y, 12, 31), today), f"{y}")
    singles = _ISO_RE.findall(q)
    if len(singles) == 1 and (d := _parse(singles[0])) and d <= today:
        return Window(d, d, singles[0])
    return None


def _latest_year_for_month(month: int, today: date) -> int:
    return today.year if month <= today.month else today.year - 1


def _parse(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
