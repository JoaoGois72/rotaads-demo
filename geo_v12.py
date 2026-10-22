"""RotaAds V1.2: zonas circulares, localização opt-in, mapa e métricas.

Sem dependências GIS: cálculo geodésico Haversine. Guarda só a última
posição do ecrã; não guarda trajetos no histórico das reproduções.
"""
import csv
import io
import math
from datetime import datetime, timedelta, timezone

from flask import Response, abort, flash, jsonify, redirect, render_template, request, url_for

_query_all = None


def fresh_position(device, max_age=120):
    """Obtém coordenadas apenas se a posição for recente e válida."""
    if not device['ultima_localizacao_em'] or device['ultima_lat'] is None or device['ultima_lon'] is None:
        return None
    try:
        date = datetime.fromisoformat(device['ultima_localizacao_em'])
        age = (datetime.now(timezone.utc) - date).total_seconds()
        lat, lon = float(device['ultima_lat']), float(device['ultima_lon'])
        accuracy = device['ultima_precisao_m']
        if not (-5 <= age <= max_age and -90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        if accuracy is not None and (not math.isfinite(float(accuracy)) or float(accuracy) > 1500):
            return None
        return lat, lon
    except (ValueError, TypeError, OverflowError):
        return None


def distance_metres(lat1, lon1, lat2, lon2):
    a1, a2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lat2 - lat1)
    dg = math.radians(lon2 - lon1)
    h = math.sin(dl/2)**2 + math.cos(a1)*math.cos(a2)*math.sin(dg/2)**2
    return 6371000 * 2 * math.atan2(math.sqrt(max(0,h)), math.sqrt(max(0, 1-h)))


def in_zone(position, zone):
    if position is None:
        return False
    return distance_metres(*position, zone['latitude'], zone['longitude']) <= zone['raio_m']


def resolve_campaign_zone(campaign_id, device):
    """Resultado (reproduzível, zona). Sem zonas: campanha normal da V1.1.

    Campanha com uma ou mais zonas atribuídas só toca se GPS recente
    estiver dentro de uma das zonas ativas. As zonas inativas não autorizam
    reprodução. Prioridade maior vence sobre zonas sobrepostas.
    """
    rules = _query_all('''SELECT z.* FROM campanhas_zonas cz JOIN zonas z ON z.id=cz.zona_id
                          WHERE cz.campanha_id=? ORDER BY z.prioridade DESC, z.id ASC''', (campaign_id,))
    position = fresh_position(device)
    if rules:
        for zone in rules:
            if zone['ativo'] and in_zone(position, zone):
                return True, zone
        return False, None
    # Campanhas não segmentadas continuam a funcionar mesmo sem permissão GPS.
    if position:
        zones = _query_all('SELECT * FROM zonas WHERE ativo=1 ORDER BY prioridade DESC, id ASC')
        for zone in zones:
            if in_zone(position, zone):
                return True, zone
    return True, None


def parse_zone(values):
    nome = (values.get('nome') or '').strip()
    cidade = (values.get('cidade') or '').strip()
    try:
        lat = float(values['latitude'].replace(',', '.'))
        lon = float(values['longitude'].replace(',', '.'))
        radius = int(values['raio_m'])
        priority = int(values.get('prioridade') or 0)
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError('Coordenadas, raio e prioridade devem ser números válidos.')
    if not nome or len(nome) > 100 or len(cidade) > 90 or not all(math.isfinite(n) for n in (lat,lon)):
        raise ValueError('Informe um nome e coordenadas válidos.')
    if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 100 <= radius <= 30000 and -100 <= priority <= 100):
        raise ValueError('Latitude -90 a 90; longitude -180 a 180; raio 100 a 30000 m; prioridade -100 a 100.')
    return nome, cidade, lat, lon, radius, priority


