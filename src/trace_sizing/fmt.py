"""Shared number formatting for the Markdown, HTML and formula renderers."""

from __future__ import annotations


def _n(x: float, d: int = 2) -> str:
    if x == 0:
        return "0"
    if abs(x) < 10 ** -d:
        return f"< {10 ** -d:g}"
    s = f"{x:,.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)
