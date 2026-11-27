"""Strict SZSE PCF field decoder. Descriptive only: no order authority."""
import re
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

NS = "{http://ts.szse.cn/Fund}"
CAPS = (
    "CreationLimit", "RedemptionLimit", "CreationLimitPerUser", "RedemptionLimitPerUser",
    "NetCreationLimit", "NetRedemptionLimit", "NetCreationLimitPerUser", "NetRedemptionLimitPerUser",
)


def parse_szse_pcf(raw: bytes, *, symbol: str, session: date) -> dict:
    if not 0 < len(raw) <= 1024 * 1024 or not re.fullmatch(r"\d{6}", symbol):
        raise ValueError("invalid size or identity")
    # XML declaration may specify UTF-8; never allow DTD/entity expansion.
    body = raw.decode("utf-8-sig")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", body, re.I):
        raise ValueError("DTD/entities forbidden")
    root = ET.fromstring(body)
    if root.tag != NS + "PCFFile":
        raise ValueError("unexpected PCF root: " + root.tag[:120])

    def field(name, required=True):
        nodes = root.findall(NS + name)
        if len(nodes) > 1 or (required and not nodes):
            raise ValueError("missing or duplicate field: " + name)
        if not nodes:
            return None
        node = nodes[0]
        if len(node) or not node.text or not node.text.strip():
            raise ValueError("invalid scalar: " + name)
        return node.text.strip()

    def day(name):
        value = field(name)
        if not re.fullmatch(r"[0-9]{8}", value):
            raise ValueError("invalid date: " + name)
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))

    def number(name, integer=False, optional=False, positive=False):
        value = field(name, not optional)
        if value is None:
            return None
        pattern = r"[0-9]+(?:\.[0-9]+)?"
        if len(value) > 32 or not re.fullmatch(pattern, value):
            raise ValueError("invalid number: " + name + " / " + repr(value[:32]))
        result = Decimal(value)
        if integer and result != result.to_integral_value():
            raise ValueError("fractional share count: " + name)
        if integer:
            result = int(result)
        if positive and result <= 0:
            raise ValueError("nonpositive: " + name)
        return result if integer else str(result)

    def yn(name):
        value = field(name)
        if value not in ("Y", "N"):
            raise ValueError("invalid flag: " + name)
        return value == "Y"

    if field("SecurityID") != symbol or field("SecurityIDSource") != "102":
        raise ValueError("security identity mismatch")
    if day("TradingDay") != session:
        raise ValueError("session mismatch")
    ref = day("PreTradingDay")
    if ref >= session:
        raise ValueError("reference date not before session")
    caps = {name: number(name, integer=True, optional=True) for name in CAPS}
    return {
        "symbol": symbol,
        "session": session.isoformat(),
        "nav_reference_day": ref.isoformat(),
        "nav_per_unit": number("NAV", positive=True),
        "nav_per_creation_unit": number("NAVperCU", positive=True),
        "creation_unit": number("CreationRedemptionUnit", integer=True, positive=True),
        "creation_allowed_reported": yn("Creation"),
        "redemption_allowed_reported": yn("Redemption"),
        "iopv_publish_reported": yn("Publish"),
        "caps_shares_raw": caps,
        "zero_cap_semantics": "NO_NUMERIC_CAP_REPORTED_FOR_FIELD_NOT_ACCEPTANCE",
        "actual_order_acceptance_verified": False,
        "secondary_trading_status_inferred": False,
        "historical_first_availability_verified": False,
        "decision_authority": False,
    }
