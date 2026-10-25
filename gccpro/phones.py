"""Phone numbers: normalisation to E.164, French display, WhatsApp links. Pure functions.

Numbers are stored as E.164 (``+33612345678``). Residents type them however
they like ("06 12 34 56 78", "+33 6 12...", "0033612..."); national French
numbers are assumed when there is no country code.
"""

import re
from urllib.parse import quote


class PhoneError(ValueError):
    """An input that cannot be a phone number; ``str()`` is user-facing (French)."""


def normalize(raw: str) -> str:
    """Return ``raw`` as an E.164 number, or raise :class:`PhoneError`."""
    number = re.sub(r"[\s.\-()/]", "", raw or "")
    if number.startswith("00"):
        number = "+" + number[2:]
    if re.fullmatch(r"0[1-9]\d{8}", number):        # French national format
        number = "+33" + number[1:]
    if re.fullmatch(r"\+330[1-9]\d{8}", number):    # "+33 06..." typed with the 0
        number = "+33" + number[4:]
    if not re.fullmatch(r"\+[1-9]\d{7,14}", number):
        raise PhoneError("Numéro de téléphone invalide.")
    return number


def display(e164: str | None) -> str:
    """Format a stored number for display: "06 12 34 56 78" for French numbers."""
    if not e164:
        return ""
    if re.fullmatch(r"\+33[1-9]\d{8}", e164):
        national = "0" + e164[3:]
        return " ".join(national[i:i + 2] for i in range(0, 10, 2))
    return e164


def whatsapp_url(e164: str, message: str) -> str:
    """Return a link opening a WhatsApp chat with ``e164``, ``message`` pre-filled."""
    return f"https://wa.me/{e164.lstrip('+')}?text={quote(message)}"
