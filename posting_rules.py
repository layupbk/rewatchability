import re

# ------------- helpers -------------

def sport_emoji(sport: str) -> str:
    s = sport.upper()
    if s in ("NBA", "NCAAM"):
        return "🏀"
    if s in ("NFL", "NCAAF"):
        return "🏈"
    if s == "MLB":
        return "⚾"
    return ""

def clean_hashtag_text(text: str) -> str:
    """Keep letters/numbers only; no spaces/punct; title-casing not required for hashtags."""
    return re.sub(r"[^A-Za-z0-9]", "", text.strip())

def league_hashtag(sport: str) -> str:
    """Force college names: NCAAF, NCAAM."""
    mapping = {
        "NBA": "NBA",
        "NFL": "NFL",
        "MLB": "MLB",
        "NCAAF": "NCAAF",
        "NCAAM": "NCAAM",
    }
    tag = mapping.get(sport.upper(), sport.upper())
    return f"#{tag}"

def event_hashtag(event_name: str | None) -> str | None:
    """
    Convert an event/tournament name to a hashtag if provided.
    Examples:
      'Champions Classic' -> '#ChampionsClassic'
      'Maui Invitational' -> '#MauiInvitational'
      'Red River Rivalry' -> '#RedRiverRivalry'
    """
    if not event_name:
        return None
    cleaned = clean_hashtag_text(event_name)
    return f"#{cleaned}" if cleaned else None

# ------------- public formatting -------------

def format_post(game, score, vibe, date, sport, neutral_site=False, network=None):
    """
    Tweet text (no hashtags).
    game: {"away": "...", "home": "..."}
    date: 'MM/D/YY'
    Note: we still show network (if national) in the headline text for human context,
    but we never hashtag the network anymore.
    """
    emoji = sport_emoji(sport)
    sep = "vs." if neutral_site else "@"

    line1 = f"{emoji} {game['away']} {sep} {game['home']}"
    if network:
        line1 += f" — {network}"
    line1 += " — FINAL"

    return f"""{line1}
Rewatchability Score™: {score}
{vibe}
{date}
"""

def format_video_caption(game, score, vibe, date, sport,
                         neutral_site=False, network=None,
                         is_national=True, event_name: str | None = None):
    """
    Video caption (same as tweet, plus hashtags):
    Base 4 tags:
      #RewatchabilityScore #<League> #<AwayTeam> #<HomeTeam>
    If an event name exists (from ESPN), add it as the 5th tag:
      #<EventName>
    We DO NOT add broadcaster/network hashtags anymore.
    """
    text = format_post(game, score, vibe, date, sport, neutral_site, network)

    tags = [
        "#RewatchabilityScore",
        league_hashtag(sport),
        f"#{clean_hashtag_text(game['away'])}",
        f"#{clean_hashtag_text(game['home'])}",
    ]

    evt = event_hashtag(event_name)
    if evt:
        tags.append(evt)

    return text.rstrip() + "\n\n" + " ".join(tags)
