"""Command line: trace-sizing [params.toml] [--format md|json] [--scale 0.5,1,2] [--set iot.pilot_sites=5]"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from . import params as params_mod
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace-sizing", description="TRACE WP3 platform sizing calculator")
    ap.add_argument(
        "params", nargs="?",
        help="TOML parameter file, e.g. config/trace_workload.toml (omit to use the TRACE defaults)",
    )
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--scale", help="comma-separated scale factors, e.g. 0.5,1,2,10 ('none' to skip)")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE",
                    help="override one parameter, e.g. --set iot.pilot_sites=5 (repeatable)")
    ap.add_argument("-o", "--output", help="write to file instead of stdout")
    args = ap.parse_args(argv)

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

    if args.format == "json":
        doc = {
            "params": dataclasses.asdict(p),
            "result": result.to_dict(),
            "scaling": [{"factor": f, "result": r.to_dict()} for f, _, r in (table or [])],
        }
        text = json.dumps(doc, indent=2) + "\n"
    else:
        text = full_md(p, result, table)

    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
