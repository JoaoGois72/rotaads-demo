"""Administração e métricas V1.3, sem exibir localização individual ao anunciante."""
import csv
import io
import secrets
from datetime import datetime, timedelta, timezone
from flask import Response, abort, flash, jsonify, redirect, render_template, request, url_for
from motor_v13 import DIAS, parse_schedule, summarize_hours


def register_v13_routes(app, get_db, one, all_rows, admin_required, verify_csrf,
                        advertiser_required, campaign_owned, now_iso):
    @app.post('/admin/ecra/<int:id>/otimizacao')
    @admin_required
    def admin_device_optimization(id):
        verify_csrf()
        if not one('SELECT id FROM dispositivos WHERE id=?', (id,)):
            abort(404)
        enabled = request.form.get('ativo') == '1'
        db = get_db()
        db.execute('UPDATE dispositivos SET otimizacao_ativa=? WHERE id=?', (int(enabled), id))
        db.commit()
        flash('Modo de otimização atualizado. Nenhuma campanha foi alterada.', 'success')
        return redirect(url_for('admin_devices'))

    @app.post('/admin/ecra/<int:id>/renovar-token')
    @admin_required
    def admin_device_reset_token(id):
        verify_csrf()
        if not one('SELECT id FROM dispositivos WHERE id=?', (id,)):
            abort(404)
        db = get_db()
        db.execute('UPDATE dispositivos SET token=? WHERE id=?', (secrets.token_urlsafe(30), id))
        db.commit()
        flash('Token renovado: atualize o endereço do player no tablet. O link anterior deixou de funcionar.', 'success')
        return redirect(url_for('admin_devices'))

    @app.post('/admin/campanhas/<int:id>/inteligencia')
    @admin_required
    def admin_campaign_optimizer(id):
        verify_csrf()
        if not one('SELECT id FROM campanhas WHERE id=?', (id,)):
            abort(404)
        try:
            peso = int(request.form.get('peso_v13', '3'))
            if not 1 <= peso <= 5:
                raise ValueError('A prioridade deve estar entre 1 e 5.')
            start, end, days = parse_schedule(request.form.get('horario_inicio'),
                                              request.form.get('horario_fim'),
                                              request.form.getlist('dias_semana'))
        except (TypeError, ValueError) as error:
            flash(str(error), 'error')
            return redirect(url_for('admin_campaign_detail', id=id))
        db = get_db()
        db.execute('''UPDATE campanhas SET peso_v13=?,horario_inicio=?,horario_fim=?,dias_semana=?
                      WHERE id=?''', (peso, start, end, days, id))
        db.commit()
        flash('Regras de prioridade e horários atualizadas (hora de Portugal).', 'success')
        return redirect(url_for('admin_campaign_detail', id=id))

    @app.get('/admin/otimizacao')
    @admin_required
    def admin_optimization():
        cutoff = (datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec='seconds')
        rows = all_rows('''SELECT c.id,c.nome,c.anunciante,c.peso_v13,c.horario_inicio,
               c.horario_fim,c.dias_semana,c.ativo,
               (SELECT COUNT(*) FROM exibicoes e WHERE e.campanha_id=c.id AND e.criado_em>=?) AS reproducoes_7d,
               (SELECT COUNT(*) FROM atribuicoes a JOIN dispositivos d ON d.id=a.dispositivo_id
                   WHERE a.campanha_id=c.id AND d.otimizacao_ativa=1) AS ecra_inteligente
               FROM campanhas c ORDER BY c.id DESC''', (cutoff,))
        summary = one('''SELECT COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN otimizacao_ativa=1 THEN 1 ELSE 0 END),0) AS otimizados
            FROM dispositivos''')
        return render_template('admin_optimization.html', rows=rows, summary=summary)

    @app.get('/api/anunciante/campanhas/<int:id>/horarios')
    @advertiser_required
    def api_advertiser_hours(id):
        campaign_owned(id)
        cutoff = (datetime.now(timezone.utc)-timedelta(days=30)).isoformat(timespec='seconds')
        stamps = all_rows('SELECT criado_em FROM exibicoes WHERE campanha_id=? AND criado_em>=?',
                          (id, cutoff))
        totals = summarize_hours([r['criado_em'] for r in stamps])
        return jsonify({'periodo_dias':30, 'fuso_horario':'Europe/Lisbon',
                        'horas':[{'hora':i,'reproducoes':n} for i,n in enumerate(totals)],
                        'total':sum(totals), 'atualizado_em':now_iso()})

    @app.get('/anunciante/campanhas/<int:id>/horarios.csv')
    @advertiser_required
    def advertiser_hours_csv(id):
        c = campaign_owned(id)
        cutoff = (datetime.now(timezone.utc)-timedelta(days=30)).isoformat(timespec='seconds')
        stamps = all_rows('SELECT criado_em FROM exibicoes WHERE campanha_id=? AND criado_em>=?',
                          (id,cutoff))
        values = summarize_hours([r['criado_em'] for r in stamps])
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['Campanha',c['nome']])
        writer.writerow(['Fuso horário','Europe/Lisbon'])
        writer.writerow(['Hora local','Reproduções iniciadas - últimos 30 dias'])
        for i,n in enumerate(values):
            writer.writerow([f'{i:02d}:00', n])
        return Response('\ufeff'+out.getvalue(), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition':f'attachment; filename=rotaads_campanha_{id}_horarios.csv'})
