from ipaddress import ip_address


def is_loopback_address(address):
    if not isinstance(address, str) or not address.strip():
        return False

    normalized_address = address.strip().casefold()
    if normalized_address == "localhost":
        return True

    try:
        return ip_address(normalized_address).is_loopback
    except ValueError:
        return False


def is_bind_address_allowed(address, allow_hosted_access=False):
    return is_loopback_address(address) or allow_hosted_access is True
