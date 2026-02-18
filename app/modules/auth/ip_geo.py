import httpx
import logging
from functools import lru_cache

logger = logging.getLogger("app")

# Кэшируем 500 IP → чтобы не спамить API
@lru_cache(maxsize=500)
def get_ip_geo(ip: str) -> dict:
    """
    Получает геолокацию по IP через бесплатный API ipapi.co
    """
    if not ip or ip == "127.0.0.1" or ip.startswith("192.168.") or ip.startswith("10."):
        return {"city": "Локальная сеть", "country": ""}

    try:
        url = f"https://ipapi.co/{ip}/json/"
        resp = httpx.get(url, timeout=2.0)

        if resp.status_code != 200:
            return {"city": None, "country": None}

        data = resp.json()

        return {
            "city": data.get("city"),
            "country": data.get("country_name"),
        }

    except Exception as e:
        logger.error(f"IP geo lookup failed for {ip}: {e}")
        return {"city": None, "country": None}
