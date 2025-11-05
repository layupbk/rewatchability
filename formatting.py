def format_date_for_post(date_obj):
    return date_obj.strftime("%m/%d/%y").lstrip("0").replace("/0", "/")
