def vibe_tag_from_score(score: int) -> str:
    # One short tag by tier. We can refine later.
    if score >= 90:
        return "Cinematic"
    elif score >= 80:
        return "Punchy"
    elif score >= 70:
        return "Steady"
    elif score >= 60:
        return "Flat"
    elif score >= 50:
        return "Routine"
    else:
        return "Lifeless"
