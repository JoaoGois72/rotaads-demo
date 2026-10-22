"""Exportação PDF do Dashboard RotaAds V1.3.1.

Recebe apenas a estrutura agregada de analytics_v131.dashboard_data.
Não consulta a base nem conhece identificadores de GPS/dispositivos.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable,
    KeepTogether,
)

NAVY = colors.HexColor('#102d44')
GREEN = colors.HexColor('#277e67')
MUTED = colors.HexColor('#62798a')
LINE = colors.HexColor('#e0e8eb')
LIGHT = colors.HexColor('#f4f8f9')
ORANGE = colors.HexColor('#be8a38')


def safe_text(text, limit=175):
    value = '' if text is None else str(text)
    # ReportLab Paragraph suporta markup: escapar sempre dados do utilizador.
    value = ''.join(c if c.isprintable() else ' ' for c in value)
    if len(value) > limit:
        value = value[:limit - 1] + '…'
    return escape(value)


def integer(value):
    try:
        return f'{int(value):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return '0'


def _style():
    st = getSampleStyleSheet()
    st.add(ParagraphStyle(name='RotaTitle', fontName='Helvetica-Bold', fontSize=18,
                          leading=23, textColor=NAVY, spaceAfter=7))
    st.add(ParagraphStyle(name='RotaSub', fontName='Helvetica', fontSize=8.5,
                          leading=12, textColor=MUTED))
    st.add(ParagraphStyle(name='RotaSection', fontName='Helvetica-Bold', fontSize=11,
                          leading=15, textColor=NAVY, spaceBefore=13, spaceAfter=8))
    st.add(ParagraphStyle(name='RotaCell', fontName='Helvetica', fontSize=7.7,
                          leading=10.5, textColor=NAVY))
    st.add(ParagraphStyle(name='RotaCellSmall', parent=st['RotaCell'], fontSize=7,
                          leading=9.3))
    st.add(ParagraphStyle(name='RotaHead', fontName='Helvetica-Bold', fontSize=7.2,
                          leading=10, textColor=colors.white))
    st.add(ParagraphStyle(name='RotaNote', fontName='Helvetica', fontSize=7.7,
                          leading=11.2, textColor=MUTED))
    st.add(ParagraphStyle(name='RotaKpiLabel', fontName='Helvetica', fontSize=8,
                          leading=12, textColor=MUTED))
    st.add(ParagraphStyle(name='RotaKpiValue', fontName='Helvetica-Bold', fontSize=15,
                          leading=18, textColor=NAVY))
    return st


class DailyTrend(Flowable):
    """Gráfico vetorial de 3 séries (sem dependências JavaScript)."""
    def __init__(self, records, width, height=132):
        super().__init__()
        self.records = records
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        records = self.records
        left, right = 43, 9
        bottom, top = 29, self.height - 20
        available_width = max(1, self.width - left - right)
        available_height = max(1, top - bottom)
        all_vals = [float(row.get(key, 0) or 0) for row in records
                    for key in ('reproducoes', 'leituras', 'resgates')]
        maximum = max([1] + all_vals)
        c.setFont('Helvetica', 7)
        c.setStrokeColor(LINE)
        c.setFillColor(MUTED)
        for step in range(5):
            y = bottom + available_height * step / 4
            c.line(left, y, left + available_width, y)
            c.drawRightString(left - 7, y - 2, integer(round(maximum * step / 4)))
        palette = [('reproducoes', NAVY, 'Reproduções'),
                   ('leituras', GREEN, 'Leituras QR'),
                   ('resgates', ORANGE, 'Resgates')]
        for idx, (key, color, label) in enumerate(palette):
            c.setStrokeColor(color)
            c.setLineWidth(1.8 if idx == 0 else 1.2)
            if records:
                points = []
                for i, row in enumerate(records):
                    x = left + available_width * i / max(1, len(records) - 1)
                    y = bottom + available_height * float(row.get(key, 0) or 0) / maximum
                    points.append((x, y))
                path = c.beginPath()
                path.moveTo(*points[0])
                for x, y in points[1:]:
                    path.lineTo(x, y)
                c.drawPath(path)
            lx = left + idx * 120
            c.setFillColor(color)
            c.rect(lx, self.height - 10, 12, 3, fill=1, stroke=0)
            c.setFillColor(NAVY)
            c.setFont('Helvetica', 7)
            c.drawString(lx + 16, self.height - 12, label)
        if records:
            label_points = [0, len(records)//2, len(records)-1]
            c.setFillColor(MUTED)
            for i in sorted(set(label_points)):
                x = left + available_width * i / max(1, len(records)-1)
                if i == 0:
                    c.drawString(x, 13, str(records[i].get('data', '')))
                elif i == len(records) - 1:
                    c.drawRightString(x, 13, str(records[i].get('data', '')))
                else:
                    c.drawCentredString(x, 13, str(records[i].get('data', '')))


def _data_table(headers, records, widths, style, max_rows=None):
    rows = [[Paragraph(safe_text(h), style['RotaHead']) for h in headers]]
    for record in (records if max_rows is None else records[:max_rows]):
        rows.append([Paragraph(safe_text(value), style['RotaCellSmall']) for value in record])
    if len(rows) == 1:
        rows.append([Paragraph('Sem registos no período.', style['RotaCellSmall'])] + [''] * (len(headers)-1))
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, -1), (-1, -1), 0.5, LINE),
    ]))
    return table


def _footer(canvas, doc):
    canvas.saveState()
    w, _ = doc.pagesize
    canvas.setStrokeColor(LINE)
    canvas.line(17*mm, 14*mm, w-17*mm, 14*mm)
    canvas.setFillColor(MUTED)
    canvas.setFont('Helvetica', 7)
    canvas.drawString(17*mm, 9.5*mm, 'RotaAds  |  Relatório técnico de publicidade')
    canvas.drawRightString(w-17*mm, 9.5*mm, f'Página {doc.page}')
    canvas.restoreState()


def build_dashboard_pdf(report, admin=False):
    """Devolve bytes de PDF válido. report já vem filtrado pelo login autenticado."""
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4),
                            leftMargin=17*mm, rightMargin=17*mm,
                            topMargin=16*mm, bottomMargin=19*mm,
                            title='RotaAds - Dashboard Inteligente',
                            author='RotaAds', pageCompression=1)
    available = doc.width
    st = _style()
    story = []
    name = 'Relatório executivo - administração' if admin else 'Relatório de desempenho - anunciante'
    story.append(Paragraph('RotaAds  |  Dashboard Inteligente V1.3.1', st['RotaTitle']))
    story.append(Paragraph(safe_text(name) + f'  |  Últimos {int(report["dias"])} dias  |  Gerado em UTC: '
                           + safe_text(report.get('atualizado_em', '')), st['RotaSub']))
    story.append(Spacer(1, 13))
    summary = report['resumo']
    kpis = [
        ('Reproduções iniciadas', integer(summary.get('reproducoes', 0))),
        ('Ecrãs online / total', f'{integer(summary.get("ecra_online",0))} / {integer(summary.get("ecra_total",0))}'),
        ('Campanhas em curso / total', f'{integer(summary.get("campanhas_ativas",0))} / {integer(summary.get("campanhas",0))}'),
        ('Leituras QR', integer(summary.get('leituras', 0))),
        ('Resgates registados', integer(summary.get('resgates', 0))),
        ('Leituras por 100 reproduções',
         f'{summary["leituras_por_100_reproducoes"]}%' if summary.get('leituras_por_100_reproducoes') is not None else '-'),
    ]
    kpi_cells = []
    for label, val in kpis:
        kpi_cells.append([Paragraph(safe_text(label), st['RotaKpiLabel']),
                          Paragraph(safe_text(val), st['RotaKpiValue'])])
    boxes = Table([kpi_cells[:3], kpi_cells[3:]], colWidths=[available/3]*3)
    boxes.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 0.6, LINE),
        ('INNERGRID', (0, 0), (-1, -1), 0.6, LINE),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(boxes)
    story.append(Paragraph('Tendência diária', st['RotaSection']))
    story.append(DailyTrend(report.get('diario', []), available, 140))

    story.append(Paragraph('Comparação de campanhas', st['RotaSection']))
    if admin:
        headers = ['Campanha', 'Anunciante', 'Prioridade', 'Carros', 'Reproduções', 'QR', 'Resgates']
        widths = [available*.25, available*.20, available*.095, available*.105,
                  available*.14, available*.085, available*.125]
        rows = [[c.get('nome'), c.get('anunciante'), f'{c.get("peso_v13", 1)} / 5',
                 f'{c.get("atribuidos",0)} / {c.get("carros_contratados",0)}',
                 integer(c.get('reproducoes',0)), integer(c.get('leituras',0)),
                 integer(c.get('resgates',0))] for c in report.get('campanhas', [])]
    else:
        headers = ['Campanha', 'Prioridade', 'Carros', 'Reproduções', 'Leituras QR', 'Resgates']
        widths = [available*.38, available*.11, available*.12, available*.15,
                  available*.13, available*.11]
        rows = [[c.get('nome'), f'{c.get("peso_v13",1)} / 5',
                 f'{c.get("atribuidos",0)} / {c.get("carros_contratados",0)}',
                 integer(c.get('reproducoes',0)), integer(c.get('leituras',0)),
                 integer(c.get('resgates',0))] for c in report.get('campanhas', [])]
    story.append(_data_table(headers, rows, widths, st))

    story.append(Paragraph('Reproduções por zona publicitária', st['RotaSection']))
    story.append(_data_table(['Zona', 'Reproduções'],
                             [[z.get('nome'), integer(z.get('reproducoes',0))]
                              for z in report.get('zonas', [])],
                             [available*.75, available*.25], st))

    story.append(Paragraph('Reproduções por horário (Portugal)', st['RotaSection']))
    hourly = report.get('horario', [])
    # 24 h em linhas de 4 blocos compactos, um conjunto por linha.
    hr_rows = []
    for offset in range(6):
        cells = []
        for block in range(4):
            idx = block*6 + offset
            if idx < len(hourly):
                h = hourly[idx]
                cells.append(f'{h["hora"]}: {integer(h["reproducoes"])}')
            else:
                cells.append('')
        hr_rows.append(cells)
    story.append(_data_table(['00-05 h', '06-11 h', '12-17 h', '18-23 h'], hr_rows,
                             [available/4]*4, st))

    story.append(Paragraph('Evolução diária (datas UTC)', st['RotaSection']))
    daily = report.get('diario', [])
    story.append(_data_table(['Data UTC', 'Reproduções', 'Leituras QR', 'Resgates'],
                             [[d.get('data'), integer(d.get('reproducoes',0)),
                               integer(d.get('leituras',0)), integer(d.get('resgates',0))]
                              for d in daily], [available*.25]*4, st))

    if report.get('sugestoes'):
        story.append(Paragraph('Oportunidades de melhoria', st['RotaSection']))
        for title, description in report['sugestoes']:
            story.append(KeepTogether([
                Paragraph('<b>' + safe_text(title) + '</b>', st['RotaCell']),
                Paragraph(safe_text(description, 700), st['RotaNote']),
                Spacer(1, 7),
            ]))
    story.append(Spacer(1, 12))
    story.append(Paragraph('Nota metodológica: reproduções são inícios técnicos enviados pelos ecrãs; '
                           'leituras QR são acessos, não pessoas únicas; resgates dependem de confirmação manual. '
                           'Os indicadores não comprovam visualizações humanas nem vendas. '
                           'Os dados são agregados e não incluem localizações individuais.', st['RotaNote']))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output.getvalue()
