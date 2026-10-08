"""Render a CostEstimate as Markdown, as an HTML section (embedded in the
sizing report), or as a standalone Markdown/HTML page (trace-cost)."""

from __future__ import annotations

from ..fmt import _n, md_table
from ..htmlkit import _esc, _h3, _section, _slug, _table, page
from .prices import PRICES_CHECKED, RATE_KEYS

NOTE = ("On-demand list prices from AWS's public price list (USD, ex. tax), applied to the sizing report's usage. "
        "Assumes every site is live from month 1, so it errs high for a phased roll-out.")


def _money(x: float, cur: str = "$") -> str:
    return f"{cur}{x:,.0f}"


def summary_rows(c) -> list[tuple[str, str, str]]:
    """(key, label, value) rows for the headline table."""
    t = c.terms
    rows = [("subtotal-usd", "Subtotal (USD)", _money(c.total_usd)),
            ("eur", f"In EUR (x {_n(t.usd_to_eur)})", _money(c.total_eur, "EUR "))]
    if t.discount:
        rows.append(("after-discount", f"After {_n(t.discount * 100)}% discount", _money(c.after_discount_eur, "EUR ")))
    rows.append(("incl-vat", f"Incl. {_n(t.vat * 100)}% VAT", _money(c.total_incl_vat_eur, "EUR ")))
    if t.budget_eur:
        d = c.budget_headroom_eur
        rows.append(("budget", f"Budget (EUR {t.budget_eur:,.0f})",
                     f"under by EUR {d:,.0f}" if d >= 0 else f"OVER by EUR {-d:,.0f}"))
    return rows


def _vm_rows(c) -> list[list[str]]:
    return [[v.name, v.instance_type, f"${c.prices.vm_rate(v.instance_type)}/h", f"{v.hours_per_month:g}",
             f"{v.ebs_gb:g} GB"] for v in c.usage.vms]


# --------------------------------------------------------------------------- markdown

def cost_md(c) -> str:
    rows = summary_rows(c)
    return "\n".join([
        f"## AWS cost estimate ({c.months} months, {c.region})",
        "",
        f"_{NOTE}_",
        "",
        md_table(["", "Amount"], [[label, f"**{v}**" if key in ("subtotal-usd", "incl-vat") else v]
                                  for key, label, v in rows]),
        "",
        "**By year**",
        "",
        md_table(["Year", "USD", "EUR"], [[f"Year {i + 1}", _money(y), _money(y * c.terms.usd_to_eur, "EUR ")]
                                          for i, y in enumerate(c.year_totals_usd())]),
        "",
        "**By category**",
        "",
        md_table(["Category", "USD", "Share"], [[k, _money(v), f"{v / c.total_usd * 100:.0f}%"]
                                               for k, v in c.category_totals_usd().items()]),
        "",
        "**Line items**",
        "",
        md_table(["Category", "Item", "Basis", "Avg/month", "Total"],
                 [[l.category, l.item, l.basis, _money(l.total_usd / c.months), f"**{_money(l.total_usd)}**"]
                  for l in c.lines]),
    ])


def _inputs_md(c) -> str:
    u = c.usage
    return "\n".join([
        "## Inputs",
        "",
        "**VMs priced**",
        "",
        md_table(["VM", "Instance type", "Price", "Hours/month", "EBS"], _vm_rows(c)),
        "",
        "**Usage (average per month)**",
        "",
        md_table(["Quantity", "Average/month"], _usage_rows(u)),
        "",
        f"**Prices ({c.region}, checked {PRICES_CHECKED})**",
        "",
        md_table(["Price", "USD"], [[RATE_KEYS[k], f"{v:g}"] for k, v in c.prices.rates.items()]),
    ])


