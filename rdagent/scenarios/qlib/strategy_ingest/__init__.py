"""Strategy ingest: paper PDF → StrategySpec."""

from rdagent.scenarios.qlib.strategy_ingest.method_extractor import (
    extract_strategy_from_report,
    persist_extracted_strategy,
)
from rdagent.scenarios.qlib.strategy_ingest.factor_matcher import (
    apply_factor_match,
    match_strategy_factors,
    persist_factor_match,
)
from rdagent.scenarios.qlib.strategy_ingest.method_mapper import ingest_report_to_spec, map_extracted_to_spec

__all__ = [
    "extract_strategy_from_report",
    "persist_extracted_strategy",
    "map_extracted_to_spec",
    "ingest_report_to_spec",
    "match_strategy_factors",
    "apply_factor_match",
    "persist_factor_match",
]
