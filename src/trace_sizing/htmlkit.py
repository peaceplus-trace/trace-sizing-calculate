"""Shared HTML building blocks: escaping, stable ids, copy-link anchors,
tables, sections, and the page shell (CSS + link-sharing script).

Used by html_report.py (sizing report) and cost/render.py (cost report),
so both pages look and behave the same.
"""

from __future__ import annotations

import html as _html
import re


def _esc(x) -> str:
    return _html.escape(str(x))


def _slug(text: str) -> str:
    """Stable, URL-safe id fragment from a label (tags and entities stripped)."""
    plain = _html.unescape(re.sub(r"<[^>]+>", "", str(text))).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "item"


def _anchor(eid: str) -> str:
    return f'<a class="anchor" href="#{eid}" title="Copy link to this" aria-label="Copy link to this">#</a>'


def _h3(text: str, parent: str, key: str | None = None) -> str:
    eid = f"{parent}--{key or _slug(text)}"
    return f'<h3 id="{eid}">{_esc(text)}{_anchor(eid)}</h3>'


def _table(headers: list[str], rows: list[list[str]], tid: str | None = None,
           keys: list[str] | None = None) -> str:
    """With `tid`, every row gets id `tid--key` and a copy-link anchor. Keys
    default to the first cell's text; pass `keys` where that text contains
    values that change between runs, so shared links stay valid."""
    thead = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body_rows, seen = [], {}
    for i, row in enumerate(rows):
        if tid:
            key = keys[i] if keys else _slug(row[0])
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                key = f"{key}-{seen[key]}"
            eid = f"{tid}--{key}"
            first = f"{_anchor(eid)}{row[0]}"
            cells = "".join(f"<td>{c}</td>" for c in [first] + row[1:])
            body_rows.append(f'<tr id="{eid}">{cells}</tr>')
        else:
            body_rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    return (f'<div class="wrap"><table><thead><tr>{thead}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table></div>')


def _section(title: str, body: str, note: str = "", sid: str | None = None,
             title_html: str | None = None) -> str:
    sid = sid or _slug(title)
    note_html = f'<p class="note">{note}</p>' if note else ""
    heading = title_html if title_html is not None else _esc(title)
    return f'<section id="{sid}"><h2>{heading}{_anchor(sid)}</h2>{note_html}{body}</section>'


_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#6b7280;--border:#e5e7eb;--accent:#2563eb;
--ok:#16a34a;--ok-bg:#dcfce7;--warn:#dc2626;--warn-bg:#fee2e2;--card:#f9fafb}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e5e7eb;--muted:#9ca3af;
--border:#2a2e37;--accent:#60a5fa;--ok:#4ade80;--ok-bg:#14301f;--warn:#f87171;
--warn-bg:#3b1212;--card:#171a21}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);margin:0;padding:1.5rem;
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto}
h1{font-size:1.6rem;margin-bottom:0.25rem}
h2{font-size:1.2rem;border-bottom:1px solid var(--border);padding-bottom:0.4rem;margin-top:2rem}
h3{font-size:1rem;color:var(--muted);margin-top:1.2rem}
.subtitle{color:var(--muted);margin-top:0}
.note{color:var(--muted);font-size:0.9rem}
table{width:100%;border-collapse:collapse;margin:0.6rem 0 1rem;font-size:0.9rem}
th,td{text-align:left;padding:0.4rem 0.6rem;border-bottom:1px solid var(--border);white-space:nowrap}
th{color:var(--muted);font-weight:600}
tr:hover td{background:var(--card)}
.wrap{overflow-x:auto}
code{background:var(--card);padding:0.1rem 0.35rem;border-radius:4px;font-size:0.85em}
.badge{display:inline-block;padding:0.1rem 0.6rem;border-radius:999px;font-size:0.85em;font-weight:700}
.badge.ok{background:var(--ok-bg);color:var(--ok)}
.badge.bad{background:var(--warn-bg);color:var(--warn)}
.warn{color:var(--warn)}
.bar-track{display:inline-block;width:140px;height:8px;background:var(--border);
border-radius:4px;overflow:hidden;vertical-align:middle;margin-right:0.5rem}
.bar-fill{height:100%;background:var(--accent)}
.bar-fill.over{background:var(--warn)}
.bar-label{font-variant-numeric:tabular-nums}
details summary{cursor:pointer;font-weight:600;color:var(--accent);margin:0.6rem 0}
section,h3,tr{scroll-margin-top:1rem}
.anchor{margin-left:0.4rem;color:var(--muted);text-decoration:none;font-weight:400;opacity:0;transition:opacity .15s}
td .anchor{margin:0 0.35rem 0 0}
h2:hover .anchor,h3:hover .anchor,tr:hover .anchor,.anchor:focus{opacity:1}
@media (hover:none){.anchor{opacity:.6}}
.anchor:hover{color:var(--accent)}
:root{--hl:#fef3c7}
@media (prefers-color-scheme:dark){:root{--hl:#3a3110}}
tr:target td,tr.flash td{background:var(--hl)}
section:target>h2,h3:target{background:var(--hl);border-radius:4px}
#toast{position:fixed;bottom:1.2rem;left:50%;transform:translateX(-50%);background:var(--fg);color:var(--bg);
padding:0.45rem 0.9rem;border-radius:6px;font-size:0.85rem;opacity:0;pointer-events:none;transition:opacity .2s}
#toast.show{opacity:1}
footer{color:var(--muted);font-size:0.8rem;margin-top:2.5rem;border-top:1px solid var(--border);padding-top:1rem}
"""


_JS = """
(function () {
  var toast = document.getElementById("toast"), t;
  function show(msg) {
    toast.textContent = msg; toast.classList.add("show");
    clearTimeout(t); t = setTimeout(function () { toast.classList.remove("show"); }, 1800);
  }
  function reveal(id) {
    var el = id && document.getElementById(id);
    if (!el) return;
    for (var p = el.parentElement; p; p = p.parentElement) if (p.tagName === "DETAILS") p.open = true;
    el.scrollIntoView({block: "center"});
  }
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    var ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta);
    ta.select(); try { document.execCommand("copy"); } finally { ta.remove(); }
    return Promise.resolve();
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.anchor");
    if (!a) return;
    e.preventDefault();
    var id = a.getAttribute("href").slice(1);
    history.replaceState(null, "", "#" + id);
    reveal(id);
    var url = location.href;
    copy(url).then(function () { show("Link copied"); }, function () { show(url); });
  });
  window.addEventListener("hashchange", function () { reveal(decodeURIComponent(location.hash.slice(1))); });
  if (location.hash) reveal(decodeURIComponent(location.hash.slice(1)));
})();
"""


def page(title: str, subtitle: str, body: str, footer: str) -> str:
    """A complete, dependency-free HTML page."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>{_esc(title)}</h1>
<p class="subtitle">{subtitle}</p>
{body}
<div id="toast" role="status" aria-live="polite"></div>
<script>{_JS}</script>
<footer>{footer}</footer>
</main>
</body>
</html>
"""
