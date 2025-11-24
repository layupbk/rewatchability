import re

# ------------- helpers -------------

def sport_emoji(sport: str) -> str:
    """
    Emoji used in headline line for posts/captions.
    If the sport is unrecognized, return no emoji.
    """
    s = sport.upper()
    if s in ("NBA", "NCAAM", "NCAAB", "CBB"):
        return "🏀"
    if s in ("NFL", "NCAAF", "CFB"):
        return "🏈"
    if s == "MLB":
        return "⚾"
    return ""


def clean_hashtag_text(text: str) -> str:
    """Keep letters/numbers only; no spaces/punct; title-casing not required for hashtags."""
    return re.sub(r"[^A-Za-z0-9]", "", text.strip())


def league_hashtag(sport: str) -> str:
    """
    Normalize multiple internal keys to a small, consistent set of public tags:
      - NBA         -> #NBA
      - NFL         -> #NFL
      - MLB         -> #MLB
      - NCAAF / CFB -> #NCAAF
      - NCAAM / NCAAB / CBB -> #NCAAM  (men's college basketball)
    """
    s = sport.upper()
    mapping = {
        "NBA": "NBA",
        "NFL": "NFL",
        "MLB": "MLB",
        "NCAAF": "NCAAF",
        "CFB": "NCAAF",
        "NCAAM": "NCAAM",
        "NCAAB": "NCAAM",
        "CBB": "NCAAM",
    }
    tag = mapping.get(s, s)
    return f"#{tag}"


# ------------- public formatting -------------

def format_post(
    game,
    score: int,
    vibe: str,
    date: str,
    sport: str,
    neutral_site: bool = False,
    network: str | None = None,
) -> str:
    """
    Core text post format, used for:
      - X (Twitter)
      - Threads
      - Any other plain-text contexts

    `date` is already formatted (e.g., 'Tue · 11/4/25').

    Uses SHORT team names everywhere if available:
      game['away_short'] / game['home_short'] preferred over game['away'] / game['home'].
    """
    emoji = sport_emoji(sport)
    away_name = (game.get("away_short") or game.get("away") or "").strip()
    home_name = (game.get("home_short") or game.get("home") or "").strip()

    sep = "vs." if neutral_site else "@"

    line1 = f"{emoji} {away_name} {sep} {home_name}".strip()
    if network:
        line1 += f" — {network}"
    line1 += " — FINAL"

    return f"""{line1}
Rewatchability Score™: {score}
{vibe}
{date}
"""


def format_video_caption(
    game,
    score: int,
    vibe: str,
    date: str,
    sport: str,
    neutral_site: bool = False,
    network: str | None = None,
) -> str:
    """
    Short-form video caption format, used for:
      - TikTok
      - Instagram Reels
      - Facebook Reels
      - YouTube Shorts
      - etc.

    Structure:
      - Same core text as format_post(...)
      - Plus hashtags:

        1) #RewatchabilityScore
        2) #<League>      (NBA/NFL/MLB/NCAAF/NCAAM)
        3) #<AwayShort>   (short team name, letters/numbers only)
        4) #<HomeShort>   (short team name, letters/numbers only)
    """
    text = format_post(game, score, vibe, date, sport, neutral_site, network)

    away_name = (game.get("away_short") or game.get("away") or "").strip()
    home_name = (game.get("home_short") or game.get("home") or "").strip()

    tags = [
        "#RewatchabilityScore",
        league_hashtag(sport),
        f"#{clean_hashtag_text(away_name)}",
        f"#{clean_hashtag_text(home_name)}",
    ]

    return text.rstrip() + "\n\n" + " ".join(tags)
