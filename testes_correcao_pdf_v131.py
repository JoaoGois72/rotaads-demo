"""Verificação da exportação PDF. Não acede à base de dados operacional."""
from datetime import date, timedelta
from io import BytesIO
from reportlab import Version
from pdf_v131 import build_dashboard_pdf

report = {
    'dias': 7,
    'atualizado_em': '2026-10-21T12:00:00+00:00',
    'resumo': {'reproducoes': 100, 'ecra_online': 1, 'ecra_total': 2,
               'campanhas_ativas': 1, 'campanhas': 2, 'leituras': 3,
               'resgates': 1, 'leituras_por_100_reproducoes': 3.0},
    'diario': [{'data': (date(2026,10,21)-timedelta(days=i)).isoformat(),
                'reproducoes': 10, 'leituras': 1, 'resgates': 0} for i in range(7)],
    'campanhas': [{'nome': 'Campanha <Teste & A>', 'anunciante': 'Empresa <A>',
                   'peso_v13': 5, 'atribuidos': 1, 'carros_contratados': 2,
                   'reproducoes': 100, 'leituras': 3, 'resgates': 1}],
    'zonas': [{'nome': 'Lisboa Centro', 'reproducoes': 100}],
    'horario': [{'hora': f'{i:02}:00', 'reproducoes': i} for i in range(24)],
    'sugestoes': [('Oportunidade', 'Manter a divulgação durante as horas adequadas.')],
}
for admin in [False, True]:
    pdf = build_dashboard_pdf(report, admin)
    assert pdf.startswith(b'%PDF-') and b'%%EOF' in pdf[-64:], 'O PDF não é válido.'
    assert len(pdf) > 2000, 'O PDF está vazio ou incompleto.'
    print('  OK - Exportação PDF do ' + ('administrador' if admin else 'anunciante'))
print('\nRESULTADO: geração dos PDFs concluída com sucesso (ReportLab ' + str(Version) + ').')
print('NOTA: execute testes_v1_3_1_flask.py para validar autenticação e downloads HTTP.')
