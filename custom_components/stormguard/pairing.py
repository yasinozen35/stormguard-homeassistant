"""Pairing link and the URLs the app needs.

The app understands
``stormguardweather://home-assistant?url=<base>&id=<webhook_id>[&remote=<https base>]``
and validates it with the same rules as manual entry
(``configFromPairingParams`` in the app): ``url`` may be plain ``http`` only
on a home-network host, ``remote`` must be ``https``. These rules are mirrored
here so the config flow can warn *before* the user taps a link the app will
refuse.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import secrets
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url
from yarl import URL

from .const import APP_PAIRING_URL, WEBHOOK_ID_PATTERN, WEBHOOK_ID_PREFIX

# Same list as LOCAL_SUFFIXES in the app.
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain", ".ts.net")
_PRIVATE_V4 = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "127.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
    )
)
_PRIVATE_V6 = tuple(ipaddress.ip_network(n) for n in ("::1/128", "fe80::/10", "fc00::/7"))
# The app forbids these anywhere in a base URL.
_FORBIDDEN = set(" \t\r\n@?#\\")


def generate_webhook_id() -> str:
    """Return a fresh secret webhook id (``stormguard_`` + 32 url-safe chars)."""
    webhook_id = WEBHOOK_ID_PREFIX + secrets.token_urlsafe(24)
    assert WEBHOOK_ID_PATTERN.fullmatch(webhook_id)
    return webhook_id


def normalize_base_url(url: str) -> str:
    """Scheme + host + port only: no path, no trailing slash."""
    return str(URL(url.strip()).origin()).rstrip("/")


def is_private_host(host: str) -> bool:
    """Mirror of the app's ``isPrivateNetworkHost``."""
    host = host.lower().strip("[]")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host:
            return bool(host)
        return host.endswith(_LOCAL_SUFFIXES)
    networks = _PRIVATE_V4 if address.version == 4 else _PRIVATE_V6
    return any(address in network for network in networks)


def app_accepts_base_url(url: str) -> bool:
    """Would the app accept this as the (home network) server address?"""
    if any(ch in _FORBIDDEN or ord(ch) < 0x20 for ch in url):
        return False
    parsed = URL(url)
    if parsed.scheme not in ("http", "https") or not parsed.host:
        return False
    return parsed.scheme == "https" or is_private_host(parsed.host)


def app_accepts_remote_url(url: str) -> bool:
    """Would the app accept this as the remote (outside the home) address?"""
    return URL(url).scheme == "https" and app_accepts_base_url(url)


def build_pairing_link(base_url: str, webhook_id: str, remote_url: str | None = None) -> str:
    """Return the deep link the StormGuard app opens."""
    link = f"{APP_PAIRING_URL}?url={quote(base_url, safe='')}&id={quote(webhook_id, safe='')}"
    if remote_url:
        link += f"&remote={quote(remote_url, safe='')}"
    return link


@dataclass(frozen=True, slots=True)
class PairingInfo:
    """What the config flow shows on its pairing step."""

    base_url: str | None
    remote_url: str | None
    link: str | None
    problem: str | None  # translation key of a warning, or None


def async_pairing_info(hass: HomeAssistant, webhook_id: str, allow_remote: bool) -> PairingInfo:
    """Compute the home and (optionally) remote base URLs and the deep link."""
    base_url: str | None
    try:
        base_url = normalize_base_url(
            get_url(hass, allow_internal=True, allow_external=False, allow_cloud=False)
        )
    except NoURLAvailableError:
        base_url = None

    remote_url: str | None = None
    if allow_remote:
        try:
            remote_url = normalize_base_url(
                get_url(
                    hass,
                    allow_internal=False,
                    allow_ip=False,
                    require_ssl=True,
                    require_standard_port=False,
                    allow_cloud=True,
                    prefer_cloud=False,
                )
            )
        except NoURLAvailableError:
            remote_url = None
        if remote_url is not None and not app_accepts_remote_url(remote_url):
            remote_url = None

    problem: str | None = None
    if base_url is None:
        problem = "no_local_url"
    elif not app_accepts_base_url(base_url):
        problem = "insecure_local_url"
    elif allow_remote and remote_url is None:
        problem = "no_remote_url"

    link = None
    if base_url is not None and problem != "insecure_local_url":
        link = build_pairing_link(base_url, webhook_id, remote_url)
    elif remote_url is not None:
        # Home address unusable but a valid https one exists: still pairable.
        link = build_pairing_link(remote_url, webhook_id, remote_url)

    return PairingInfo(base_url=base_url, remote_url=remote_url, link=link, problem=problem)
