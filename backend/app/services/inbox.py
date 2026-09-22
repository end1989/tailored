"""The web-mail inbox for a person's contact email.

Only providers that can be known from the domain alone get a link. A custom
domain (Google Workspace included) could be hosted anywhere, so it gets none.
Only the Gmail form selects an account; the others open whichever account is
signed in on that site.
"""
from __future__ import annotations

from urllib.parse import quote

_GMAIL = ("gmail.com", "googlemail.com")
_ICLOUD = ("icloud.com", "me.com", "mac.com")
_OUTLOOK = ("outlook.com", "hotmail.com", "live.com", "msn.com")


def inbox_url(email: str | None) -> str | None:
    """The inbox URL for this address, or None when the provider is unknown."""
    if email is None:
        return None
    address = email.strip()
    if "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].lower()
    if domain in _GMAIL:
        return "https://mail.google.com/mail/?authuser=" + quote(address, safe="@")
    if domain in _ICLOUD:
        return "https://www.icloud.com/mail"
    if domain in _OUTLOOK:
        return "https://outlook.live.com/mail/"
    return None
