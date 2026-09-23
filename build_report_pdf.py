from pathlib import Path
import re
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, KeepTogether

root = Path(__file__).parent
source = root / 'RucRut_Project_Report_Chapters_1-3.md'
target = root / 'RucRut_Project_Report_Chapters_1-3.pdf'
lines = source.read_text(encoding='utf-8').splitlines()
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='ReportTitle', parent=styles['Title'], fontName='Times-Bold', fontSize=24, leading=29, alignment=TA_CENTER, textColor=colors.HexColor('#a85d00'), spaceAfter=12))
styles.add(ParagraphStyle(name='ReportH1', parent=styles['Heading1'], fontName='Times-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#a85d00'), spaceBefore=16, spaceAfter=8, pageBreakBefore=True))
styles.add(ParagraphStyle(name='ReportH2', parent=styles['Heading2'], fontName='Times-Bold', fontSize=14, leading=18, textColor=colors.HexColor('#754400'), spaceBefore=12, spaceAfter=6))
styles.add(ParagraphStyle(name='ReportBody', parent=styles['BodyText'], fontName='Times-Roman', fontSize=10.5, leading=15, alignment=4, spaceAfter=7))
styles.add(ParagraphStyle(name='ReportSmall', parent=styles['BodyText'], fontName='Times-Roman', fontSize=8.5, leading=11))
styles.add(ParagraphStyle(name='ReportCode', parent=styles['Code'], fontName='Courier', fontSize=8, leading=10, backColor=colors.HexColor('#f6f6f6')))

def inline(text):
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', text)
    return text

def table_rows(start):
    rows = []
    index = start
    while index < len(lines) and lines[index].strip().startswith('|'):
        cells = [cell.strip() for cell in lines[index].strip().strip('|').split('|')]
        if not all(set(cell) <= set('-: ') for cell in cells):
            rows.append(cells)
        index += 1
    return rows, index

story = []
i = 0
paragraph = []
list_items = []
def flush_paragraph():
    global paragraph
    if paragraph:
        story.append(Paragraph(inline(' '.join(paragraph)), styles['ReportBody']))
        paragraph = []
def flush_list():
    global list_items
    if list_items:
        for item in list_items:
            story.append(Paragraph('• ' + inline(item), styles['ReportBody']))
        list_items = []
while i < len(lines):
    raw = lines[i]
    text = raw.strip()
    if not text:
        flush_paragraph(); flush_list(); i += 1; continue
    if text.startswith('|'):
        flush_paragraph(); flush_list(); rows, i = table_rows(i)
        if rows:
            data = [[Paragraph(inline(cell), styles['ReportSmall']) for cell in row] for row in rows]
            table = Table(data, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#fff1d6')),('TEXTCOLOR',(0,0),(-1,0),colors.HexColor('#603900')),('GRID',(0,0),(-1,-1),0.4,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
            story.extend([Spacer(1, 4), table, Spacer(1, 8)])
        continue
    if text.startswith('# '):
        flush_paragraph(); flush_list(); story.append(Paragraph(inline(text[2:]), styles['ReportTitle'])); i += 1; continue
    if text.startswith('## '):
        flush_paragraph(); flush_list(); story.append(Paragraph(inline(text[3:]), styles['ReportH1'])); i += 1; continue
    if text.startswith('### '):
        flush_paragraph(); flush_list(); story.append(Paragraph(inline(text[4:]), styles['ReportH2'])); i += 1; continue
    if text == '---':
        flush_paragraph(); flush_list(); story.append(Spacer(1, 8)); i += 1; continue
    if re.match(r'^\d+\.\s+', text):
        flush_paragraph(); list_items.append(re.sub(r'^\d+\.\s+', '', text)); i += 1; continue
    if text.startswith('- '):
        flush_paragraph(); list_items.append(text[2:]); i += 1; continue
    paragraph.append(text)
    i += 1
flush_paragraph(); flush_list()
doc = SimpleDocTemplate(str(target), pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=20*mm, bottomMargin=18*mm, title='RucRut Project Report Chapters 1-3', author='RucRut Team')
doc.build(story)
print(f'{target} ({target.stat().st_size} bytes)')
