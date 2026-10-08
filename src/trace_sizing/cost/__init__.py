"""AWS cost estimation, as a pipeline stage.

    from trace_sizing.cost import load_usage, PriceBook, Terms, estimate

    usage  = load_usage("build/report.json")       # from trace-sizing --format json
    usage  = usage.with_vm_overrides([{"name": "portal", "instance_type": "m7g.2xlarge"}])
    prices = PriceBook.for_region("eu-west-1").override(glue_dpu_hour=0.308)
    result = estimate(usage, prices, Terms(vat=0.23, budget_eur=20_000))
    result.save("build/cost.json")

Usage (quantities), PriceBook (AWS unit rates) and Terms (exchange rate,
discount, VAT, budget, fixed monthly items) are independent inputs.
"""

from .config import CostConfig, load as load_config
from .estimate import CostEstimate, CostLine, FixedItem, Terms, estimate
from .prices import PRICE_BOOK, PriceBook
from .usage import SCHEMA, Usage, VMUsage, load_usage, usage_from_sizing

__all__ = [
    "CostConfig", "CostEstimate", "CostLine", "FixedItem", "PRICE_BOOK", "PriceBook", "SCHEMA",
    "Terms", "Usage", "VMUsage", "estimate", "load_config", "load_usage", "usage_from_sizing",
]
