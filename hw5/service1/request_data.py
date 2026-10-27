from datetime import datetime, timezone
from ipaddress import ip_address


FORBIDDEN_COUNTRIES = {
    "north korea", "iran", "cuba", "myanmar", "iraq",
    "libya", "sudan", "zimbabwe", "syria",
    "kp", "ir", "cu", "mm", "iq", "ly", "sd", "zw", "sy",
}


def extract_request_data(headers, requested_file, run_id="manual"):
    received_at = datetime.now(timezone.utc)

    country = headers.get("X-country", "").strip()

    # INET field in PostgreSQL requires a valid IP address.
    raw_ip = headers.get("X-client-IP", "").strip()
    try:
        client_ip = str(ip_address(raw_ip))
    except ValueError:
        client_ip = None

    # Client time does not include a timezone.
    raw_time = headers.get("X-time", "").strip()
    try:
        client_time = datetime.strptime(
            raw_time, "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        client_time = None

    return {
        "country": country or None,
        "client_ip": client_ip,
        "gender": headers.get("X-gender", "").strip() or None,
        "age_group": headers.get("X-age", "").strip() or None,
        "income_group": headers.get("X-income", "").strip() or None,
        "is_banned": country.casefold() in FORBIDDEN_COUNTRIES,
        "client_time": client_time,
        "received_at": received_at,
        "requested_file": requested_file,
        "run_id": run_id,
    }