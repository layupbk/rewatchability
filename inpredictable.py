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
from typing import Dict, Tuple

import requests

NBA_PRECAP_URL = "https://stats.inpredictable.com/nba/preCap.php"
WNBA_PRECAP_URL = "https://stats.inpredictable.com/wnba/preCap.php"

PRECAP_URLS = {
    "NBA": NBA_PRECAP_URL,
    "WNBA": WNBA_PRECAP_URL,
}

# Parse strings like "DET @ BOS" (possibly with extra junk after them)
GAME_CELL_RE = re.compile(
    r"""
    ^\s*
    (?P<away>[A-Z]{2,4})      # away team abbreviation
    \s*@\s*
    (?P<home>[A-Z]{2,4})      # home team abbreviation
    """,
    re.VERBOSE,
)


def _fetch_precap_html(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            print(f"[INPRED] GET {url} -> {resp.status_code}", flush=True)
            return None
        resp.encoding = "utf-8"
        return resp.text
    except Exception as ex:
        print(f"[INPRED] error fetching {url}: {ex}", flush=True)
        return None


def _parse_precap_table(html: str) -> Dict[Tuple[str, str], float]:
    """
    Return {(away_abbr, home_abbr): excitement_float} for games
    where Status == "Finished".
    """
    rows: Dict[Tuple[str, str], float] = {}

    cleaned = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)

    header_match = re.search(
        r"Rank\s*Game\s*Status\s*Excitement\s*Tension",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not header_match:
        return rows

    table_text = cleaned[header_match.end() :]

    game_pattern = re.compile(
        r"""
        (?P<rank>\d+)
        \s+
        (?P<game>[A-Z]{2,4}\s*@\s*[A-Z]{2,4}[^0-9\n]*?)
        \s+
        (?P<status>Finished|In\ Progress|Scheduled)
        \s+
        (?P<excite>\d+(\.\d+)?)
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    for m in game_pattern.finditer(table_text):
        status = m.group("status").strip().lower()
        if status != "finished":
            continue

        game_cell = m.group("game")
        excite_str = m.group("excite")

        if not excite_str:
            continue

        gm = GAME_CELL_RE.search(game_cell)
        if not gm:
            continue
        away = gm.group("away").upper()
        home = gm.group("home").upper()

        try:
            excite = float(excite_str)
        except ValueError:
            continue

        rows[(away, home)] = excite

    return rows


def fetch_excitement_map(league: str) -> Dict[Tuple[str, str], float]:
    """
    Return a dict mapping (away_abbr, home_abbr) -> inpredictable Excitement (raw).
    """
    league_up = (league or "").upper()
    if league_up not in PRECAP_URLS:
        raise ValueError(f"Unsupported league for inpredictable PreCap: {league!r}")

    url = PRECAP_URLS[league_up]
    html = _fetch_precap_html(url)
    if not html:
        return {}

    mapping = _parse_precap_table(html)
    print(f"[INPRED] parsed {len(mapping)} finished games from PreCap for {league_up}", flush=True)
    return mapping
