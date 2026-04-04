"""Build HTML and PDF artifacts for the paper from docs/pdf only."""

from __future__ import annotations

import html
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "paper.md"
HTML_OUT = ROOT / "paper.html"


def format_inline(text: str) -> str:
    """Convert a small markdown subset used by the paper into HTML."""
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def render_markdown(md: str) -> str:
    """Render the paper markdown using a purpose-built minimal parser."""
    lines = md.splitlines()
    output: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            output.append("<pre><code>")
            output.append(html.escape("\n".join(code_lines)))
            output.append("</code></pre>")
            i += 1
            continue

        if stripped.startswith("# "):
            output.append(f"<h1>{format_inline(stripped[2:])}</h1>")
            i += 1
            continue

        if stripped.startswith("## "):
            output.append(f"<h2>{format_inline(stripped[3:])}</h2>")
            i += 1
            continue

        if stripped.startswith("### "):
            output.append(f"<h3>{format_inline(stripped[4:])}</h3>")
            i += 1
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(f"<li>{format_inline(lines[i].strip()[2:])}</li>")
                i += 1
            output.append("<ul>")
            output.extend(items)
            output.append("</ul>")
            continue

        if re.match(r"^\d+\.\s", stripped):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i].strip()):
                item = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                items.append(f"<li>{format_inline(item)}</li>")
                i += 1
            output.append("<ol>")
            output.extend(items)
            output.append("</ol>")
            continue

        if stripped.startswith("**") and stripped.endswith("**") and stripped.count("**") == 2:
            output.append(f"<p class=\"callout\"><strong>{format_inline(stripped[2:-2])}</strong></p>")
            i += 1
            continue

        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            next_line = lines[i].strip()
            if not next_line:
                break
            if next_line.startswith(("#", "```", "- ")) or re.match(r"^\d+\.\s", next_line):
                break
            paragraph_lines.append(next_line)
            i += 1
        paragraph = " ".join(paragraph_lines)
        output.append(f"<p>{format_inline(paragraph)}</p>")

    return "\n".join(output)


def build_html(md: str) -> str:
    """Wrap rendered paper content in a print-friendly HTML template."""
    body = render_markdown(md)
    body = body.replace("<h2>Abstract</h2>", "<section class=\"abstract-block\"><h2>Abstract</h2>", 1)
    body = body.replace("<h2>1. Introduction</h2>", "</section><h2>1. Introduction</h2>", 1)
    body = re.sub(
        (
            r"^<h1>(.*?)</h1>\s*"
            r"<p><strong>Author:</strong>\s*(.*?)\s*"
            r"<strong>Project:</strong>\s*(.*?)\s*"
            r"<strong>Status:</strong>\s*(.*?)\s*"
            r"<strong>Date:</strong>\s*(.*?)</p>"
        ),
        (
            "<header class=\"title-block\">"
            "<h1>\\1</h1>"
            "<div class=\"meta\">"
            "<div><span class=\"label\">Author</span><span class=\"value\">\\2</span></div>"
            "<div><span class=\"label\">Project</span><span class=\"value\">\\3</span></div>"
            "<div><span class=\"label\">Status</span><span class=\"value\">\\4</span></div>"
            "<div><span class=\"label\">Date</span><span class=\"value\">\\5</span></div>"
            "</div>"
            "</header>"
        ),
        body,
        count=1,
        flags=re.S,
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Register Once, Verify Everywhere</title>
  <style>
    @page {{
      size: A4;
      margin: 18mm 18mm 20mm 18mm;
    }}

    :root {{
      --ink: #111827;
      --muted: #4b5563;
      --line: #d5dbe4;
      --bg: #ffffff;
      --code-bg: #f7f8fb;
      --accent: #1f2937;
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Times New Roman", Times, serif;
      line-height: 1.45;
      font-size: 11pt;
    }}

    main {{
      max-width: 820px;
      margin: 0 auto;
    }}

    .title-block {{
      text-align: center;
      margin: 0 0 16pt;
      page-break-after: avoid;
    }}

    h1 {{
      font-size: 23pt;
      line-height: 1.1;
      margin: 0 0 12pt;
      letter-spacing: 0;
      font-weight: 700;
    }}

    .meta {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4pt 16pt;
      max-width: 560px;
      margin: 0 auto;
      font-size: 10pt;
      color: var(--muted);
    }}

    .meta div {{
      display: flex;
      gap: 6pt;
      justify-content: center;
      white-space: nowrap;
    }}

    .label {{
      font-variant: small-caps;
      letter-spacing: 0.04em;
      color: var(--ink);
    }}

    h2 {{
      font-size: 14pt;
      margin: 18pt 0 7pt;
      font-weight: 700;
    }}

    h3 {{
      font-size: 11.5pt;
      margin: 12pt 0 5pt;
      color: var(--accent);
      font-weight: 700;
    }}

    p {{
      margin: 0 0 7pt;
      text-align: justify;
      hyphens: auto;
    }}

    p.callout {{
      text-align: left;
    }}

    .abstract-block {{
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 10pt 12pt 7pt;
      margin: 0 0 12pt;
      page-break-inside: avoid;
    }}

    .abstract-block h2 {{
      margin-top: 0;
      text-align: center;
      font-size: 12pt;
      font-variant: small-caps;
      letter-spacing: 0.05em;
    }}

    ul, ol {{
      margin: 0 0 8pt 18pt;
      padding: 0;
    }}

    li {{
      margin: 0 0 4pt;
    }}

    code {{
      font-family: "Courier New", Courier, monospace;
      font-size: 0.88em;
      background: var(--code-bg);
      padding: 1pt 3pt;
      border-radius: 3pt;
    }}

    pre {{
      margin: 9pt 0 11pt;
      padding: 9pt 11pt;
      background: var(--code-bg);
      border: 1px solid var(--line);
      border-radius: 4pt;
      overflow-wrap: anywhere;
      white-space: pre-wrap;
      page-break-inside: avoid;
    }}

    pre code {{
      background: none;
      padding: 0;
      border-radius: 0;
      font-size: 9.2pt;
    }}

    a {{
      color: #1d4ed8;
      text-decoration: none;
    }}

    strong {{
      color: #0f172a;
    }}

    @media screen {{
      body {{
        background: #eef2f7;
        padding: 20px 0;
      }}

      main {{
        background: white;
        padding: 18mm 18mm 20mm 18mm;
        box-shadow: 0 20px 60px rgba(15, 23, 42, 0.12);
      }}
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
</body>
</html>
"""


def main() -> None:
    """Build the paper HTML file from the markdown source."""
    md = SOURCE.read_text()
    HTML_OUT.write_text(build_html(md))
    print(f"Wrote {HTML_OUT}")


if __name__ == "__main__":
    main()
