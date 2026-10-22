"""RotaAds V1.4 — Gestão de frotas, mantendo publicidade e analytics anteriores.

Executar: pip install -r requirements.txt && python app.py
Alterar SECRET_KEY, ADMIN_PASSWORD e SITE_URL antes de publicar.
"""
import csv
import io
import json
import math
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from contextlib import closing
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from dotenv import load_dotenv
from flask import (
    Flask, Response, abort, flash, g, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from motor_v13 import schedule_allowed, weighted_playlist

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
app = Flask(__name__)
# Credenciais persistentes e obrigatórias quando exposto pela internet.
HOSTED_DEMO = os.getenv('DEMO_MODE', '') == '1'
if HOSTED_DEMO and not all(os.getenv(k) for k in ('SECRET_KEY', 'ADMIN_PASSWORD', 'DEMO_ACCESS_PASSWORD', 'DEMO_ADVERTISER_PASSWORD')):
    raise RuntimeError('Faltam SECRET_KEY, ADMIN_PASSWORD, DEMO_ACCESS_PASSWORD ou DEMO_ADVERTISER_PASSWORD no Render.')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '80')) * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = (os.getenv('SITE_URL') or os.getenv('RENDER_EXTERNAL_URL', '')).startswith('https://')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
APP_NAME = os.getenv('APP_NAME', 'RotaAds')
DATABASE = Path(os.getenv('DATABASE_PATH', str(BASE / 'instance' / 'rotaads.sqlite3')))
UPLOAD_FOLDER = Path(os.getenv('UPLOAD_FOLDER', str(BASE / 'uploads')))
DATABASE.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
MEDIA_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'mp4', 'webm'}
FORMS = {
    'anunciante': 'Empresa que quer anunciar',
    'agencia': 'Agência de publicidade',
    'frota': 'Frota TVDE',
    'motorista': 'Motorista individual',
}
STATUS = {'novo': 'Novo', 'contactado': 'Contactado', 'proposta': 'Proposta enviada', 'fechado': 'Fechado'}
ADMIN_HASH = generate_password_hash(os.getenv('ADMIN_PASSWORD')) if os.getenv('ADMIN_PASSWORD') else ''


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def get_db():
    if 'db' not in g:
        db = sqlite3.connect(str(DATABASE), timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=20000')
        g.db = db
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        # Atualização não destrutiva: preserva dados e produz um backup ANTES da migração.
        existing = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='campanhas'").fetchone()
        if existing:
            cols = {c['name'] for c in db.execute('PRAGMA table_info(campanhas)').fetchall()}
            if 'anunciante_id' not in cols:
                backup_dir = DATABASE.parent / 'backups'
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_file = backup_dir / ('rotaads_pre_v1_1_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
                with sqlite3.connect(str(backup_file)) as dst:
                    db.backup(dst)
        # V1.2: backup consistente ANTES de qualquer alteração no banco V1.1.
        device_table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dispositivos'").fetchone()
        if device_table:
            geo_cols = {row['name'] for row in db.execute('PRAGMA table_info(dispositivos)')}
            if 'ultima_localizacao_em' not in geo_cols:
                backup_dir = DATABASE.parent / 'backups'
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_file = backup_dir / ('rotaads_pre_v1_2_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
                with sqlite3.connect(str(backup_file)) as dst:
                    db.backup(dst)
        db.executescript('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, nome TEXT NOT NULL,
            email TEXT NOT NULL, empresa TEXT NOT NULL, cidade TEXT NOT NULL,
            carros INTEGER NOT NULL CHECK(carros > 0), estado TEXT NOT NULL DEFAULT 'novo',
            criado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS campanhas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
            anunciante TEXT NOT NULL, cidade TEXT NOT NULL DEFAULT '',
            carros_contratados INTEGER NOT NULL CHECK(carros_contratados > 0),
            ativo INTEGER NOT NULL DEFAULT 1, data_inicio TEXT, data_fim TEXT,
            ficheiro TEXT, tipo_media TEXT, duracao_seg INTEGER NOT NULL DEFAULT 12,
            cupao_ativo INTEGER NOT NULL DEFAULT 0,
            cupao_codigo TEXT NOT NULL DEFAULT '', cupao_descricao TEXT NOT NULL DEFAULT '',
            cupao_url TEXT NOT NULL DEFAULT '', criado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dispositivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
            parceiro TEXT NOT NULL DEFAULT '', cidade TEXT NOT NULL DEFAULT '',
            token TEXT NOT NULL UNIQUE, ativo INTEGER NOT NULL DEFAULT 1,
            ultimo_sinal TEXT, ultima_lat REAL, ultima_lon REAL,
            criado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS atribuicoes (
            dispositivo_id INTEGER NOT NULL REFERENCES dispositivos(id) ON DELETE CASCADE,
            campanha_id INTEGER NOT NULL REFERENCES campanhas(id) ON DELETE CASCADE,
            PRIMARY KEY(dispositivo_id, campanha_id));
        CREATE TABLE IF NOT EXISTS exibicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dispositivo_id INTEGER NOT NULL REFERENCES dispositivos(id),
            campanha_id INTEGER NOT NULL REFERENCES campanhas(id), criado_em TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_exibicoes_campanha ON exibicoes(campanha_id, criado_em);
        CREATE TABLE IF NOT EXISTS leituras_qr (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campanha_id INTEGER NOT NULL REFERENCES campanhas(id), criado_em TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS resgates_cupao (
            id INTEGER PRIMARY KEY AUTOINCREMENT, campanha_id INTEGER NOT NULL REFERENCES campanhas(id),
            referencia TEXT NOT NULL DEFAULT '', criado_em TEXT NOT NULL);
        ''')
        # Migrar a V1.0 sem eliminar campanhas, dispositivos ou reproduções existentes.
        cols = {c['name'] for c in db.execute('PRAGMA table_info(campanhas)').fetchall()}
        if 'anunciante_id' not in cols:
            db.execute('ALTER TABLE campanhas ADD COLUMN anunciante_id INTEGER REFERENCES anunciantes(id)')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS anunciantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            empresa TEXT NOT NULL,
            email TEXT NOT NULL COLLATE NOCASE UNIQUE,
            senha_hash TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_campanhas_anunciante ON campanhas(anunciante_id);
        CREATE INDEX IF NOT EXISTS idx_atribuicoes_campanha ON atribuicoes(campanha_id);
        CREATE INDEX IF NOT EXISTS idx_leituras_campanha ON leituras_qr(campanha_id, criado_em);
        CREATE INDEX IF NOT EXISTS idx_resgates_campanha ON resgates_cupao(campanha_id, criado_em);
        ''')
        # Colunas adicionais opcionais e não destrutivas.
        device_cols = {row['name'] for row in db.execute('PRAGMA table_info(dispositivos)')}
        if 'ultima_precisao_m' not in device_cols:
            db.execute('ALTER TABLE dispositivos ADD COLUMN ultima_precisao_m REAL')
        if 'ultima_localizacao_em' not in device_cols:
            db.execute('ALTER TABLE dispositivos ADD COLUMN ultima_localizacao_em TEXT')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS zonas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
            cidade TEXT NOT NULL DEFAULT '', latitude REAL NOT NULL,
            longitude REAL NOT NULL, raio_m INTEGER NOT NULL CHECK(raio_m BETWEEN 100 AND 30000),
            prioridade INTEGER NOT NULL DEFAULT 0, ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS campanhas_zonas (
            campanha_id INTEGER NOT NULL REFERENCES campanhas(id) ON DELETE CASCADE,
            zona_id INTEGER NOT NULL REFERENCES zonas(id) ON DELETE CASCADE,
            PRIMARY KEY(campanha_id,zona_id)
        );
        CREATE INDEX IF NOT EXISTS idx_campanhas_zonas_zona ON campanhas_zonas(zona_id);
        ''')
        play_cols = {row['name'] for row in db.execute('PRAGMA table_info(exibicoes)')}
        if 'zona_id' not in play_cols:
            db.execute('ALTER TABLE exibicoes ADD COLUMN zona_id INTEGER REFERENCES zonas(id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_exibicoes_zona ON exibicoes(zona_id, campanha_id, criado_em)')
        # V1.3: backup da V1.2 antes da primeira alteração de esquema.
        v13_campaign_cols = {row['name'] for row in db.execute('PRAGMA table_info(campanhas)')}
        v13_device_cols = {row['name'] for row in db.execute('PRAGMA table_info(dispositivos)')}
        if 'peso_v13' not in v13_campaign_cols or 'otimizacao_ativa' not in v13_device_cols:
            backup_dir = DATABASE.parent / 'backups'
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_file = backup_dir / ('rotaads_pre_v1_3_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.sqlite3')
            db.commit()
            with closing(sqlite3.connect(str(backup_file))) as dst:
                db.backup(dst)
        for name, decl in (
            ('peso_v13', 'INTEGER NOT NULL DEFAULT 3'),
            ('horario_inicio', "TEXT NOT NULL DEFAULT ''"),
            ('horario_fim', "TEXT NOT NULL DEFAULT ''"),
            ('dias_semana', "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in v13_campaign_cols:
                db.execute(f'ALTER TABLE campanhas ADD COLUMN {name} {decl}')
        if 'otimizacao_ativa' not in v13_device_cols:
            db.execute('ALTER TABLE dispositivos ADD COLUMN otimizacao_ativa INTEGER NOT NULL DEFAULT 0')
        db.commit()


def one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def all_rows(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(24)
    return session['_csrf']


@app.context_processor
def context():
    return {'app_name': APP_NAME, 'form_types': FORMS, 'statuses': STATUS, 'csrf_token': csrf_token, 'demo_mode': HOSTED_DEMO}


def verify_csrf():
    expected = session.get('_csrf', '')
    value = request.form.get('csrf_token', '')
    if not expected or not secrets.compare_digest(expected, value):
        abort(400, 'Formulário expirado. Atualize a página e tente de novo.')


def is_admin():
    return session.get('admin_logged') is True


def admin_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not is_admin():
            return redirect(url_for('admin_login', next=request.path))
        return fn(*args, **kwargs)
    return inner


def safe_next(value):
    return value if value and value.startswith('/admin') and not value.startswith('//') else url_for('admin_dashboard')


def within_dates(c):
    today = datetime.now(timezone.utc).date().isoformat()
    return bool(c['ativo']) and (not c['data_inicio'] or c['data_inicio'] <= today) and (not c['data_fim'] or c['data_fim'] >= today)


def online_count():
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(timespec='seconds')
    return one('SELECT COUNT(*) AS n FROM dispositivos WHERE ativo=1 AND ultimo_sinal>=?', (cutoff,))['n']


def get_device(token):
    d = one('SELECT * FROM dispositivos WHERE token=? AND ativo=1', (token,))
    if not d:
        abort(404)
    return d


def public_base():
    # Configure SITE_URL for correct URLs behind proxies.
    return (os.getenv('SITE_URL') or os.getenv('RENDER_EXTERNAL_URL') or request.host_url.rstrip('/')).rstrip('/')


def valid_https_link(raw):
    if not raw:
        return ''
    u = urlparse(raw)
    if u.scheme not in ('https', 'http') or not u.netloc or u.username or u.password:
        raise ValueError('Indique um URL http(s) válido.')
    return raw


@app.get('/healthz')
def healthz():
    # A sondagem do Render não precisa de credenciais.
    return 'ok', 200


@app.before_request
def private_demo_gate():
    if not HOSTED_DEMO or request.path == '/healthz':
        return None
    # Autenticação HTTP Basic para o ambiente de avaliação, independente
    # da sessão administrativa e do portal do anunciante.
    auth = request.authorization
    expected = os.getenv('DEMO_ACCESS_PASSWORD', '')
    if auth and (secrets.compare_digest(auth.username or '', 'visitante')
                 and secrets.compare_digest(auth.password or '', expected)):
        return None
    return Response('Acesso à demonstração RotaAds. Introduza as credenciais fornecidas.',
                    status=401, headers={'WWW-Authenticate': 'Basic realm="RotaAds Demo"',
                                         'Cache-Control': 'no-store'})


@app.after_request
def add_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if HOSTED_DEMO:
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    if request.path.startswith(('/api/', '/admin', '/anunciante')):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/contacto', methods=['GET', 'POST'])
def contact():
    tipo = request.values.get('tipo', 'anunciante')
    if tipo not in FORMS:
        abort(404)
    if request.method == 'POST':
        verify_csrf()
        if request.form.get('website', ''):  # Honeypot antispam
            return redirect(url_for('thanks'))
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip()
        empresa = request.form.get('empresa', '').strip()
        cidade = request.form.get('cidade', '').strip()
        if not all([nome, email, empresa, cidade]) or len(nome) > 130 or len(empresa) > 140 or len(cidade) > 90 or len(email) > 200 or '@' not in email:
            flash('Preencha corretamente todos os campos.', 'error')
            return render_template('contact.html', tipo=tipo)
        try:
            carros = int(request.form.get('carros', '0'))
            if not 1 <= carros <= 100000:
                raise ValueError
        except ValueError:
            flash('Indique um número de carros válido.', 'error')
            return render_template('contact.html', tipo=tipo)
        if request.form.get('privacidade') != 'sim':
            flash('Confirme que leu a informação de privacidade.', 'error')
            return render_template('contact.html', tipo=tipo)
        db = get_db()
        db.execute('INSERT INTO leads(tipo,nome,email,empresa,cidade,carros,criado_em) VALUES(?,?,?,?,?,?,?)',
                   (tipo, nome, email, empresa, cidade, carros, now_iso()))
        db.commit()
        return redirect(url_for('thanks'))
    return render_template('contact.html', tipo=tipo)


@app.route('/pedido-recebido')
def thanks():
    return render_template('thanks.html')


@app.route('/privacidade')
def privacy():
    return render_template('privacy.html')


@app.route('/admin/entrar', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        verify_csrf()
        username = os.getenv('ADMIN_USERNAME', 'admin')
        submitted = request.form.get('password', '')
        # Compare credentials and never allow blank admin passwords.
        if ADMIN_HASH and secrets.compare_digest(request.form.get('username', ''), username) and check_password_hash(ADMIN_HASH, submitted):
            session.clear()
            session['admin_logged'] = True
            csrf_token()
            return redirect(safe_next(request.args.get('next')))
        flash('Credenciais inválidas ou administrador não configurado.', 'error')
    return render_template('admin_login.html')


@app.post('/admin/sair')
@admin_required
def admin_logout():
    verify_csrf()
    session.clear()
    return redirect(url_for('home'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    total_leads = one('SELECT COUNT(*) AS n FROM leads')['n']
    total_campaigns = one('SELECT COUNT(*) AS n FROM campanhas')['n']
    total_devices = one('SELECT COUNT(*) AS n FROM dispositivos')['n']
    plays = one('SELECT COUNT(*) AS n FROM exibicoes')['n']
    scans = one('SELECT COUNT(*) AS n FROM leituras_qr')['n']
    recent = all_rows('SELECT * FROM leads ORDER BY id DESC LIMIT 6')
    campaigns = all_rows('SELECT c.*, (SELECT COUNT(*) FROM atribuicoes a WHERE a.campanha_id=c.id) AS atribuicoes FROM campanhas c ORDER BY c.id DESC LIMIT 8')
    return render_template('admin_dashboard.html', lead_count=total_leads, campaigns_count=total_campaigns,
                           devices_count=total_devices, online_count=online_count(), plays=plays, scans=scans,
                           recent=recent, campaigns=campaigns, advertisers_count=one('SELECT COUNT(*) AS n FROM anunciantes')['n'])


@app.route('/admin/pedidos')
@admin_required
def admin_leads():
    tipo = request.args.get('tipo', '')
    if tipo and tipo not in FORMS:
        abort(400)
    leads = all_rows('SELECT * FROM leads WHERE (?="" OR tipo=?) ORDER BY id DESC', (tipo, tipo))
    return render_template('admin_leads.html', leads=leads, tipo=tipo)


@app.post('/admin/pedidos/<int:id>/estado')
@admin_required
def lead_status(id):
    verify_csrf()
    state = request.form.get('estado')
    if state not in STATUS:
        abort(400)
    get_db().execute('UPDATE leads SET estado=? WHERE id=?', (state, id))
    get_db().commit()
    return redirect(url_for('admin_leads'))


@app.route('/admin/pedidos.csv')
@admin_required
def export_leads():
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(['ID', 'Tipo', 'Nome', 'E-mail', 'Empresa', 'Cidade', 'Carros', 'Estado', 'Criado em (UTC)'])
    for lead in all_rows('SELECT * FROM leads ORDER BY id DESC'):
        writer.writerow([lead[x] for x in ('id', 'tipo', 'nome', 'email', 'empresa', 'cidade', 'carros', 'estado', 'criado_em')])
    return Response('\ufeff' + stream.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=pedidos_rotaads.csv'})


@app.route('/admin/campanhas')
@admin_required
def admin_campaigns():
    rows = all_rows('''SELECT c.*, (SELECT COUNT(*) FROM atribuicoes a WHERE a.campanha_id=c.id) AS atribuicoes,
        (SELECT COUNT(*) FROM exibicoes p WHERE p.campanha_id=c.id) AS exibicoes,
        (SELECT COUNT(*) FROM leituras_qr q WHERE q.campanha_id=c.id) AS leituras
        FROM campanhas c ORDER BY c.id DESC''')
    return render_template('admin_campaigns.html', campaigns=rows)


@app.route('/admin/campanhas/nova', methods=['GET', 'POST'])
@admin_required
def admin_campaign_new():
    if request.method == 'POST':
        verify_csrf()
        nome = request.form.get('nome', '').strip()
        anunciante = request.form.get('anunciante', '').strip()
        cidade = request.form.get('cidade', '').strip()
        if not nome or not anunciante or len(nome)>120 or len(anunciante)>140 or len(cidade)>90:
            flash('Nome, anunciante e cidade devem ser válidos.', 'error')
            return render_template('admin_campaign_form.html', advertisers=all_rows('SELECT id, empresa, email FROM anunciantes WHERE ativo=1 ORDER BY empresa'))
        try:
            carros = int(request.form.get('carros_contratados', '0'))
            duration = int(request.form.get('duracao_seg', '12'))
            if not (1 <= carros <= 100000 and 5 <= duration <= 600):
                raise ValueError
        except ValueError:
            flash('Quantidade de carros ou duração inválida.', 'error')
            return render_template('admin_campaign_form.html', advertisers=all_rows('SELECT id, empresa, email FROM anunciantes WHERE ativo=1 ORDER BY empresa'))
        start, end = request.form.get('data_inicio') or None, request.form.get('data_fim') or None
        try:
            for d in (start, end):
                if d:
                    datetime.strptime(d, '%Y-%m-%d')
            if start and end and start > end:
                raise ValueError
            url = valid_https_link(request.form.get('cupao_url', '').strip())
        except ValueError:
            flash('Confirme as datas e o endereço web do cupão.', 'error')
            return render_template('admin_campaign_form.html', advertisers=all_rows('SELECT id, empresa, email FROM anunciantes WHERE ativo=1 ORDER BY empresa'))
        media = request.files.get('ficheiro')
        if not media or not media.filename:
            flash('Carregue uma imagem ou vídeo para a campanha.', 'error')
            return render_template('admin_campaign_form.html', advertisers=all_rows('SELECT id, empresa, email FROM anunciantes WHERE ativo=1 ORDER BY empresa'))
        extension = media.filename.rsplit('.', 1)[-1].lower() if '.' in media.filename else ''
        if extension not in MEDIA_EXTENSIONS:
            flash('Ficheiro inválido. Utilize PNG, JPG, WEBP, GIF, MP4 ou WEBM.', 'error')
            return render_template('admin_campaign_form.html', advertisers=all_rows('SELECT id, empresa, email FROM anunciantes WHERE ativo=1 ORDER BY empresa'))
        filename = secrets.token_hex(18) + '.' + extension
        media.save(UPLOAD_FOLDER / filename)
        kind = 'video' if extension in {'mp4', 'webm'} else 'image'
        enable_coupon = request.form.get('cupao_ativo') == 'sim'
        raw_account = request.form.get('anunciante_id', '').strip()
        try:
            advertiser_id = int(raw_account) if raw_account else None
        except ValueError:
            abort(400)
        if advertiser_id and not one('SELECT id FROM anunciantes WHERE id=? AND ativo=1', (advertiser_id,)):
            abort(400, 'Conta de anunciante inválida.')
        db = get_db()
        db.execute('''INSERT INTO campanhas(nome,anunciante,cidade,carros_contratados,
            data_inicio,data_fim,ficheiro,tipo_media,duracao_seg,cupao_ativo,cupao_codigo,
            cupao_descricao,cupao_url,criado_em,anunciante_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (nome, anunciante, cidade, carros, start, end, filename, kind, duration,
             int(enable_coupon), request.form.get('cupao_codigo', '').strip()[:50] if enable_coupon else '',
             request.form.get('cupao_descricao', '').strip()[:240] if enable_coupon else '',
             url if enable_coupon else '', now_iso(), advertiser_id))
        db.commit()
        flash('Campanha criada com sucesso.', 'success')
        return redirect(url_for('admin_campaigns'))
    return render_template('admin_campaign_form.html', advertisers=all_rows('SELECT id, empresa, email FROM anunciantes WHERE ativo=1 ORDER BY empresa'))


@app.post('/admin/campanhas/<int:id>/alternar')
@admin_required
def admin_campaign_toggle(id):
    verify_csrf()
    db = get_db()
    db.execute('UPDATE campanhas SET ativo=1-ativo WHERE id=?', (id,))
    db.commit()
    return redirect(url_for('admin_campaigns'))


@app.route('/admin/campanhas/<int:id>')
@admin_required
def admin_campaign_detail(id):
    c = one('''SELECT c.*, (SELECT COUNT(*) FROM atribuicoes a WHERE a.campanha_id=c.id) AS atribuicoes,
        (SELECT COUNT(*) FROM exibicoes e WHERE e.campanha_id=c.id) AS exibicoes,
        (SELECT COUNT(*) FROM leituras_qr l WHERE l.campanha_id=c.id) AS leituras,
        (SELECT COUNT(*) FROM resgates_cupao r WHERE r.campanha_id=c.id) AS resgates
        FROM campanhas c WHERE id=?''', (id,))
    if not c:
        abort(404)
    devices = all_rows('''SELECT d.* FROM dispositivos d JOIN atribuicoes a ON a.dispositivo_id=d.id
                           WHERE a.campanha_id=? ORDER BY d.nome''', (id,))
    return render_template('admin_campaign_detail.html', c=c, devices=devices, advertisers=all_rows('SELECT id, empresa, email, ativo FROM anunciantes ORDER BY empresa'), zones=all_rows('SELECT * FROM zonas ORDER BY prioridade DESC, nome'), selected_zones=[r['zona_id'] for r in all_rows('SELECT zona_id FROM campanhas_zonas WHERE campanha_id=?', (id,))])


@app.post('/admin/campanhas/<int:id>/resgatar')
@admin_required
def redeem_coupon(id):
    verify_csrf()
    c = one('SELECT * FROM campanhas WHERE id=? AND cupao_ativo=1', (id,))
    if not c:
        abort(404)
    db = get_db()
    db.execute('INSERT INTO resgates_cupao(campanha_id,referencia,criado_em) VALUES(?,?,?)',
               (id, request.form.get('referencia', '').strip()[:100], now_iso()))
    db.commit()
    flash('Resgate registado manualmente.', 'success')
    return redirect(url_for('admin_campaign_detail', id=id))


@app.route('/admin/ecra')
@admin_required
def admin_devices():
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(timespec='seconds')
    devices = all_rows('''SELECT d.*, (SELECT COUNT(*) FROM atribuicoes a WHERE a.dispositivo_id=d.id) AS campanhas
                          FROM dispositivos d ORDER BY d.id DESC''')
    return render_template('admin_devices.html', devices=devices, cutoff=cutoff)


@app.route('/admin/ecra/novo', methods=['GET', 'POST'])
@admin_required
def admin_device_new():
    if request.method == 'POST':
        verify_csrf()
        nome = request.form.get('nome', '').strip()
        parceiro = request.form.get('parceiro', '').strip()
        cidade = request.form.get('cidade', '').strip()
        if not nome or len(nome) > 100 or len(parceiro) > 140 or len(cidade) > 90:
            flash('Preencha um nome de ecrã válido.', 'error')
        else:
            db = get_db()
            token = secrets.token_urlsafe(30)
            db.execute('INSERT INTO dispositivos(nome,parceiro,cidade,token,criado_em) VALUES(?,?,?,?,?)',
                       (nome, parceiro, cidade, token, now_iso()))
            db.commit()
            flash('Ecrã registado. Guarde o link de reprodução em local seguro.', 'success')
            return redirect(url_for('admin_devices'))
    return render_template('admin_device_form.html')


@app.post('/admin/ecra/<int:id>/alternar')
@admin_required
def admin_device_toggle(id):
    verify_csrf()
    db = get_db()
    db.execute('UPDATE dispositivos SET ativo=1-ativo WHERE id=?', (id,))
    db.commit()
    return redirect(url_for('admin_devices'))


@app.route('/admin/atribuicoes', methods=['GET', 'POST'])
@admin_required
def admin_assign():
    devices = all_rows('SELECT * FROM dispositivos ORDER BY nome')
    campaigns = all_rows('''SELECT c.*, (SELECT COUNT(*) FROM atribuicoes a WHERE a.campanha_id=c.id) AS atribuicoes
                            FROM campanhas c ORDER BY id DESC''')
    if request.method == 'POST':
        verify_csrf()
        try:
            device_id = int(request.form['dispositivo_id'])
            campaign_id = int(request.form['campanha_id'])
        except (KeyError, ValueError):
            abort(400)
        d = one('SELECT id FROM dispositivos WHERE id=?', (device_id,))
        c = one('''SELECT c.*, (SELECT COUNT(*) FROM atribuicoes a WHERE a.campanha_id=c.id) AS atribuicoes
                   FROM campanhas c WHERE id=?''', (campaign_id,))
        if not d or not c:
            abort(404)
        action = request.form.get('acao', 'atribuir')
        db = get_db()
        if action == 'remover':
            db.execute('DELETE FROM atribuicoes WHERE campanha_id=? AND dispositivo_id=?',
                       (campaign_id, device_id))
            flash('Atribuição removida.', 'success')
        elif action == 'atribuir':
            existing = one('SELECT 1 FROM atribuicoes WHERE campanha_id=? AND dispositivo_id=?',
                           (campaign_id, device_id))
            if not existing and c['atribuicoes'] >= c['carros_contratados']:
                flash('O limite contratado de carros já foi atingido.', 'error')
                return redirect(url_for('admin_assign'))
            db.execute('INSERT OR IGNORE INTO atribuicoes(dispositivo_id,campanha_id) VALUES(?,?)',
                       (device_id, campaign_id))
            flash('Ecrã atribuído à campanha.', 'success')
        else:
            abort(400)
        db.commit()
        return redirect(url_for('admin_assign'))
    assigned = all_rows('''SELECT a.*, d.nome AS dispositivo, c.nome AS campanha
                           FROM atribuicoes a JOIN dispositivos d ON d.id=a.dispositivo_id
                           JOIN campanhas c ON c.id=a.campanha_id ORDER BY c.nome, d.nome''')
    return render_template('admin_assign.html', devices=devices, campaigns=campaigns, assigned=assigned)


# ===========================================================
# V1.1 — acesso exclusivo do anunciante e relatórios
# ===========================================================

def current_advertiser():
    account_id = session.get('anunciante_id')
    if not isinstance(account_id, int):
        return None
    return one('SELECT id,nome,empresa,email FROM anunciantes WHERE id=? AND ativo=1', (account_id,))


def advertiser_required(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        if not current_advertiser():
            if request.path.startswith('/api/'):
                return jsonify({'erro': 'Não autorizado'}), 401
            return redirect(url_for('advertiser_login'))
        return fn(*args, **kwargs)
    return inner


def campaign_owned(campaign_id):
    account = current_advertiser()
    if not account:
        abort(403)
    campaign = one('SELECT * FROM campanhas WHERE id=? AND anunciante_id=?', (campaign_id, account['id']))
    if not campaign:
        abort(404)
    return campaign


def campaign_state(c):
    today = datetime.now(timezone.utc).date().isoformat()
    if not c['ativo']:
        return 'Pausada'
    if c['data_inicio'] and today < c['data_inicio']:
        return 'Agendada'
    if c['data_fim'] and today > c['data_fim']:
        return 'Terminada'
    return 'Em curso'


def campaign_metrics(c):
    # Indicador quase em tempo real: sinal de vida do ecrã, não de presença de passageiros.
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(timespec='seconds')
    assigned = one('''SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN d.ativo=1 AND d.ultimo_sinal>=? THEN 1 ELSE 0 END),0) online
                      FROM atribuicoes a JOIN dispositivos d ON d.id=a.dispositivo_id
                      WHERE a.campanha_id=?''', (cutoff, c['id']))
    plays = one('SELECT COUNT(*) n FROM exibicoes WHERE campanha_id=?', (c['id'],))['n']
    qr = one('SELECT COUNT(*) n FROM leituras_qr WHERE campanha_id=?', (c['id'],))['n']
    redemptions = one('SELECT COUNT(*) n FROM resgates_cupao WHERE campanha_id=?', (c['id'],))['n']
    state = campaign_state(c)
    return {
        'id': c['id'], 'nome': c['nome'], 'estado': state,
        'carros_contratados': c['carros_contratados'], 'carros_atribuidos': assigned['n'],
        'carros_online': int(assigned['online']) if state == 'Em curso' else 0,
        'reproducoes': plays, 'leituras_qr': qr if c['cupao_ativo'] else None,
        'resgates': redemptions if c['cupao_ativo'] else None,
        'qr_ativo': bool(c['cupao_ativo']),
        'data_inicio': c['data_inicio'], 'data_fim': c['data_fim'],
    }


def advertiser_summary():
    account = current_advertiser()
    campaigns = all_rows('SELECT * FROM campanhas WHERE anunciante_id=? ORDER BY id DESC', (account['id'],))
    stats = [campaign_metrics(c) for c in campaigns]
    # Um mesmo ecrã em várias campanhas do cliente conta UMA vez como carro ativo.
    online_ids = one('''SELECT COUNT(DISTINCT d.id) n FROM dispositivos d
        JOIN atribuicoes a ON a.dispositivo_id=d.id
        JOIN campanhas c ON c.id=a.campanha_id
        WHERE c.anunciante_id=? AND d.ativo=1 AND d.ultimo_sinal>=?
          AND c.ativo=1 AND (c.data_inicio IS NULL OR c.data_inicio<=?)
          AND (c.data_fim IS NULL OR c.data_fim>=?)''',
        (account['id'], (datetime.now(timezone.utc)-timedelta(seconds=120)).isoformat(timespec='seconds'),
         datetime.now(timezone.utc).date().isoformat(), datetime.now(timezone.utc).date().isoformat()))['n']
    return {
        'empresa': account['empresa'], 'carros_online': online_ids,
        'campanhas': stats, 'quantidade_campanhas': len(stats),
        'carros_contratados': sum(x['carros_contratados'] for x in stats),
        'reproducoes': sum(x['reproducoes'] for x in stats),
        'leituras_qr': sum(x['leituras_qr'] or 0 for x in stats),
        'resgates': sum(x['resgates'] or 0 for x in stats),
        'atualizado_em': now_iso(),
        'criterio_online_segundos': 120,
    }


def daily_metrics(campaign_id, days=14):
    start = (datetime.now(timezone.utc).date() - timedelta(days=days-1)).isoformat()
    plays = all_rows('''SELECT substr(criado_em,1,10) dia, COUNT(*) n FROM exibicoes
        WHERE campanha_id=? AND criado_em>=? GROUP BY substr(criado_em,1,10)''', (campaign_id, start))
    scans = all_rows('''SELECT substr(criado_em,1,10) dia, COUNT(*) n FROM leituras_qr
        WHERE campanha_id=? AND criado_em>=? GROUP BY substr(criado_em,1,10)''', (campaign_id, start))
    redeemed = all_rows('''SELECT substr(criado_em,1,10) dia, COUNT(*) n FROM resgates_cupao
        WHERE campanha_id=? AND criado_em>=? GROUP BY substr(criado_em,1,10)''', (campaign_id, start))
    pm = {r['dia']:r['n'] for r in plays}
    qm = {r['dia']:r['n'] for r in scans}
    rm = {r['dia']:r['n'] for r in redeemed}
    return [{'dia': (datetime.now(timezone.utc).date()-timedelta(days=days-1-i)).isoformat(),
             'reproducoes': pm.get((datetime.now(timezone.utc).date()-timedelta(days=days-1-i)).isoformat(), 0),
             'leituras_qr': qm.get((datetime.now(timezone.utc).date()-timedelta(days=days-1-i)).isoformat(), 0),
             'resgates': rm.get((datetime.now(timezone.utc).date()-timedelta(days=days-1-i)).isoformat(), 0)}
            for i in range(days)]


@app.route('/admin/anunciantes')
@admin_required
def admin_advertisers():
    accounts = all_rows('''SELECT an.*, (SELECT COUNT(*) FROM campanhas c WHERE c.anunciante_id=an.id) campanhas
                            FROM anunciantes an ORDER BY an.id DESC''')
    return render_template('admin_advertisers.html', accounts=accounts)


@app.post('/admin/anunciantes/criar')
@admin_required
def admin_advertiser_new():
    verify_csrf()
    name = request.form.get('nome', '').strip()
    company = request.form.get('empresa', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('senha', '')
    if not name or not company or '@' not in email or len(email)>200 or len(company)>140 or len(name)>130 or not 12<=len(password)<=128:
        flash('Preencha corretamente os dados; a palavra-passe deve ter 12 a 128 caracteres.', 'error')
        return redirect(url_for('admin_advertisers'))
    try:
        db=get_db()
        db.execute('INSERT INTO anunciantes(nome,empresa,email,senha_hash,criado_em) VALUES(?,?,?,?,?)',
                   (name,company,email,generate_password_hash(password),now_iso()))
        db.commit()
        flash('Anunciante criado. Associe agora as campanhas a esta conta.', 'success')
    except sqlite3.IntegrityError:
        flash('Já existe uma conta com este e-mail.', 'error')
    return redirect(url_for('admin_advertisers'))


@app.post('/admin/anunciantes/<int:id>/alternar')
@admin_required
def admin_advertiser_toggle(id):
    verify_csrf()
    if not one('SELECT id FROM anunciantes WHERE id=?', (id,)):
        abort(404)
    db=get_db()
    db.execute('UPDATE anunciantes SET ativo=1-ativo WHERE id=?', (id,))
    db.commit()
    return redirect(url_for('admin_advertisers'))


@app.post('/admin/anunciantes/<int:id>/redefinir-senha')
@admin_required
def admin_advertiser_reset_password(id):
    verify_csrf()
    password=request.form.get('senha','')
    if not 12<=len(password)<=128:
        flash('A palavra-passe deve ter 12 a 128 caracteres.', 'error')
        return redirect(url_for('admin_advertisers'))
    db=get_db()
    cur=db.execute('UPDATE anunciantes SET senha_hash=? WHERE id=?', (generate_password_hash(password),id))
    if not cur.rowcount:
        abort(404)
    db.commit()
    flash('Palavra-passe redefinida.', 'success')
    return redirect(url_for('admin_advertisers'))


@app.post('/admin/campanhas/<int:id>/anunciante')
@admin_required
def admin_campaign_advertiser(id):
    verify_csrf()
    if not one('SELECT id FROM campanhas WHERE id=?', (id,)):
        abort(404)
    raw=request.form.get('anunciante_id','').strip()
    try:
        advertiser_id=int(raw) if raw else None
    except ValueError:
        abort(400)
    if advertiser_id and not one('SELECT id FROM anunciantes WHERE id=?', (advertiser_id,)):
        abort(400)
    db=get_db()
    db.execute('UPDATE campanhas SET anunciante_id=? WHERE id=?', (advertiser_id,id))
    db.commit()
    flash('Acesso à campanha atualizado.', 'success')
    return redirect(url_for('admin_campaign_detail',id=id))


@app.route('/anunciante/entrar', methods=['GET','POST'])
def advertiser_login():
    if current_advertiser():
        return redirect(url_for('advertiser_home'))
    if request.method=='POST':
        verify_csrf()
        email=request.form.get('email','').strip().lower()
        password=request.form.get('senha','')
        account=one('SELECT * FROM anunciantes WHERE email=? AND ativo=1', (email,)) if len(email)<=200 else None
        if account and check_password_hash(account['senha_hash'],password):
            session.clear()
            session['anunciante_id']=account['id']
            session.permanent=True
            csrf_token()
            return redirect(url_for('advertiser_home'))
        flash('E-mail ou palavra-passe inválidos.', 'error')
    return render_template('advertiser_login.html')


@app.post('/anunciante/sair')
@advertiser_required
def advertiser_logout():
    verify_csrf()
    session.clear()
    return redirect(url_for('home'))


@app.get('/anunciante')
@advertiser_required
def advertiser_home():
    return render_template('advertiser_dashboard.html', account=current_advertiser(), summary=advertiser_summary())


@app.get('/api/anunciante/resumo')
@advertiser_required
def api_advertiser_summary():
    return jsonify(advertiser_summary())


@app.get('/anunciante/campanhas/<int:id>')
@advertiser_required
def advertiser_campaign(id):
    c=campaign_owned(id)
    return render_template('advertiser_campaign.html', account=current_advertiser(),
                           c=c, metrics=campaign_metrics(c), daily=daily_metrics(id))


@app.get('/api/anunciante/campanhas/<int:id>/metricas')
@advertiser_required
def api_advertiser_campaign(id):
    c=campaign_owned(id)
    return jsonify({'metricas':campaign_metrics(c),'diario':daily_metrics(id),'atualizado_em':now_iso()})


@app.get('/anunciante/campanhas/<int:id>/relatorio.csv')
@advertiser_required
def advertiser_campaign_csv(id):
    c=campaign_owned(id)
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['Campanha',c['nome']])
    writer.writerow(['Data (UTC)','Reproduções iniciadas','Acessos QR','Resgates confirmados'])
    for d in daily_metrics(id,days=30):
        writer.writerow([d['dia'],d['reproducoes'],d['leituras_qr'],d['resgates']])
    return Response('\ufeff'+output.getvalue(),mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition':f'attachment; filename=rotaads_campanha_{id}_30dias.csv'})


@app.route('/media/<path:filename>')
def media(filename):
    if '/' in filename or '\\' in filename or not filename.startswith(tuple('0123456789abcdef')):
        abort(404)
    response = send_from_directory(UPLOAD_FOLDER, filename, conditional=True)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    if HOSTED_DEMO:
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/player/<token>')
def player(token):
    device = get_device(token)
    return render_template('player.html', device=device, token=token)


@app.get('/api/ecra/<token>/playlist')
def api_playlist(token):
    d = get_device(token)
    campaigns = all_rows('''SELECT c.* FROM campanhas c JOIN atribuicoes a ON a.campanha_id=c.id
                        WHERE a.dispositivo_id=? ORDER BY c.id''', (d['id'],))
    payload = []
    for c in campaigns:
        # V1.2 intacta: sem horários definidos, esta validação autoriza a campanha.
        if not within_dates(c) or not c['ficheiro'] or not schedule_allowed(c):
            continue
        allowed, zone = resolve_campaign_zone(c['id'], d)
        if not allowed:
            continue
        zone_limited = one('SELECT 1 FROM campanhas_zonas WHERE campanha_id=? LIMIT 1', (c['id'],)) is not None
        payload.append({'id': c['id'], 'nome': c['nome'], 'media': url_for('media', filename=c['ficheiro']),
                        'tipo': c['tipo_media'], 'duracao': c['duracao_seg'],
                        'qr': url_for('qr_image', id=c['id']) if c['cupao_ativo'] else None,
                        'cupao_ativo': bool(c['cupao_ativo']),
                        'zona': zone['nome'] if zone else None,
                        'peso': c['peso_v13'], 'segmentada': zone_limited and bool(zone),
                        'anunciante_id': c['anunciante_id']})
    optimized = bool(d['otimizacao_ativa'])
    if optimized:
        start = (datetime.now(timezone.utc)-timedelta(hours=3)).isoformat(timespec='seconds')
        counts = all_rows('SELECT campanha_id, COUNT(*) AS n FROM exibicoes '
                          'WHERE dispositivo_id=? AND criado_em>=? GROUP BY campanha_id', (d['id'], start))
        payload = weighted_playlist(payload, {r['campanha_id']: r['n'] for r in counts})
    # Não expor identificadores internos nem pontuações comerciais à URL do player.
    for item in payload:
        item.pop('peso', None)
        item.pop('segmentada', None)
        item.pop('anunciante_id', None)
    return jsonify({'campanhas': payload, 'ecra': d['nome'],
                    'modo': 'inteligente' if optimized else 'classico',
                    'gps_recente': fresh_position(d) is not None,
                    'atualizado_em': now_iso()})


@app.post('/api/ecra/<token>/sinal')
def api_heartbeat(token):
    d = get_device(token)
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        abort(400)
    db = get_db()
    stamp = now_iso()
    if payload.get('consentimento_gps') is False:
        # Pedido explícito para desligar a localização: apagar coordenadas guardadas.
        db.execute('''UPDATE dispositivos SET ultimo_sinal=?,ultima_lat=NULL,ultima_lon=NULL,
                      ultima_precisao_m=NULL,ultima_localizacao_em=NULL WHERE id=?''', (stamp, d['id']))
    elif payload.get('consentimento_gps') is True:
        try:
            lat = float(payload['lat'])
            lon = float(payload['lon'])
            precision = float(payload['precisao_m'])
        except (KeyError, ValueError, TypeError, OverflowError):
            abort(400, 'Localização incompleta.')
        if not all(math.isfinite(v) for v in (lat, lon, precision)) or not (-90 <= lat <= 90 and -180 <= lon <= 180 and 0 <= precision <= 1500):
            abort(400, 'Coordenadas ou precisão inválidas.')
        db.execute('''UPDATE dispositivos SET ultimo_sinal=?,ultima_lat=?,ultima_lon=?,
                      ultima_precisao_m=?,ultima_localizacao_em=? WHERE id=?''',
                   (stamp, lat, lon, precision, stamp, d['id']))
    else:
        db.execute('UPDATE dispositivos SET ultimo_sinal=? WHERE id=?', (stamp, d['id']))
    db.commit()
    return jsonify({'ok': True, 'gps_recente': fresh_position(get_device(token)) is not None})


@app.post('/api/ecra/<token>/exibicao')
def api_play(token):
    d = get_device(token)
    data = request.get_json(silent=True) or {}
    try:
        campaign_id = int(data.get('campanha_id', 0))
    except (ValueError, TypeError):
        abort(400)
    c = one('''SELECT c.* FROM campanhas c JOIN atribuicoes a ON a.campanha_id=c.id
               WHERE a.dispositivo_id=? AND c.id=?''', (d['id'], campaign_id))
    if not c or not within_dates(c) or not schedule_allowed(c):
        abort(403)
    allowed, zone = resolve_campaign_zone(c['id'], d)
    if not allowed:
        abort(403, 'Campanha fora da zona publicitária autorizada.')
    last = one('''SELECT criado_em FROM exibicoes WHERE dispositivo_id=? AND campanha_id=?
                  ORDER BY id DESC LIMIT 1''', (d['id'], campaign_id))
    if last:
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last['criado_em'])).total_seconds()
            if elapsed < 8:
                return jsonify({'ok': True, 'duplicada': True})
        except ValueError:
            pass
    db = get_db()
    db.execute('INSERT INTO exibicoes(dispositivo_id,campanha_id,criado_em,zona_id) VALUES(?,?,?,?)',
               (d['id'], campaign_id, now_iso(), zone['id'] if zone else None))
    db.commit()
    return jsonify({'ok': True})


@app.route('/qr/<int:id>.png')
def qr_image(id):
    c = one('SELECT id FROM campanhas WHERE id=? AND cupao_ativo=1 AND ativo=1', (id,))
    if not c:
        abort(404)
    data = public_base() + url_for('offer', id=id)
    img = qrcode.make(data, border=2, box_size=8)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return Response(buffer.getvalue(), mimetype='image/png', headers={'Cache-Control': 'public, max-age=600'})


@app.route('/oferta/<int:id>')
def offer(id):
    c = one('SELECT * FROM campanhas WHERE id=? AND cupao_ativo=1 AND ativo=1', (id,))
    if not c or not within_dates(c):
        abort(404)
    db = get_db()
    db.execute('INSERT INTO leituras_qr(campanha_id,criado_em) VALUES(?,?)', (id, now_iso()))
    db.commit()
    return render_template('offer.html', c=c)


@app.errorhandler(404)
def not_found(_err):
    return render_template('error.html', msg='A página não foi encontrada.'), 404


@app.errorhandler(413)
def too_large(_err):
    return render_template('error.html', msg='O ficheiro ultrapassa o tamanho permitido.'), 413


@app.errorhandler(500)
def server_error(_err):
    return render_template('error.html', msg='Ocorreu um erro inesperado. Tente novamente.'), 500


# Funcionalidades V1.2: zonas, mapa protegido e relatórios geográficos.
from geo_v12 import register_geo_routes, fresh_position, resolve_campaign_zone
register_geo_routes(app, get_db, one, all_rows, admin_required, verify_csrf, now_iso,
                    advertiser_required, campaign_owned)
from rotas_v13 import register_v13_routes
register_v13_routes(app, get_db, one, all_rows, admin_required, verify_csrf,
                    advertiser_required, campaign_owned, now_iso)

# V1.3.1 — Painéis de inteligência e relatórios. Nenhuma alteração no banco.
from rotas_v131 import register_v131_routes
register_v131_routes(app, get_db, admin_required, advertiser_required, current_advertiser)

from frotas_v14 import v14_routes, db_schema
v14_routes(app, get_db, admin_required, verify_csrf, now_iso)

init_db()
with app.app_context():
    db_schema(get_db())
    if HOSTED_DEMO:
        from demo_data import seed_demo
        seed_demo(get_db(), UPLOAD_FOLDER, BASE)

if __name__ == '__main__':
    print('RotaAds V1.4  |  http://127.0.0.1:5000')
    if not os.getenv('ADMIN_PASSWORD'):
        print('AVISO: defina ADMIN_PASSWORD em .env para ativar a área administrativa.')
    app.run(host=os.getenv('APP_HOST', '127.0.0.1'), port=int(os.getenv('PORT', '5000')), debug=False)
