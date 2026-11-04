"""리포트(report/*.md)를 같은 이름의 PDF로 만든다. 사용: python3 scripts/make_report_pdf.py report/<이름>.md [...]
순서: pandoc(md -> 단일 HTML, CSS 내장) -> Chrome headless(HTML -> PDF). 한글 글꼴은 macOS 'Apple SD Gothic Neo'.
필요: pandoc, /Applications/Google Chrome.app. 결과 PDF는 md와 같은 폴더·같은 이름(.pdf)이며 둘을 함께 커밋한다(CLAUDE.md 6장)."""
import subprocess, sys, tempfile
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: 'Apple SD Gothic Neo','AppleGothic',sans-serif; font-size: 10.5pt; line-height: 1.55; color: #1b1f24; max-width: none; margin: 0; padding: 0; }
h1 { font-size: 21pt; margin: 0 0 4pt; border-bottom: 2px solid #2b6cb0; padding-bottom: 6pt; }
h2 { font-size: 14.5pt; margin-top: 20pt; border-bottom: 1px solid #cbd5e0; padding-bottom: 3pt; break-after: avoid; }
h3 { font-size: 11.5pt; margin-top: 12pt; break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 8.8pt; break-inside: auto; }
th, td { border: 1px solid #cbd5e0; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #edf2f7; }
tr { break-inside: avoid; }
code { font-family: Menlo, monospace; font-size: 8.8pt; background: #f1f5f9; padding: 0 2pt; border-radius: 2pt; }
blockquote { margin: 8pt 0; padding: 4pt 10pt; border-left: 3px solid #90cdf4; background: #f7fafc; color: #2d3748; }
a { color: #2b6cb0; text-decoration: none; }
header#title-block-header { display: none; }
"""


def build(md: Path):
    pdf = md.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as td:
        css = Path(td) / "r.css"
        css.write_text(CSS)
        html = Path(td) / "r.html"
        subprocess.run(["pandoc", str(md), "-f", "gfm", "-s", "--embed-resources", "--css", str(css),
                        "--metadata", f"title={md.stem}", "-o", str(html)], check=True)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", f"file://{html}"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not pdf.exists() or pdf.stat().st_size < 2000:
        raise SystemExit(f"PDF 생성 실패: {pdf}")
    print(f"만듦: {pdf} ({pdf.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for a in sys.argv[1:]:
        build(Path(a))
