"""Painéis analíticos V1.3.1: isolados da lógica de reprodução V1.3."""
import csv
import io
from flask import Response, abort, render_template, request
from analytics_v131 import dashboard_data, period_days, csv_safe
from pdf_v131 import build_dashboard_pdf


def register_v131_routes(app, get_db, admin_required, advertiser_required, current_advertiser):
    def read_days():
        try:
            return period_days(request.args.get('dias', '30'))
        except ValueError:
            abort(400, 'Escolha 7, 30 ou 90 dias.')

    def csv_report(report, only_company=False):
        buff = io.StringIO(newline='')
        w = csv.writer(buff, delimiter=';')
        def row(*cells):
            w.writerow([csv_safe(c) for c in cells])
        row('RotaAds — Relatório de desempenho V1.3.1')
        row('Âmbito', 'Campanhas do anunciante' if only_company else 'Consolidado administrativo')
        row('Período', f"{report['dias']} dias corridos (datas em UTC)")
        row('Gerado em (UTC)', report['atualizado_em'])
        row('Indicador', 'Valor')
        for key, value in report['resumo'].items():
            row(key, value)
        row()
        row('DADOS DIÁRIOS (UTC)')
        row('Dia UTC', 'Reproduções iniciadas', 'Acessos QR', 'Resgates registados')
        for d in report['diario']:
            row(d['data'], d['reproducoes'], d['leituras'], d['resgates'])
        row()
        row('COMPARAÇÃO DE CAMPANHAS')
        row('Campanha ID', 'Campanha', 'Anunciante', 'Prioridade', 'Atribuídos',
            'Contratados', 'Reproduções', 'Acessos QR', 'Resgates')
        for c in report['campanhas']:
            row(c['id'], c['nome'], c['anunciante'], c['peso_v13'], c['atribuidos'],
                c['carros_contratados'], c['reproducoes'], c['leituras'], c['resgates'])
        row()
        row('REPRODUÇÕES POR ZONA (SEM COORDENADAS INDIVIDUAIS)')
        row('Zona', 'Reproduções iniciadas')
        for z in report['zonas']:
            row(z['nome'], z['reproducoes'])
        row()
        row('REPRODUÇÕES POR HORA — EUROPE/LISBON')
        row('Hora local', 'Reproduções iniciadas')
        for h in report['horario']:
            row(h['hora'], h['reproducoes'])
        row()
        row('Nota', 'Reproduções são eventos técnicos, QR são acessos e resgates dependem de confirmação. Não representam audiência comprovada nem vendas.')
        return Response('\ufeff' + buff.getvalue(), content_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': ('attachment; filename=rotaads_v1_3_1_anunciante.csv' if only_company
                                                         else 'attachment; filename=rotaads_v1_3_1_dashboard.csv'),
                                 'Cache-Control': 'no-store'})

    @app.get('/admin/inteligencia')
    @admin_required
    def admin_intelligence():
        data = dashboard_data(get_db(), read_days())
        return render_template('intelligence_v131.html', report=data, role='admin')

    @app.get('/admin/inteligencia.csv')
    @admin_required
    def admin_intelligence_csv():
        return csv_report(dashboard_data(get_db(), read_days()))

    def pdf_response(report, admin=False):
        pdf = build_dashboard_pdf(report, admin=admin)
        filename = ('rotaads_dashboard_admin_' if admin else 'rotaads_dashboard_anunciante_') + str(report['dias']) + 'dias.pdf'
        return Response(pdf, mimetype='application/pdf', headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Cache-Control': 'private, no-store',
            'X-Content-Type-Options': 'nosniff',
        })

    @app.get('/admin/inteligencia.pdf')
    @admin_required
    def admin_intelligence_pdf():
        return pdf_response(dashboard_data(get_db(), read_days()), admin=True)

    @app.get('/anunciante/inteligencia.pdf')
    @advertiser_required
    def advertiser_intelligence_pdf():
        return pdf_response(dashboard_data(get_db(), read_days(), current_advertiser()['id']))

    @app.get('/admin/inteligencia/imprimir')
    @admin_required
    def admin_intelligence_print():
        return render_template('intelligence_v131.html', report=dashboard_data(get_db(), read_days()),
                               role='admin', print_view=True)

    @app.get('/anunciante/inteligencia')
    @advertiser_required
    def advertiser_intelligence():
        return render_template('intelligence_v131.html',
                               report=dashboard_data(get_db(), read_days(), current_advertiser()['id']),
                               role='anunciante')

    @app.get('/anunciante/inteligencia.csv')
    @advertiser_required
    def advertiser_intelligence_csv():
        return csv_report(dashboard_data(get_db(), read_days(), current_advertiser()['id']), True)

    @app.get('/anunciante/inteligencia/imprimir')
    @advertiser_required
    def advertiser_intelligence_print():
        return render_template('intelligence_v131.html',
                               report=dashboard_data(get_db(), read_days(), current_advertiser()['id']),
                               role='anunciante', print_view=True)
