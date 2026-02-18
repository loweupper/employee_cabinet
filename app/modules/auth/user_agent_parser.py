def parse_user_agent(ua: str) -> dict:
    """
    Определяет устройство и браузер по User-Agent.
    Возвращает dict: {"device": "...", "browser": "..."}
    """

    if not ua:
        return {"device": "Неизвестно", "browser": "Неизвестно"}

    ua_lower = ua.lower()

    # -------------------------
    # Определение устройства
    # -------------------------
    if "iphone" in ua_lower:
        device = "iPhone"
    elif "ipad" in ua_lower:
        device = "iPad"
    elif "android" in ua_lower:
        device = "Android"
    elif "windows" in ua_lower:
        device = "Windows"
    elif "mac os" in ua_lower or "macintosh" in ua_lower:
        device = "Mac"
    elif "linux" in ua_lower:
        device = "Linux"
    else:
        device = "Неизвестно"

    # -------------------------
    # Определение браузера
    # -------------------------
    if "chrome" in ua_lower and "edg" not in ua_lower:
        browser = "Chrome"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        browser = "Safari"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "edg" in ua_lower:
        browser = "Edge"
    elif "opera" in ua_lower or "opr" in ua_lower:
        browser = "Opera"
    else:
        browser = "Неизвестно"

    return {"device": device, "browser": browser}
