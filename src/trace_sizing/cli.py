"""Command line: trace-sizing [params.toml] [--format md|html|json] [--scale 0.5,1,2] [--set iot.pilot_sites=5]

The JSON report carries a "usage" block that trace-cost reads; the md/html
reports include the cost section, priced with config/cost.toml if it exists.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys

from . import params as params_mod
from .formulas import formulas
from .html_report import full_html
from .cost import estimate, load_config as load_cost_config, usage_from_sizing
from .model import calculate, scaling_table
from .report import full_md


def _coerce(raw: str):
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("none", "null"):
        return None
    for t in (int, float):
        try:
            return t(raw)
        except ValueError:
            pass
    return raw


def apply_overrides(p: params_mod.Params, overrides: list[str]) -> params_mod.Params:
    for o in overrides:
        key, _, raw = o.partition("=")
        section, _, name = key.partition(".")
        if not raw or not name:
            raise SystemExit(f"--set expects section.key=value, got {o!r}")
        sub = getattr(p, section, None)
        if sub is None or not dataclasses.is_dataclass(sub) or name not in {f.name for f in dataclasses.fields(sub)}:
            raise SystemExit(f"--set: unknown parameter {key!r}")
        p = dataclasses.replace(p, **{section: dataclasses.replace(sub, **{name: _coerce(raw)})})
    return p


_EXT_FORMATS = {".md": "md", ".markdown": "md", ".html": "html", ".htm": "html", ".json": "json"}


def _resolve_format(fmt: str | None, output: str | None) -> str:
    """--format wins; otherwise the -o extension; otherwise Markdown."""
    if fmt:
        return "md" if fmt == "markdown" else fmt
    if output:
        ext = os.path.splitext(output)[1].lower()
        if ext in _EXT_FORMATS:
            return _EXT_FORMATS[ext]
    return "md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace-sizing", description="TRACE WP3 platform sizing calculator")
    ap.add_argument(
        "params", nargs="?",
        help="TOML parameter file, e.g. config/trace_workload.toml (omit to use the TRACE defaults)",
    )
    ap.add_argument("--format", choices=["md", "markdown", "html", "json"], default=None,
                    help="output format; inferred from -o extension (.md, .html, .json) if omitted, else md")
    ap.add_argument("--scale", help="comma-separated scale factors, e.g. 0.5,1,2,10 ('none' to skip)")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE",
                    help="override one parameter, e.g. --set iot.pilot_sites=5 (repeatable)")
    ap.add_argument("--no-params", action="store_true",
                    help="hide the 'Parameters used' section (md/html only; json always includes params)")
    ap.add_argument("--no-formulas", action="store_true",
                    help="hide the Formulas section (md/html only)")
    ap.add_argument("--cost-config", metavar="PATH",
                    help="cost config for the cost section (default: config/cost.toml if it exists)")
    ap.add_argument("--no-cost", action="store_true", help="leave out the cost section")
    ap.add_argument("-o", "--output", help="write to file instead of stdout")
    args = ap.parse_args(argv)
    args.format = _resolve_format(args.format, args.output)

    p = params_mod.load(args.params) if args.params else params_mod.Params()
    p = apply_overrides(p, args.set)

    if args.scale and args.scale.lower() == "none":
        factors: list[float] = []
    elif args.scale:
        factors = [float(x) for x in args.scale.split(",")]
    else:
        factors = p.sizing.scale_factors

    result = calculate(p)
    table = scaling_table(p, factors) if factors else None
    usage = usage_from_sizing(p, result)
    cost = None
    if not args.no_cost:
        cfg_path = args.cost_config or ("config/cost.toml" if os.path.exists("config/cost.toml") else None)
        try:
            cfg = load_cost_config(cfg_path)
            cost = estimate(usage.with_vm_overrides(cfg.vm_overrides), cfg.prices, cfg.terms)
        except ValueError as e:
            raise SystemExit(f"trace-sizing: cost config: {e}")

    if args.format == "json":
        doc = {
            "params": dataclasses.asdict(p),
            "result": result.to_dict(),
            "usage": usage.to_dict(),
            "cost": cost.to_dict() if cost is not None else None,
            "scaling": [{"factor": f, "result": r.to_dict()} for f, _, r in (table or [])],
            "formulas": [dataclasses.asdict(f) for f in formulas(p, result, cost)],
        }
        text = json.dumps(doc, indent=2) + "\n"
    elif args.format == "html":
        text = full_html(p, result, table, show_params=not args.no_params, show_formulas=not args.no_formulas,
                         cost=cost)
    else:
        text = full_md(p, result, table, show_params=not args.no_params, show_formulas=not args.no_formulas,
                       cost=cost)

    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
