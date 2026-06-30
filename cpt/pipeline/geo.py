"""Small ISO-3166 alpha-2 lookup. Not exhaustive -- extend as needed."""

COUNTRY_TO_ALPHA2 = {
    "india": "IN", "in": "IN", "bharat": "IN",
    "united states": "US", "usa": "US", "us": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "germany": "DE", "deutschland": "DE",
    "france": "FR", "australia": "AU", "singapore": "SG",
    "united arab emirates": "AE", "uae": "AE",
    "netherlands": "NL", "ireland": "IE", "japan": "JP",
    "china": "CN", "brazil": "BR", "mexico": "MX",
}

# Country calling code -> alpha-2, used for phone-based region inference.
CALLING_CODE_TO_ALPHA2 = {
    "1": "US", "44": "GB", "91": "IN", "61": "AU", "49": "DE",
    "33": "FR", "971": "AE", "65": "SG", "31": "NL", "353": "IE",
    "81": "JP", "86": "CN", "55": "BR", "52": "MX",
}


def country_to_alpha2(raw: str):
    if not raw:
        return None
    key = raw.strip().lower()
    if len(key) == 2:
        return key.upper()
    return COUNTRY_TO_ALPHA2.get(key)
