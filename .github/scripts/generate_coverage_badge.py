#!/usr/bin/env python3
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _color_for_percentage(pct: int) -> str:
  if pct >= 90:
    return "#4c1"  # bright green
  if pct >= 80:
    return "#97CA00"  # green
  if pct >= 70:
    return "#dfb317"  # yellow
  if pct >= 50:
    return "#fe7d37"  # orange
  return "#e05d44"  # red


def _text_width_px(text: str) -> int:
  # Approx for Verdana 11px used by shields-style badges
  return int(len(text) * 6.2 + 10)


def generate_svg(label: str, value: str, color: str) -> str:
  label_w = max(50, _text_width_px(label))
  value_w = max(35, _text_width_px(value))
  total_w = label_w + value_w

  label_x = label_w / 2
  value_x = label_w + value_w / 2

  title = f"{label}: {value}"

  return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20" role="img" aria-label="{title}">
  <title>{title}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_w}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{color}"/>
    <rect width="{total_w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="{label_x:.1f}" y="14">{label}</text>
    <text x="{value_x:.1f}" y="14">{value}</text>
  </g>
</svg>
"""


def main(argv: list[str]) -> int:
  if len(argv) != 3:
    print("Usage: generate_coverage_badge.py <coverage.xml> <out.svg>", file=sys.stderr)
    return 2

  in_path = Path(argv[1])
  out_path = Path(argv[2])

  if not in_path.exists():
    print(f"coverage file not found: {in_path}", file=sys.stderr)
    return 1

  root = ET.parse(in_path).getroot()
  line_rate = float(root.attrib.get("line-rate", "0") or 0)
  pct = int(round(line_rate * 100))

  svg = generate_svg("coverage", f"{pct}%", _color_for_percentage(pct))
  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_text(svg, encoding="utf-8")
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv))

