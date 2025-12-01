# publisher_x.py
# X posting is DISABLED for now (free dev plan).
# This stub just logs what would have been posted and returns True
# so the rest of the system (ledger, etc.) keeps working normally.


def post_to_x(text: str) -> bool:
    print("[X DISABLED] Would have posted to X:\n", flush=True)
    print(text, flush=True)
    print("-" * 40, flush=True)
    # Return True so main.py treats this as "success" and doesn't retry
    return True
