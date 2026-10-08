"""trace-cost: price a usage file or trace-sizing JSON report.

  trace-sizing config/trace_workload.toml --format json -o build/report.json
  trace-cost build/report.json -o build/cost.html
  trace-cost build/report.json --vm portal=m7g.2xlarge --vm data-plane.ebs_gb=200 -o build/cost-bigger.html
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from typing import Any

from . import config as cost_config
from .estimate import estimate
from ..htmlkit import parse_links
from .render import cost_page_html, cost_page_md
from .usage import load_usage

DEFAULT_CONFIG = "config/cost.toml"
_EXT = {".md": "md", ".markdown": "md", ".html": "html", ".htm": "html", ".json": "json"}
_VM_FIELDS = {"instance_type": str, "ebs_gb": float, "hours_per_month": float}


def parse_vm_override(spec: str) -> dict[str, Any]:
    """NAME=TYPE sets the instance type (TYPE "none" removes the VM);
    NAME.FIELD=VALUE sets ebs_gb, hours_per_month or instance_type."""
    key, sep, value = spec.partition("=")
    if not sep or not key or not value:
        raise SystemExit(f"--vm expects NAME=TYPE or NAME.FIELD=VALUE, got {spec!r}")
    name, dot, fld = key.partition(".")
    if not dot:
        if value.lower() == "none":
            return {"name": name, "remove": True}
        return {"name": name, "instance_type": value}
    if fld not in _VM_FIELDS:
        raise SystemExit(f"--vm {spec!r}: field must be one of {', '.join(_VM_FIELDS)}")
    try:
        return {"name": name, fld: _VM_FIELDS[fld](value)}
    except ValueError:
        raise SystemExit(f"--vm {spec!r}: {fld} must be a number")


def parse_price_override(spec: str) -> tuple[str, float]:
    key, sep, value = spec.partition("=")
    try:
        return key, float(value)
    except ValueError:
        raise SystemExit(f"--price expects KEY=NUMBER, got {spec!r}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace-cost", description="AWS cost estimate from a trace-sizing report or usage file")
    ap.add_argument("input", help="trace-sizing JSON report (trace-sizing ... --format json) or usage .json/.toml")
    ap.add_argument("--config", help=f"cost config (default: {DEFAULT_CONFIG} if it exists, else built-in defaults)")
    ap.add_argument("--region", help="price book region, e.g. eu-west-1 or us-east-1 (overrides the config)")
    ap.add_argument("--vm", action="append", default=[], metavar="SPEC",
                    help="override a VM: NAME=TYPE, NAME=none (remove), NAME.ebs_gb=N, NAME.hours_per_month=N; "
                         "a new NAME adds a VM (repeatable)")
    ap.add_argument("--price", action="append", default=[], metavar="KEY=USD",
                    help="override a price, e.g. glue_dpu_hour=0.308 or vm_hourly.m7g.2xlarge=0.36 (repeatable)")
    ap.add_argument("--format", choices=["md", "markdown", "html", "json"],
                    help="output format; inferred from -o extension, else md")
    ap.add_argument("--link", action="append", default=[], metavar="LABEL=URL",
                    help="add a link to a related page in the html output's top bar, e.g. "
                         "--link 'Cost estimate=cost.html' (repeatable; the -o file is marked current)")
    ap.add_argument("-o", "--output", help="write to a file instead of stdout")
    ap.add_argument("--emit-usage", metavar="PATH", help="also write the usage actually priced (after VM overrides)")
    args = ap.parse_args(argv)

    cfg_path = args.config or (DEFAULT_CONFIG if os.path.exists(DEFAULT_CONFIG) else None)
    data: dict[str, Any] = {}
    if cfg_path:
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
    if args.region:
        data["region"] = args.region
    prices_section = dict(data.get("prices", {}))
    vm_prices = dict(prices_section.get("vm_hourly", {}))
    for key, value in map(parse_price_override, args.price):
        if key.startswith("vm_hourly."):
            vm_prices[key.split(".", 1)[1]] = value
        else:
            prices_section[key] = value
    prices_section["vm_hourly"] = vm_prices
    data["prices"] = prices_section

    try:
        cfg = cost_config.from_dict(data)
        usage = load_usage(args.input)
        usage = usage.with_vm_overrides(cfg.vm_overrides + [parse_vm_override(s) for s in args.vm])
        result = estimate(usage, cfg.prices, cfg.terms)
    except (ValueError, FileNotFoundError) as e:
        raise SystemExit(f"trace-cost: {e}")

    if args.emit_usage:
        usage.save(args.emit_usage)

    fmt = args.format or _EXT.get(os.path.splitext(args.output or "")[1].lower(), "md")
    if fmt == "json":
        import json
        text = json.dumps(result.to_dict(), indent=2) + "\n"
    elif fmt == "html":
        try:
            links = parse_links(args.link)
        except ValueError as e:
            raise SystemExit(f"trace-cost: {e}")
        text = cost_page_html(result, nav=links, current=os.path.basename(args.output) if args.output else None)
    else:
        text = cost_page_md(result)

    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
