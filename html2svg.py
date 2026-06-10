#!/usr/bin/env python3
"""
Extract embedded SVG elements from an HTML file and save each as a
standalone .svg file.

Usage:
    python html_to_svg.py input.html
    python html_to_svg.py input.html --out ./output_dir
    python html_to_svg.py input.html --prefix my_diagram
    python html_to_svg.py input.html --names "full,climate,schemas"
    python html_to_svg.py input.html --index 0        # only first SVG
    python html_to_svg.py input.html --list           # list SVGs, no output
"""

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("beautifulsoup4 is required:  pip install beautifulsoup4")


#  helpers
def load_html(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_svgs(html: str) -> list[str]:
    """Return list of SVG strings found in the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    return [str(svg) for svg in soup.find_all("svg")]


def infer_title(svg_str: str) -> str:
    """Try to pull a title from the SVG's first <text> or <title> element."""
    soup = BeautifulSoup(svg_str, "html.parser")
    # prefer explicit <title>
    t = soup.find("title")
    if t and t.text.strip():
        return slugify(t.text.strip())
    # fall back to first <text> content
    txt = soup.find("text")
    if txt and txt.text.strip():
        return slugify(txt.text.strip()[:40])
    return ""


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:50]


def ensure_xml_declaration(svg: str) -> str:
    """Prepend XML declaration if missing."""
    if not svg.strip().startswith("<?xml"):
        svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg
    return svg


def save_svg(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ensure_xml_declaration(content))


def describe(svg_str: str) -> dict:
    """Extract width, height, viewBox from an SVG string."""
    soup = BeautifulSoup(svg_str, "html.parser")
    tag = soup.find("svg")
    if not tag:
        return {}
    return {
        "width":   tag.get("width",   "?"),
        "height":  tag.get("height",  "?"),
        "viewBox": tag.get("viewBox", "?"),
    }


#  main
def main():
    parser = argparse.ArgumentParser(
        description="Extract SVG elements from an HTML file into standalone .svg files."
    )
    parser.add_argument("html", help="Path to the HTML file")
    parser.add_argument(
        "--out", default=None,
        help="Output directory (default: same directory as the HTML file)"
    )
    parser.add_argument(
        "--prefix", default="diagram",
        help="Filename prefix for output files (default: 'diagram')"
    )
    parser.add_argument(
        "--names", default=None,
        help="Comma-separated names to use instead of auto-generated ones, "
             "e.g. 'full,climate,schemas'"
    )
    parser.add_argument(
        "--index", type=int, default=None,
        help="Extract only the SVG at this index (0-based)"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all SVGs found without writing any files"
    )
    args = parser.parse_args()

    #  load
    html_path = Path(args.html).resolve()
    if not html_path.exists():
        sys.exit(f"File not found: {html_path}")

    html = load_html(str(html_path))
    svgs = extract_svgs(html)

    if not svgs:
        sys.exit("No <svg> elements found in the HTML file.")

    #  list mode
    if args.list:
        print(f"Found {len(svgs)} SVG element(s) in {html_path.name}:\n")
        for i, svg in enumerate(svgs):
            info = describe(svg)
            title = infer_title(svg) or "(no title)"
            print(f"  [{i}]  {info.get('width','?')} × {info.get('height','?')}"
                  f"  viewBox: {info.get('viewBox','?')}"
                  f"  title: {title}")
        return

    #  filter by index
    if args.index is not None:
        if args.index >= len(svgs):
            sys.exit(f"Index {args.index} out of range — only {len(svgs)} SVG(s) found.")
        svgs = [svgs[args.index]]
        start_index = args.index
    else:
        start_index = 0

    #  output directory
    out_dir = Path(args.out) if args.out else html_path.parent

    #  custom names
    custom_names = []
    if args.names:
        custom_names = [n.strip() for n in args.names.split(",")]

    #  write
    print(f"Extracting {len(svgs)} SVG(s) from {html_path.name} → {out_dir}/\n")
    written = []

    for i, svg in enumerate(svgs):
        real_index = start_index + i

        # determine filename
        if custom_names and i < len(custom_names):
            stem = custom_names[i]
        else:
            inferred = infer_title(svg)
            stem = (f"{args.prefix}_{real_index:02d}_{inferred}"
                    if inferred
                    else f"{args.prefix}_{real_index:02d}")

        out_path = out_dir / f"{stem}.svg"

        # avoid overwriting without warning
        if out_path.exists():
            print(f"  [!] {out_path.name} already exists — skipping "
                  f"(rename or use --prefix to avoid this)")
            continue

        save_svg(svg, out_path)
        info = describe(svg)
        print(f"  ✓  {out_path.name}"
              f"  ({info.get('width','?')} × {info.get('height','?')})")
        written.append(out_path)

    print(f"\nDone. {len(written)} file(s) written.")
    return written


if __name__ == "__main__":
    main()