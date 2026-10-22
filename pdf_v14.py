"""Relatórios PDF administrativos V1.4 — minutas e resumos, sem assinatura digital."""
from io import BytesIO
from html import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from frotas_v14 import euros


def styles():
    st=getSampleStyleSheet()
    st.add(ParagraphStyle(name='RA14Title',parent=st['Title'],fontName='Helvetica-Bold',
                          textColor=colors.HexColor('#17354d'),fontSize=18,spaceAfter=13,alignment=TA_LEFT))
    st.add(ParagraphStyle(name='RA14Body',fontName='Helvetica',fontSize=9.7,leading=15,
                          textColor=colors.HexColor('#273d50'),spaceAfter=7))
    st.add(ParagraphStyle(name='RA14Small',fontName='Helvetica',fontSize=8.3,leading=13,
                          textColor=colors.HexColor('#6b7d89'),spaceAfter=6))
    return st


def P(value, s):
    return Paragraph(escape(str(value if value is not None else '')),s)


def pdf_contract(c, vehicle, beneficiary):
    buffer=BytesIO(); st=styles()
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=24*mm,leftMargin=24*mm,
                          topMargin=21*mm,bottomMargin=22*mm,title=f'RotaAds - resumo de cedencia #{c["id"]}')
    story=[Paragraph('RotaAds · Ficha de cedência de espaço publicitário',st['RA14Title']),
           Paragraph('DOCUMENTO ADMINISTRATIVO / MINUTA NÃO ASSINADA',st['RA14Small']),
           Paragraph('Este resumo reproduz os dados do cadastro. Não substitui contrato escrito revisto e assinado pelas partes.',st['RA14Body']),
           Spacer(1,7*mm)]
    rows=[('N.º do registo',str(c['id'])), ('Matrícula',vehicle['matricula']),
          ('Veículo',(vehicle['marca'] or '')+' '+(vehicle['modelo'] or '')),
          ('Beneficiário',beneficiary),('Tipo de beneficiário',c['beneficiario_tipo']),
          ('Valor mensal',euros(c['valor_centimos']).replace('€','EUR')),
          ('Início',c['data_inicio']),('Fim',c['data_fim'] or 'Sem fim definido'),
          ('Vencimento','Dia '+str(c['dia_vencimento'])+' de cada mês'),
          ('Estado atual',c['estado']),('Observações',c['observacoes'] or '—')]
    data=[[P(a,st['RA14Small']),P(b,st['RA14Body'])] for a,b in rows]
    table=Table(data,colWidths=[47*mm,114*mm],hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[colors.whitesmoke,colors.white]),
        ('LINEBELOW',(0,0),(-1,-1),.35,colors.HexColor('#dde5eb')),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
    story += [table,Spacer(1,17*mm),
              Paragraph('Assinaturas — após revisão e formalização contratual',st['RA14Body']),
              Spacer(1,11*mm),
              Paragraph('_______________________________________________',st['RA14Body']),
              Paragraph('Entidade promotora (identificar juridicamente)',st['RA14Small']),
              Spacer(1,7*mm),
              Paragraph('_______________________________________________',st['RA14Body']),
              Paragraph('Parceiro / beneficiário da cedência',st['RA14Small'])]
    doc.build(story)
    return buffer.getvalue()


def pdf_payments(month, entries, summary_data):
    buffer=BytesIO(); st=styles();doc=SimpleDocTemplate(buffer,pagesize=landscape(A4),
        rightMargin=18*mm,leftMargin=18*mm,topMargin=18*mm,bottomMargin=18*mm,
        title=f'RotaAds - pagamentos {month}')
    story=[Paragraph('RotaAds · Controlo de pagamentos',st['RA14Title']),
           Paragraph('Competência: '+escape(month)+' · Confirmações de pagamento são manuais.',st['RA14Body'])]
    vals=[('Total',summary_data['total']),('Pago',summary_data['pago']),
          ('Pendente',summary_data['pendente']),('Vencido',summary_data['vencido'])]
    story += [Paragraph('  |  '.join(f'{title}: {euros(v).replace("€","EUR")}' for title,v in vals),st['RA14Body']),Spacer(1,5*mm)]
    header=['Contrato','Matrícula','Beneficiário','Montante','Vencimento','Estado','Referência']
    data=[[P(x,st['RA14Small']) for x in header]]
    for row in entries:
        cells=[f'#{row["contrato_id"]}',row['matricula'],row['beneficiario'] or '—',
            euros(row['valor_centimos']).replace('€','EUR'),row['vencimento'],row['estado'],row['referencia'] or '—']
        data.append([P(x,st['RA14Body']) for x in cells])
    table=Table(data,colWidths=[19*mm,29*mm,66*mm,29*mm,30*mm,25*mm,53*mm],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9f1f5')),
        ('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f8fa')]),
        ('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#e1e9eb')),
        ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story += [table,Spacer(1,6*mm),Paragraph('Relatório administrativo; não equivale a comprovativos bancários ou documentos fiscais.',st['RA14Small'])]
    doc.build(story)
    return buffer.getvalue()
