# inpredictable.py
# Scraper for inpredictable.com's PreCap "Excitement" tables.
#
# Supports:
#   - NBA  -> https://stats.inpredictable.com/nba/preCap.php
#   - WNBA -> https://stats.inpredictable.com/wnba/preCap.php
#
# Public API:
#   fetch_excitement_map("NBA")  -> dict[(away_abbrev, home_abbrev), excitement_float]
#   fetch_excitement_map("WNBA") -> same, for WNBA

from __future__ import annotations

import re
import time
from typing import Dict, Tuple, Optional

import requests

NBA_PRECAP_URL = "https://stats.inpredictable.com/nba/preCap.php"
WNBA_PRECAP_URL = "https://stats.inpredictable.com/wnba/preCap.php"

PRECAP_URLS: Dict[str, str] = {
    "NBA": NBA_PRECAP_URL,
    "WNBA": WNBA_PRECAP_URL,
}

# Simple in-process cache:
#   league -> {"ts": float, "mapping": dict[(away,home)->float]}
_CACHE: Dict[str, Dict[str, object]] = {}
CACHE_TTL_SECONDS = 120.0  # reuse for a couple of minutes


def _log(msg: str) -> None:
    print(f"[INPRED] {msg}", flush=True)


def _fetch_precap_html(url: str) -> Optional[str]:
    """Fetch raw HTML from the PreCap page."""
    try:
        resp = requests.get(url, timeout=10)
    except Exception as ex:
        _log(f"error fetching {url}: {ex}")
        return None

    if resp.status_code != 200:
        _log(f"GET {url} -> {resp.status_code}")
        return None

    resp.encoding = "utf-8"
    return resp.text


def _html_to_text(html: str) -> str:
    """
    Very simple HTML → text converter:
    - Turn <br> into newlines
    - Drop all tags
    - Normalize spaces
    """
    # 1) <br> -> newline so each row can live on its own line
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)

    # 2) Strip any remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)

    # 3) Normalize non-breaking spaces, collapse extra spaces
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)

    return text


def _parse_precap_table(html: str) -> Dict[Tuple[str, str], float]:
    """
    Return {(away_abbr, home_abbr): excitement_float} for games.

    Strategy:
      - Convert HTML to plain text.
      - Split into lines.
      - For any line that contains '@' and 'Finished', extract:
            AWAY @ HOME   (3-letter codes)
            Finished X.Y  (Excitement)
    """
    rows: Dict[Tuple[str, str], float] = {}

    if not html:
        return rows

    text = _html_to_text(html)
    _log(f"PreCap text length = {len(text)} chars")

    lines = text.splitlines()

    # patterns applied per-line
    code_pattern = re.compile(r"([A-Za-z]{3})\s*@\s*([A-Za-z]{3})")
    excite_pattern = re.compile(r"Finished\s+(\d+(\.\d+)?)", re.IGNORECASE)

    count_finished = 0
    debug_shown = 0

    for raw_line in lines:
        line = raw_line.strip()
        if "@" not in line:
            continue
        if "Finished" not in line and "finished" not in line:
            continue

        m_codes = code_pattern.search(line)
        m_ei = excite_pattern.search(line)
        if not m_codes or not m_ei:
            continue

        away = m_codes.group(1).upper()
        home = m_codes.group(2).upper()
        excite_str = m_ei.group(1)

        try:
            excite_val = float(excite_str)
        except ValueError:
            continue

        rows[(away, home)] = excite_val
        count_finished += 1

        # Log a few sample lines so we can see what's being parsed
        if debug_shown < 10:
            _log(f"ROW parsed: {away} @ {home} -> Excitement {excite_val} (line={line})")
            debug_shown += 1

    _log(f"parsed {count_finished} finished games from PreCap table")
    return rows


def _get_cached_mapping(league_up: str) -> Optional[Dict[Tuple[str, str], float]]:
    """Read from in-process cache if still fresh."""
    entry = _CACHE.get(league_up)
    if not entry:
        return None

    ts = entry.get("ts")
    mapping = entry.get("mapping")
    if not isinstance(mapping, dict) or not isinstance(ts, (int, float)):
        return None

    if (time.time() - float(ts)) > CACHE_TTL_SECONDS:
        return None

    return mapping  # still fresh


def _set_cached_mapping(league_up: str, mapping: Dict[Tuple[str, str], float]) -> None:
    _CACHE[league_up] = {"ts": time.time(), "mapping": mapping}


def fetch_excitement_map(league: str) -> Dict[Tuple[str, str], float]:
    """
    Return a dict mapping (away_abbr, home_abbr) -> inpredictable Excitement (raw).

    Behavior:
      - Try to fetch and parse the current PreCap page.
      - If it yields a non-empty mapping, cache it and return.
      - If it fails or parses to empty, fall back to a recent cached mapping
        (if available) instead of returning {}.
    """
    league_up = (league or "").upper()
    if league_up not in PRECAP_URLS:
        raise ValueError(f"Unsupported league for inpredictable PreCap: {league!r}")

    url = PRECAP_URLS[league_up]

    try:
        html = _fetch_precap_html(url)
        if html:
            mapping = _parse_precap_table(html)
            if mapping:
                _set_cached_mapping(league_up, mapping)
                _log(f"parsed {len(mapping)} finished games from PreCap for {league_up}")
                return mapping
            else:
                _log(f"parsed 0 finished games from PreCap for {league_up}")
        else:
            _log(f"no HTML from PreCap for {league_up}")
    except Exception as ex:
        _log(f"unexpected error in fetch_excitement_map({league_up}): {ex}")

    # Fallback: use cached mapping if available
    cached = _get_cached_mapping(league_up)
    if cached:
        _log(
            f"using cached Excitement mapping for {league_up} "
            f"(len={len(cached)})"
        )
        return cached

    # Nothing available
    _log(f"no Excitement data available (live or cache) for {league_up}")
    return {}
