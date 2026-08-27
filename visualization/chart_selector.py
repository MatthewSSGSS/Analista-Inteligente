def choose(schema):
    charts = []
    semantic = schema.get("semantic", {})
    dates = semantic.get("date") or schema.get("dates", [])
    metrics = semantic.get("metrics") or schema.get("metrics", [])
    dims = semantic.get("dimensions") or schema.get("categorical", [])
    geo = semantic.get("geography") or schema.get("geography", [])
    if dates and metrics:
        charts.append("time_series")
    if dims and metrics:
        charts.append("ranking")
        charts.append("donut")
    if len(metrics) >= 2:
        charts.append("scatter")
    if metrics:
        charts.append("histogram")
    if len(metrics) >= 3:
        charts.append("correlation")
    if geo:
        charts.append("geo")
    return list(dict.fromkeys(charts))
