"""RotaAds V1.3.1: métricas agregadas, sem rastrear trajetos ou passageiros.

As reproduções são inícios técnicos enviados pelo player; QR = acessos à oferta;
resgates = confirmações registadas. Não constituem prova de audiência/venda.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LISBON = ZoneInfo('Europe/Lisbon')
PERIODS = {7, 30, 90}


def period_days(raw):
    try:
        days = int(raw)
    except (TypeError, ValueError):
        raise ValueError('Período inválido.')
    if days not in PERIODS:
        raise ValueError('Período permitido: 7, 30 ou 90 dias.')
    return days


def csv_safe(value):
    """Evita interpretação como fórmula no Excel/LibreOffice."""
    value = '' if value is None else str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value


def dashboard_data(db, days=30, advertiser_id=None, current=None):
    days = period_days(days)
    current = current or datetime.now(timezone.utc)
    start_day = current.date() - timedelta(days=days - 1)
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    cutoff = start.isoformat(timespec='seconds')
    online_cutoff = (current - timedelta(seconds=120)).isoformat(timespec='seconds')
    date_today = current.date().isoformat()
    where = ' WHERE c.anunciante_id=? ' if advertiser_id is not None else ''
    params = (advertiser_id,) if advertiser_id is not None else ()

    campaigns = [dict(r) for r in db.execute('''
        SELECT c.id,c.nome,c.anunciante,c.anunciante_id,c.ativo,c.data_inicio,c.data_fim,
               c.carros_contratados,c.cupao_ativo,c.peso_v13,
               (SELECT COUNT(*) FROM atribuicoes a WHERE a.campanha_id=c.id) atribuidos,
               (SELECT COUNT(*) FROM exibicoes e WHERE e.campanha_id=c.id AND e.criado_em>=?) reproducoes,
               (SELECT COUNT(*) FROM leituras_qr q WHERE q.campanha_id=c.id AND q.criado_em>=?) leituras,
               (SELECT COUNT(*) FROM resgates_cupao r WHERE r.campanha_id=c.id AND r.criado_em>=?) resgates
        FROM campanhas c ''' + where + ' ORDER BY c.id', (cutoff, cutoff, cutoff) + params)]
    for c in campaigns:
        c['em_curso'] = bool(c['ativo'] and (not c['data_inicio'] or c['data_inicio'] <= date_today)
                             and (not c['data_fim'] or c['data_fim'] >= date_today))
    # Associar contagens e zonas apenas através das campanhas às quais há permissão.
    if advertiser_id is None:
        totals_screen = db.execute('''SELECT COUNT(*) total,
            COALESCE(SUM(CASE WHEN ativo=1 AND ultimo_sinal>=? THEN 1 ELSE 0 END),0) online
            FROM dispositivos''', (online_cutoff,)).fetchone()
    else:
        totals_screen = db.execute('''SELECT COUNT(DISTINCT d.id) total,
            COUNT(DISTINCT CASE WHEN d.ativo=1 AND d.ultimo_sinal>=? THEN d.id END) online
            FROM dispositivos d JOIN atribuicoes a ON a.dispositivo_id=d.id
            JOIN campanhas c ON c.id=a.campanha_id WHERE c.anunciante_id=?''',
            (online_cutoff, advertiser_id)).fetchone()

    totals = {
        'campanhas': len(campaigns),
        'campanhas_ativas': sum(1 for c in campaigns if c['em_curso']),
        'carros_contratados': sum(c['carros_contratados'] for c in campaigns),
        'ecra_total': int(totals_screen['total']),
        'ecra_online': int(totals_screen['online']),
        'reproducoes': sum(c['reproducoes'] for c in campaigns),
        'leituras': sum(c['leituras'] for c in campaigns),
        'resgates': sum(c['resgates'] for c in campaigns),
    }
    totals['leituras_por_100_reproducoes'] = round(100 * totals['leituras'] / totals['reproducoes'], 1) if totals['reproducoes'] else None
    totals['resgates_por_100_leituras'] = round(100 * totals['resgates'] / totals['leituras'], 1) if totals['leituras'] else None
    totals['taxa_online'] = round(100 * totals['ecra_online'] / totals['ecra_total'], 1) if totals['ecra_total'] else None

    dates = [(current.date() - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    daily = {d: {'data': d, 'reproducoes': 0, 'leituras': 0, 'resgates': 0} for d in dates}
    hourly = [{'hora': f'{i:02d}:00', 'reproducoes': 0} for i in range(24)]

    # As séries são UTC por dia, hora local de Portugal (incluindo horário de verão).
    # Consulta filtrada na origem, sem IDs de ecrãs nem coordenadas no resultado.
    for table, key in [('exibicoes','reproducoes'), ('leituras_qr','leituras'), ('resgates_cupao','resgates')]:
        if advertiser_id is None:
            sql = f'SELECT x.criado_em FROM {table} x WHERE x.criado_em>=?'
            values = (cutoff,)
        else:
            sql = f'''SELECT x.criado_em FROM {table} x JOIN campanhas c
                      ON c.id=x.campanha_id WHERE x.criado_em>=? AND c.anunciante_id=?'''
            values = (cutoff, advertiser_id)
        for stamp in db.execute(sql, values):
            try:
                dt = datetime.fromisoformat(stamp['criado_em']).astimezone(timezone.utc)
                utc_date = dt.date().isoformat()
                if utc_date in daily:
                    daily[utc_date][key] += 1
                if key == 'reproducoes':
                    hourly[dt.astimezone(LISBON).hour]['reproducoes'] += 1
            except (ValueError, TypeError):
                continue

    zones_sql = '''SELECT COALESCE(z.nome,'Sem zona identificada') nome, COUNT(*) reproducoes
                  FROM exibicoes e LEFT JOIN zonas z ON z.id=e.zona_id'''
    if advertiser_id is None:
        zones_sql += ' WHERE e.criado_em>=? GROUP BY COALESCE(z.id,-1) ORDER BY reproducoes DESC, nome LIMIT 10'
        zones_args = (cutoff,)
    else:
        zones_sql += ''' JOIN campanhas c ON c.id=e.campanha_id
                 WHERE e.criado_em>=? AND c.anunciante_id=?
                 GROUP BY COALESCE(z.id,-1) ORDER BY reproducoes DESC, nome LIMIT 10'''
        zones_args = (cutoff, advertiser_id)
    # Note: LEFT JOIN zonas precedes JOIN campanhas, both are joined on e.
    zones = [dict(r) for r in db.execute(zones_sql, zones_args)]
    campaigns.sort(key=lambda c: (-c['reproducoes'], c['nome'].lower()))

    suggestions = []
    if not campaigns:
        suggestions.append(('Começar a medir', 'Crie ou associe uma campanha para gerar indicadores no painel.'))
    else:
        if totals['ecra_total'] and totals['ecra_online'] == 0:
            suggestions.append(('Verificar ligação', 'Nenhum ecrã atribuído está online. Confirme a ligação dos players e os sinais de atividade.'))
        unassigned = sum(1 for c in campaigns if c['em_curso'] and c['atribuidos'] == 0)
        if unassigned:
            suggestions.append(('Campanhas sem distribuição', f'{unassigned} campanha(s) em curso não têm ecrãs atribuídos.'))
        if totals['reproducoes'] >= 100 and not totals['leituras']:
            suggestions.append(('Avaliar QR Code', 'Existem pelo menos 100 reproduções registadas e nenhuma leitura QR no período. Confirme se o cupão é relevante e legível.'))
        if totals['reproducoes'] >= 50:
            peak = max(hourly, key=lambda h: h['reproducoes'])
            suggestions.append(('Horário com mais atividade', f"O horário de {peak['hora']} registou mais inícios de reprodução (hora de Portugal). Compare-o com a procura real antes de alterar os horários."))
        if totals['reproducoes'] == 0:
            suggestions.append(('Ainda sem reproduções', 'Confirme que a campanha está ativa, atribuída e elegível para a localização e horário atuais.'))
    return {
        'dias': days, 'inicio_utc': cutoff, 'atualizado_em': current.isoformat(timespec='seconds'),
        'resumo': totals, 'diario': list(daily.values()), 'horario': hourly,
        'zonas': zones, 'campanhas': campaigns, 'sugestoes': suggestions[:4],
        'ambito': 'anunciante' if advertiser_id is not None else 'admin',
    }
