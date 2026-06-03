#!/usr/bin/env python3
"""
Generate calendar.ics from festivals.json.

Each festival becomes a yearly-recurring event spanning its months.

Produce season information lives in the In Season tab of the app rather
than the calendar feed — long peak periods don't make useful calendar
events. Festivals are the time-sensitive, plannable items, so the feed
focuses on those.

Re-run this whenever festivals.json changes.

    python3 generate_calendar.py
"""

import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
FESTIVALS_FILE = ROOT / "festivals.json"
OUT_FILE       = ROOT / "calendar.ics"

# Use 2026 as the base year for first occurrence — events recur yearly via RRULE
BASE_YEAR = 2026

# Number of days in each month (non-leap year is fine since we just need last-day-of-month)
MONTH_END_DAY = {
    0:  31, 1:  28, 2:  31, 3:  30,  4:  31,  5:  30,
    6:  31, 7:  31, 8:  30, 9:  31, 10:  30, 11:  31,
}

def contiguous_ranges(months):
    """
    Given a list of 0-indexed month numbers, return a list of contiguous ranges
    as (start_month, end_month) tuples. Handles year-wrap (e.g. [9,10,11,0,1]
    becomes a single range (9, 1) which crosses the year boundary).
    """
    if not months:
        return []
    months = sorted(set(months))

    # Detect wrap-around case: contains both 11 (Dec) and 0 (Jan), with no gap between
    wraps = 11 in months and 0 in months

    if wraps:
        # Rotate so we find the "start" (a month whose previous month is NOT in the set)
        for m in months:
            if ((m - 1) % 12) not in months:
                start = m
                break
        else:
            # All 12 months — single year-round range
            return [(0, 11)]
        # Walk forward from start, wrapping
        ordered = []
        m = start
        for _ in range(12):
            if m in months:
                ordered.append(m)
                m = (m + 1) % 12
            else:
                break
        if ordered:
            return [(ordered[0], ordered[-1])]
        return []
    else:
        # No wrap — find consecutive runs
        ranges = []
        current = [months[0]]
        for m in months[1:]:
            if m == current[-1] + 1:
                current.append(m)
            else:
                ranges.append((current[0], current[-1]))
                current = [m]
        ranges.append((current[0], current[-1]))
        return ranges


def fold_line(line):
    """ICS lines must be folded at 75 octets — split with CRLF + space continuation."""
    if len(line) <= 75:
        return line
    out = [line[:75]]
    rest = line[75:]
    while rest:
        out.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(out)


def escape(text):
    """Escape ICS special characters."""
    if text is None:
        return ""
    return (
        text.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n")
            .replace("\r", "")
    )


def make_event(uid, dt_start, dt_end_exclusive, summary, description, location, url, categories):
    """
    Build a single VEVENT block as a list of lines.
    All-day events use DATE values; DTEND is exclusive in iCalendar.
    Recurs yearly.
    """
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}@ulster.food",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{dt_start.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{dt_end_exclusive.strftime('%Y%m%d')}",
        "RRULE:FREQ=YEARLY",
        f"SUMMARY:{escape(summary)}",
        f"DESCRIPTION:{escape(description)}",
    ]
    if location:
        lines.append(f"LOCATION:{escape(location)}")
    if url:
        lines.append(f"URL:{url}")
    if categories:
        lines.append(f"CATEGORIES:{escape(categories)}")
    lines.append("TRANSP:TRANSPARENT")
    lines.append("END:VEVENT")
    return [fold_line(l) for l in lines]


def date_for_month(year, month, day=1):
    """Construct a date — month is 0-indexed."""
    return date(year, month + 1, day)


def event_dates_for_range(start_month, end_month):
    """
    Return (DTSTART, DTEND-exclusive) for a contiguous month range.
    If end_month < start_month, the range wraps into the following year.
    DTEND is the day AFTER the last day of end_month.
    """
    start = date_for_month(BASE_YEAR, start_month)
    if end_month >= start_month:
        last_day = MONTH_END_DAY[end_month]
        end_inclusive = date_for_month(BASE_YEAR, end_month, last_day)
    else:
        last_day = MONTH_END_DAY[end_month]
        end_inclusive = date_for_month(BASE_YEAR + 1, end_month, last_day)
    end_exclusive = end_inclusive + timedelta(days=1)
    return start, end_exclusive


def main():
    with FESTIVALS_FILE.open() as f:
        festivals = json.load(f)

    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ulster.food//Festivals Feed//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "NAME:Ulster.food — food festivals",
        "X-WR-CALNAME:Ulster.food — food festivals",
        "DESCRIPTION:Food and farming festivals across Ulster. Subscribe at ulster.food/calendar.ics",
        "X-WR-CALDESC:Food and farming festivals across Ulster. Subscribe at ulster.food/calendar.ics",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
        "COLOR:#C4622D",
    ]

    # ── Festivals ────────────────────────────────────────────────────
    for fest in festivals:
        ranges = contiguous_ranges(fest["months"])
        for idx, (start_m, end_m) in enumerate(ranges):
            dt_start, dt_end = event_dates_for_range(start_m, end_m)
            summary = f"🎪 {fest['name']}"
            desc_parts = [
                fest["story"],
                "",
                f"Dates: {fest.get('dates', '')}",
            ]
            if fest.get("focus"):
                desc_parts.append(f"Focus: {fest['focus']}")
            if fest.get("url"):
                desc_parts.append(f"More info: {fest['url']}")
            desc_parts.append("")
            desc_parts.append("Full guide at ulster.food")
            description = "\n".join(desc_parts)
            categories = "Festival," + fest.get("type", "food").capitalize()
            uid_suffix = f"-r{idx}" if len(ranges) > 1 else ""
            out.extend(make_event(
                uid=f"festival-{fest['id']}{uid_suffix}",
                dt_start=dt_start,
                dt_end_exclusive=dt_end,
                summary=summary,
                description=description,
                location=fest["location"]["label"],
                url=fest.get("url", "https://ulster.food/#season"),
                categories=categories,
            ))

    out.append("END:VCALENDAR")

    # ICS uses CRLF line endings
    content = "\r\n".join(out) + "\r\n"
    OUT_FILE.write_text(content)

    festival_events = sum(len(contiguous_ranges(f["months"])) for f in festivals)
    print(f"Wrote {OUT_FILE.name}: {festival_events} festival events from {len(festivals)} festivals")


if __name__ == "__main__":
    main()