def _usage_rows(u) -> list[list[str]]:
    avg = lambda s: sum(s) / len(s) if s else 0.0
    rows = [[f"S3 {t.replace('_', ' ')} stored", f"{avg(u.storage_gb.get(t, [])):,.0f} GB"] for t in u.storage_gb]
    rows += [[f"S3 {k.upper()} requests", f"{avg(v):,.0f}"] for k, v in u.s3_requests.items()]
    rows += [[f"Objects moved to {t.replace('_', ' ')}", f"{avg(v):,.0f}"] for t, v in u.transitions.items()]
    rows += [[f"Glue DPU-hours: {k}", f"{avg(v):,.1f}"] for k, v in u.glue_dpu_hours.items()]
    rows += [["Public IPv4 addresses", str(u.public_ipv4)], ["NAT instances", str(u.nat_instances)],
             ["Data transfer out", f"{avg(u.egress_gb):,.0f} GB"]]
    rows += [[f"Retrieved from {t.replace('_', ' ')}", f"{avg(v):,.0f} GB"] for t, v in u.retrieval_gb.items()]
    return rows


def cost_page_md(c) -> str:
    src = c.usage.source.get("from", "usage file")
    return (f"# TRACE AWS cost estimate\n\n_Usage from {src}; {c.months} months; {c.region}._\n\n"
            + cost_md(c) + "\n\n" + _inputs_md(c) + "\n")


# --------------------------------------------------------------------------- html

def cost_section_html(c) -> str:
    rows = summary_rows(c)
    summary = [[_esc(label),
                f'<strong class="warn">{_esc(v)}</strong>' if v.startswith("OVER")
                else f"<strong>{_esc(v)}</strong>" if key in ("subtotal-usd", "incl-vat") else _esc(v)]
               for key, label, v in rows]
    years = c.year_totals_usd()
    body = (
        _table(["", "Amount"], summary, tid="cost--summary", keys=[k for k, _, _ in rows])
        + _h3("By year", "cost", "by-year")
        + _table(["Year", "USD", "EUR"], [[f"Year {i + 1}", _money(y), _money(y * c.terms.usd_to_eur, "EUR ")]
                                          for i, y in enumerate(years)],
                 tid="cost--by-year", keys=[f"year-{i + 1}" for i in range(len(years))])
        + _h3("By category", "cost", "by-category")
        + _table(["Category", "USD", "Share"],
                 [[_esc(k), _money(v), f"{v / c.total_usd * 100:.0f}%"] for k, v in c.category_totals_usd().items()],
                 tid="cost--by-category")
        + _h3("Line items", "cost", "lines")
        + _table(["Category", "Item", "Basis", "Avg/month", "Total"],
                 [[_esc(l.category), _esc(l.item), _esc(l.basis), _money(l.total_usd / c.months),
                   f"<strong>{_money(l.total_usd)}</strong>"] for l in c.lines],
                 tid="cost--lines", keys=[_slug(l.item.split("(")[0]) for l in c.lines])
    )
    return _section(f"AWS cost estimate ({c.months} months, {c.region})", body, NOTE, sid="cost")


def cost_page_html(c) -> str:
    inputs = (
        _h3("VMs priced", "inputs", "vms")
        + _table(["VM", "Instance type", "Price", "Hours/month", "EBS"],
                 [[_esc(x) for x in r] for r in _vm_rows(c)], tid="inputs--vms")
        + _h3("Usage (average per month)", "inputs", "usage")
        + _table(["Quantity", "Average/month"], [[_esc(x) for x in r] for r in _usage_rows(c.usage)],
                 tid="inputs--usage")
        + _h3(f"Prices ({c.region}, checked {PRICES_CHECKED})", "inputs", "prices")
        + _table(["Price", "USD"], [[_esc(RATE_KEYS[k]), f"{v:g}"] for k, v in c.prices.rates.items()],
                 tid="inputs--prices", keys=list(c.prices.rates))
    )
    body = cost_section_html(c) + _section("Inputs", inputs, sid="inputs")
    src = _esc(c.usage.source.get("from", "usage file"))
    return page("TRACE AWS cost estimate", f"Usage from {src} &middot; {c.months} months &middot; {_esc(c.region)}",
                body, "Generated by trace-cost. This page has no external dependencies.")
