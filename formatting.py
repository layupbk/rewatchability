from datetime import datetime

def format_date_for_post(date_obj: datetime) -> str:
    """
    Legacy helper kept for backwards compatibility.
    Input: datetime object
    Output: 'M/D/YY' (no leading zeros)
    """
    return date_obj.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")

def to_weekday_mm_d_yy(date_iso: str) -> str:
    """
    New helper for posts/captions.
    Input: 'YYYY-MM-DD'
    Output: 'Tue · 11/4/25' (weekday abbreviated; no leading zeros)
    """
    d = datetime.strptime(date_iso, "%Y-%m-%d")
    # Example pattern: 'Tue · 11/04/25', then strip leading zeros on month/day.
    pretty = d.strftime("%a · %m/%d/%y")
    # Remove leading zeros from month/day while leaving the weekday alone.
    # First replace '/0X' -> '/X', then remove a possible leading '0' if month started the string (it doesn't here).
    pretty = pretty.replace("/0", "/")
    return pretty
