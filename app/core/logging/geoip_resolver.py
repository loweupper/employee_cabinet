import httpx

IP_API_URL = "http://ip-api.com/json/{ip}?fields=66846719"


async def resolve_geo(ip: str) -> dict:
    """
    Возвращает:
    - geo_country
    - geo_region
    - geo_city
    - geo_asn
    - geo_org
    - geo_isp
    - geo_hosting
    - geo_proxy
    - geo_mobile
    """

    result = {
        "geo_country": None,
        "geo_region": None,
        "geo_city": None,
        "geo_asn": None,
        "geo_org": None,
        "geo_isp": None,
        "geo_hosting": None,
        "geo_proxy": None,
        "geo_mobile": None,
    }

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(IP_API_URL.format(ip=ip))
            data = r.json()

        if data.get("status") != "success":
            return result

        result["geo_country"] = data.get("country")
        result["geo_region"] = data.get("regionName")
        result["geo_city"] = data.get("city")
        result["geo_asn"] = data.get("as")
        result["geo_org"] = data.get("org")
        result["geo_isp"] = data.get("isp")
        result["geo_hosting"] = data.get("hosting")
        result["geo_proxy"] = data.get("proxy")
        result["geo_mobile"] = data.get("mobile")

    except Exception:
        pass

    return result
