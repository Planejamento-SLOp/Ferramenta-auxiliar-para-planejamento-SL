from collections.abc import Mapping

import requests


def post_mission_event(enabled: bool, url: str | None, payload: Mapping[str, str]) -> bool:
    if not enabled:
        return False
    if not url:
        raise ValueError("Webhook URL is required when webhook logging is enabled.")

    response = requests.post(url, data=dict(payload), timeout=10)
    response.raise_for_status()
    return True
