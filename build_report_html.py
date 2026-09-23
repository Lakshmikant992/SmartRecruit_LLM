from pathlib import Path
import markdown

root = Path(__file__).parent
source = root / 'RucRut_Project_Report_Chapters_1-3.md'
target = root / 'RucRut_Project_Report_Chapters_1-3.html'
body = markdown.markdown(source.read_text(encoding='utf-8'), extensions=['tables', 'fenced_code'])
html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>RucRut Project Report Chapters 1-3</title>
<style>
@page {{ size: A4; margin: 22mm 18mm 20mm; }}
body {{ font-family: Georgia, 'Times New Roman', serif; color:#202124; line-height:1.55; font-size:11pt; }}
h1 {{ color:#a85d00; font-size:24pt; text-align:center; margin:22pt 0 12pt; page-break-before:always; }}
h1:first-child {{ page-break-before:auto; margin-top:80pt; }}
h2 {{ color:#a85d00; font-size:17pt; margin-top:20pt; border-bottom:1px solid #e1b36b; padding-bottom:4pt; }}
h3 {{ color:#754400; font-size:13pt; margin-top:15pt; }}
p {{ text-align:justify; }}
table {{ width:100%; border-collapse:collapse; margin:12pt 0; font-size:9.5pt; page-break-inside:avoid; }}
th {{ background:#fff1d6; color:#603900; }}
th,td {{ border:1px solid #b8b8b8; padding:6pt; vertical-align:top; }}
li {{ margin:4pt 0; }}
strong {{ color:#603900; }}
hr {{ border:0; border-top:1px solid #d0d0d0; margin:20pt 0; }}
code {{ font-family:Consolas, monospace; font-size:9pt; }}
</style></head><body>{body}</body></html>'''
target.write_text(html, encoding='utf-8')
print(target)
