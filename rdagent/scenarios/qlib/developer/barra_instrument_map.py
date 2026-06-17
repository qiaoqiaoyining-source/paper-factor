"""Map factor instrument codes to Barra secID (000001.XSHE / 600000.XSHG)."""

from __future__ import annotations

import re


def _suffix_to_barra_secid(code: str, suffix: str) -> str:
    suffix = suffix.upper()
    if suffix in {"SZ", "XSHE"}:
        return f"{code}.XSHE"
    if suffix in {"SH", "XSHG"}:
        return f"{code}.XSHG"
    if suffix in {"BJ"}:
        return f"{code}.BJ"
    return f"{code}.{suffix}"


def normalize_trade_date(raw: object) -> str:
    """Normalize Barra / factor dates to YYYYMMDD strings for set membership tests."""
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if len(text) == 8 and text.isdigit():
        return text
    try:
        ts = int(float(text))
        if 19000101 <= ts <= 21001231:
            return str(ts)
    except (TypeError, ValueError):
        pass
    try:
        import pandas as pd

        parsed = pd.Timestamp(text)
        if pd.notna(parsed):
            return parsed.strftime("%Y%m%d")
    except Exception:  # noqa: BLE001
        pass
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 8:
        return digits[:8]
    return text


def factor_instrument_to_barra_secid(instrument: str) -> str:
    """
    Convert factor MultiIndex instrument codes to Barra secID.

    Handles:
      - Already suffixed: 000001.SZ, 600000.SH, 000001.XSHE
      - Unpadded numeric codes from int-cast ts_code: 1 -> 000001.XSHE, 600519 -> 600519.XSHG
    """
    text = str(instrument).strip().upper()
    if not text:
        return text
    if "." in text:
        code, suffix = text.rsplit(".", 1)
        return _suffix_to_barra_secid(code, suffix)

    digits = re.sub(r"\D", "", text)
    if not digits:
        return text
    digits = digits.zfill(6)
    if digits.startswith(("60", "68", "90")):
        return f"{digits}.XSHG"
    if digits.startswith(("00", "30", "20", "43", "83", "87", "92")):
        return f"{digits}.XSHE"
    if digits.startswith(("8", "4")):
        return f"{digits}.BJ"
    return f"{digits}.XSHE"


def map_instruments_to_barra_secids(instruments) -> dict[str, str]:
    """Return {original_instrument_str: barra_secid} for a factor instrument index level."""
    out: dict[str, str] = {}
    for inst in instruments:
        key = str(inst)
        out[key] = factor_instrument_to_barra_secid(key)
    return out
