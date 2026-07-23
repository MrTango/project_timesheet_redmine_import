# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import html
import math
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from dateutil.parser import isoparse


def validate_base_url(value):
    """Return a normalized HTTP(S) URL or raise ValueError."""
    value = (value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("The Redmine base URL must be an absolute HTTP(S) URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("The Redmine base URL cannot contain a query or fragment.")
    return value


def parse_date(value, field_name="date"):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError("Invalid Redmine %s: %r" % (field_name, value))


def parse_datetime(value, field_name="datetime"):
    """Parse Redmine ISO-8601 and return a naive UTC datetime for Odoo."""
    if not value:
        return False
    try:
        parsed = isoparse(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except (TypeError, ValueError):
        raise ValueError("Invalid Redmine %s: %r" % (field_name, value))


def parse_hours(value):
    try:
        hours = float(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid Redmine hours: %r" % value)
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError("Redmine hours must be a finite number greater than zero: %r" % value)
    return hours


def integer_id(container, key, required=False):
    value = (container or {}).get(key)
    if value in (None, False, ""):
        if required:
            raise ValueError("Missing Redmine %s" % key)
        return False
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid Redmine %s: %r" % (key, value))


def normalize_email(value):
    return (value or "").strip().casefold()


def text_to_html(value):
    """Safely represent remote plain text in Odoo's HTML task description."""
    return "<p>%s</p>" % html.escape(value or "").replace("\n", "<br/>")


def safe_message(error, api_key=None, limit=1000):
    message = str(error) or error.__class__.__name__
    if api_key:
        message = message.replace(api_key, "***")
    return message[:limit]
