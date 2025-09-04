def format_number(tokens: int) -> str:
    if tokens < 1000:
        return f"{tokens}"
    elif tokens < 1000000:
        # [xxx]k
        k = tokens / 1000
        if k == int(k):
            return f"{int(k)}k"
        else:
            return f"{k:.1f}k"
    else:
        # [xxx]M[yyy]k
        m = tokens // 1000000
        remaining = (tokens % 1000000) // 1000
        if remaining == 0:
            return f"{m}M"
        else:
            return f"{m}M{remaining}k"
