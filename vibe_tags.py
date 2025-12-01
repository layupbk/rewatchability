# vibe_tags.py
# Simple, deterministic 1–2 word tags by score tier.
# 90s = bold/cinematic; 80s = dynamic; 70s = steady; <70 = flat/routine/lifeless.

from typing import Final

# Primary tag for each bucket (short, spoiler-safe)
PRIMARY_TAGS: Final[dict[str, str]] = {
    "99": "All-Timer",
    "95": "Classic",
    "90": "Cinematic",
    "80": "High Tempo",
    "70": "Steady",
    "60": "Flat",
    "50": "Routine",
    "40": "Lifeless",
}


def pick_vibe(score: int) -> str:
    """Return a short vibe tag for the given Rewatchability Score™."""
    # Clamp just in case
    s = max(40, min(100, int(score)))

    if s >= 99:
        return PRIMARY_TAGS["99"]
    if s >= 95:
        return PRIMARY_TAGS["95"]
    if s >= 90:
        return PRIMARY_TAGS["90"]
    if s >= 80:
        return PRIMARY_TAGS["80"]
    if s >= 70:
        return PRIMARY_TAGS["70"]
    if s >= 60:
        return PRIMARY_TAGS["60"]
    if s >= 50:
        return PRIMARY_TAGS["50"]
    return PRIMARY_TAGS["40"]


# Backwards-compat alias used in older files
vibe_tag_from_score = pick_vibe