def register_geo_routes(app, get_db, one, all_rows, admin_required, verify_csrf, now_iso,
                        advertiser_required, campaign_owned):
    global _query_all
    _query_all = all_rows

    @app.get('/admin/zonas')
    @admin_required
    def admin_zones():
        zones = all_rows('''SELECT z.*,
            (SELECT COUNT(*) FROM campanhas_zonas cz WHERE cz.zona_id=z.id) campanhas
            FROM zonas z ORDER BY z.ativo DESC, z.prioridade DESC, z.id DESC''')
        return render_template('admin_zones.html', zones=zones)

    @app.post('/admin/zonas/nova')
    @admin_required
    def admin_zone_create():
        verify_csrf()
        try:
            fields = parse_zone(request.form)
        except ValueError as err:
            flash(str(err), 'error')
            return redirect(url_for('admin_zones'))
        db = get_db()
        db.execute('''INSERT INTO zonas(nome,cidade,latitude,longitude,raio_m,prioridade,criado_em)
            VALUES(?,?,?,?,?,?,?)''', (*fields, now_iso()))
        db.commit()
        flash('Zona publicitária criada.', 'success')
        return redirect(url_for('admin_zones'))

    @app.post('/admin/zonas/<int:id>/editar')
    @admin_required
    def admin_zone_edit(id):
        verify_csrf()
        if not one('SELECT id FROM zonas WHERE id=?', (id,)):
            abort(404)
        try:
            fields = parse_zone(request.form)
        except ValueError as err:
            flash(str(err), 'error')
            return redirect(url_for('admin_zones'))
        db = get_db()
        db.execute('''UPDATE zonas SET nome=?,cidade=?,latitude=?,longitude=?,raio_m=?,prioridade=?
                      WHERE id=?''', (*fields, id))
        db.commit()
        flash('Zona atualizada.', 'success')
        return redirect(url_for('admin_zones'))

    @app.post('/admin/zonas/<int:id>/alternar')
    @admin_required
    def admin_zone_toggle(id):
        verify_csrf()
        db = get_db()
        cur = db.execute('UPDATE zonas SET ativo=1-ativo WHERE id=?', (id,))
        if not cur.rowcount:
            abort(404)
        db.commit()
        flash('Estado da zona atualizado.', 'success')
        return redirect(url_for('admin_zones'))

    @app.post('/admin/campanhas/<int:id>/zonas')
    @admin_required
    def admin_campaign_zones(id):
        verify_csrf()
        if not one('SELECT id FROM campanhas WHERE id=?', (id,)):
            abort(404)
        zone_ids = request.form.getlist('zona_ids')
        try:
            selected = sorted(set(int(x) for x in zone_ids))
        except (ValueError, TypeError):
            abort(400)
        if len(selected) > 100:
            abort(400)
        if selected:
            existing = all_rows('SELECT id FROM zonas WHERE id IN ('+','.join('?'*len(selected))+')', selected)
            if len(existing) != len(selected):
                abort(400)
        db = get_db()
        with db:
            db.execute('DELETE FROM campanhas_zonas WHERE campanha_id=?', (id,))
            db.executemany('INSERT INTO campanhas_zonas(campanha_id,zona_id) VALUES(?,?)',
                           ((id, z) for z in selected))
        flash('Zonas associadas. Sem zonas selecionadas, a campanha mantém-se livre.', 'success')
        return redirect(url_for('admin_campaign_detail', id=id))

    @app.get('/admin/mapa')
    @admin_required
    def admin_map():
        return render_template('admin_map.html')

    @app.get('/api/admin/mapa')
    @admin_required
    def api_admin_map():
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(timespec='seconds')
        devices = all_rows('''SELECT id,nome,parceiro,cidade,ativo,ultimo_sinal,
            ultima_lat,ultima_lon,ultima_precisao_m,ultima_localizacao_em
            FROM dispositivos ORDER BY id''')
        entries = []
        total_online = 0
        for d in devices:
            online = bool(d['ativo'] and d['ultimo_sinal'] and d['ultimo_sinal'] >= cutoff)
            if online:
                total_online += 1
            position = fresh_position(d) if online else None
            entries.append({'id': d['id'], 'nome': d['nome'], 'parceiro': d['parceiro'],
                'cidade': d['cidade'], 'online': online,
                'lat': position[0] if position else None, 'lon': position[1] if position else None,
                'precisao_m': d['ultima_precisao_m'] if position else None,
                'gps_recente': bool(position), 'ultimo_sinal': d['ultimo_sinal']})
        zones = [dict(z) for z in all_rows('SELECT id,nome,cidade,latitude,longitude,raio_m,prioridade FROM zonas WHERE ativo=1 ORDER BY prioridade DESC,id')]
        return jsonify({'dispositivos': entries, 'zonas': zones, 'online': total_online,
                        'com_gps': sum(1 for d in entries if d['gps_recente']),
                        'atualizado_em': now_iso(), 'criterio_online_segundos': 120})

    @app.get('/api/anunciante/campanhas/<int:id>/zonas')
    @advertiser_required
    def api_advertiser_zones(id):
        campaign_owned(id)
        rows = all_rows('''SELECT z.nome AS zona, COUNT(*) AS reproducoes
            FROM exibicoes e JOIN zonas z ON e.zona_id=z.id
            WHERE e.campanha_id=? GROUP BY e.zona_id ORDER BY reproducoes DESC, z.nome''', (id,))
        no_geo = one('SELECT COUNT(*) n FROM exibicoes WHERE campanha_id=? AND zona_id IS NULL', (id,))['n']
        return jsonify({'zonas': [{'nome': r['zona'], 'reproducoes': r['reproducoes']} for r in rows],
                        'sem_zona': no_geo, 'atualizado_em': now_iso()})

    @app.get('/anunciante/campanhas/<int:id>/zonas.csv')
    @advertiser_required
    def advertiser_zones_csv(id):
        c = campaign_owned(id)
        rows = all_rows('''SELECT z.nome AS zona, COUNT(*) AS reproducoes
            FROM exibicoes e JOIN zonas z ON e.zona_id=z.id
            WHERE e.campanha_id=? GROUP BY e.zona_id ORDER BY reproducoes DESC,z.nome''', (id,))
        count_other = one('SELECT COUNT(*) n FROM exibicoes WHERE campanha_id=? AND zona_id IS NULL', (id,))['n']
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Campanha', c['nome']])
        writer.writerow(['Zona', 'Reproduções iniciadas'])
        for r in rows:
            writer.writerow([r['zona'], r['reproducoes']])
        writer.writerow(['Sem zona identificada', count_other])
        return Response('\ufeff'+output.getvalue(),mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition':f'attachment; filename=rotaads_campanha_{id}_zonas.csv'})
