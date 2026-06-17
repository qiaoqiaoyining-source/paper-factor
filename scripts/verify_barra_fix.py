#!/usr/bin/env python3
"""Verify Barra exposure overlap for one literature factor."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from rdagent.scenarios.qlib.developer.barra_analysis import analyze_factor_barra_full


def main() -> int:
    factor_path = Path(
        "/mnt/remote_e/paper_factors/文献因子/AI研究系列之一_涨停板背后的Alpha_"
        "首板回调策略的系统化探索与实证/close_position.parquet"
    )
    if not factor_path.exists():
        print(f"SKIP: factor not found: {factor_path}")
        return 0

    df = pd.read_parquet(factor_path)
    result = analyze_factor_barra_full(df, model="trading")
    exp = result.get("exposure_diagnostics") or {}
    print("exposure status:", exp.get("status"))
    print("regression_days:", exp.get("regression_days"))
    print("dominant:", exp.get("dominant_style_loadings"))
    if exp.get("status") != "ok":
        print(json.dumps(exp, ensure_ascii=False, indent=2))
        return 1
    print("OK:", (result.get("summary_markdown") or "")[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
