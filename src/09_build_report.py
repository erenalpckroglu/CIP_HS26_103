"""Build report/CIP_HS26_103_Documentation.pdf from report/report.md.

Run from the repo root: python src/09_build_report.py
Markdown -> HTML (python-markdown) -> PDF (headless Google Chrome, A4); prints the page count (maximum: 6 pages).
"""
import re
import subprocess
from pathlib import Path

import markdown

from config import ROOT
from utils import get_logger

log = get_logger("report")

REPORT_DIR = ROOT / "report"
PDF = REPORT_DIR / "CIP_HS26_103_Documentation.pdf"
MAX_PAGES = 6
CHROME_PATHS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome"]
CSS = """
@page { size: A4; margin: 1.5cm 1.6cm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9.3pt; line-height: 1.32; color: #111; }
h1 { font-size: 16pt; margin: 0 0 2pt 0; }
h2 { font-size: 11.5pt; margin: 9pt 0 3pt 0; border-bottom: 0.6pt solid #999; }
h3 { font-size: 10pt; margin: 7pt 0 2pt 0; }
p { margin: 2.5pt 0 4pt 0; text-align: justify; }
.meta { font-size: 8.5pt; color: #444; margin-bottom: 4pt; text-align: left; }
table { border-collapse: collapse; width: 100%; font-size: 7.9pt; margin: 3pt 0 5pt 0; }
th, td { border: 0.5pt solid #999; padding: 1.5pt 3pt; vertical-align: top; text-align: left; }
th { background: #eee; }
code { font-size: 8pt; }
.row { display: flex; gap: 8pt; align-items: flex-start; margin: 3pt 0; }
.row figure { flex: 1 1 0; margin: 0; }
figure { margin: 3pt 0; break-inside: avoid; }
figure img { width: 100%; display: block; }
figure.wide img { width: 86%; margin: 0 auto; }
figure.mid img { width: 62%; margin: 0 auto; }
h2, h3 { break-after: avoid; }
figcaption { font-size: 7.6pt; color: #333; margin-top: 1pt; text-align: left; }
"""


def find_chrome():
    """Path of the installed Google Chrome."""
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    raise FileNotFoundError("Google Chrome not found; adjust CHROME_PATHS in src/09_build_report.py")


def count_pages(pdf_path):
    """Number of pages of a PDF (counts the page objects)."""
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", pdf_path.read_bytes()))


def main():
    body = markdown.markdown((REPORT_DIR / "report.md").read_text(encoding="utf-8"), extensions=["tables"])
    html_path = REPORT_DIR / "report.html"
    html_path.write_text(f'<!doctype html><html><head><meta charset="utf-8"><title>CIP HS26 Group 103</title>'
                         f"<style>{CSS}</style></head><body>{body}</body></html>", encoding="utf-8")
    PDF.unlink(missing_ok=True)
    subprocess.run([find_chrome(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={PDF}", html_path.as_uri()], check=True, capture_output=True, timeout=120)
    pages = count_pages(PDF)
    log.info("%s written, %d pages (maximum %d): %s", PDF.name, pages, MAX_PAGES, "OK" if pages <= MAX_PAGES else "TOO LONG")


if __name__ == "__main__":
    main()
