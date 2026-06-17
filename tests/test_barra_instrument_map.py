from __future__ import annotations

from rdagent.scenarios.qlib.developer.barra_instrument_map import (
    factor_instrument_to_barra_secid,
    normalize_trade_date,
)


def test_normalize_trade_date_int_and_float():
    assert normalize_trade_date(20240315) == "20240315"
    assert normalize_trade_date("20240315.0") == "20240315"
    assert normalize_trade_date("2024-03-15") == "20240315"


def test_factor_instrument_to_barra_secid():
    assert factor_instrument_to_barra_secid("1") == "000001.XSHE"
    assert factor_instrument_to_barra_secid("600519") == "600519.XSHG"
    assert factor_instrument_to_barra_secid("000001.SZ") == "000001.XSHE"
    assert factor_instrument_to_barra_secid("600000.SH") == "600000.XSHG"
    assert factor_instrument_to_barra_secid("000001.XSHE") == "000001.XSHE"
