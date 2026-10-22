"""RotaAds V1.4 — Gestão de parceiros TVDE, motoristas, carros, contratos e pagamentos.

A V1.4 não altera a elegibilidade nem a lógica de reprodução de campanhas.
Todas as operações mutáveis estão protegidas por ADMIN e CSRF.
"""
from __future__ import annotations

import csv
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import re
import sqlite3
from zoneinfo import ZoneInfo

from flask import (Response, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

FUSO = ZoneInfo('Europe/Lisbon')
SITUACOES = {'ATIVO', 'SUSPENSO', 'ENCERRADO'}
TIPOS = {'FROTA', 'MOTORISTA'}


def hoje_portugal():
    return datetime.now(FUSO).date()


def euros(centimos):
    v = int(centimos or 0)
    s = f'{v // 100:,}'.replace(',', '.')
    return f'{s},{v % 100:02d} €'


def parse_money(raw):
    s = str(raw or '').strip().replace('€', '').replace(' ', '')
    if not s:
        raise ValueError('Indique o valor mensal.')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif s.count('.') > 1:
        raise ValueError('Valor monetário inválido.')
    if not re.fullmatch(r'\d{1,9}(?:\.\d{1,2})?', s):
        raise ValueError('Indique o valor em euros (exemplo: 125,50).')
    try:
        cents = int((Decimal(s) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError('Valor monetário inválido.') from exc
    if cents <= 0 or cents > 100_000_00:
        raise ValueError('Valor deve ser maior do que zero e até 100 000 €.')
    return cents


def parse_date(value, *, required=False):
    s = str(value or '').strip()
    if not s and not required:
        return None
    try:
        d = date.fromisoformat(s)
        if d.isoformat() != s:
            raise ValueError()
        return d
    except (ValueError, TypeError):
        raise ValueError('Data inválida: use AAAA-MM-DD.')


def validate_month(value):
    s = str(value or '').strip()
    if not re.fullmatch(r'20\d\d-(?:0[1-9]|1[0-2])', s):
        raise ValueError('Competência inválida: use AAAA-MM.')
    return s


def month_bounds(m):
    y, mm = map(int, validate_month(m).split('-'))
    start = date(y, mm, 1)
    end = date(y + (mm == 12), mm % 12 + 1, 1) - timedelta(days=1)
    return start, end


def db_schema(db):
    """Schema aditivo; chamado após o init_db() da V1.3.1."""
    db.executescript('''
        CREATE TABLE IF NOT EXISTS frotas_v14 (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nome TEXT NOT NULL, empresa TEXT NOT NULL, email TEXT NOT NULL,
          telefone TEXT NOT NULL DEFAULT '', nif TEXT NOT NULL DEFAULT '',
          cidade TEXT NOT NULL DEFAULT '', capacidade INTEGER NOT NULL DEFAULT 0 CHECK(capacidade>=0),
          ativo INTEGER NOT NULL DEFAULT 1 CHECK(ativo IN (0,1)),
          criado_em TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS motoristas_v14 (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          nome TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
          telefone TEXT NOT NULL DEFAULT '', nif TEXT NOT NULL DEFAULT '',
          frota_id INTEGER REFERENCES frotas_v14(id),
          ativo INTEGER NOT NULL DEFAULT 1 CHECK(ativo IN (0,1)),
          criado_em TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_motoristas_frota_v14 ON motoristas_v14(frota_id);
        CREATE TABLE IF NOT EXISTS veiculos_v14 (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          matricula TEXT NOT NULL COLLATE NOCASE UNIQUE,
          marca TEXT NOT NULL DEFAULT '', modelo TEXT NOT NULL DEFAULT '',
          frota_id INTEGER REFERENCES frotas_v14(id),
          motorista_id INTEGER REFERENCES motoristas_v14(id),
          dispositivo_id INTEGER UNIQUE REFERENCES dispositivos(id) ON DELETE SET NULL,
          ativo INTEGER NOT NULL DEFAULT 1 CHECK(ativo IN (0,1)),
          criado_em TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_veiculos_frota_v14 ON veiculos_v14(frota_id);
        CREATE TABLE IF NOT EXISTS contratos_v14 (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          veiculo_id INTEGER NOT NULL REFERENCES veiculos_v14(id),
          beneficiario_tipo TEXT NOT NULL CHECK(beneficiario_tipo IN ('FROTA','MOTORISTA')),
          beneficiario_id INTEGER NOT NULL,
          valor_centimos INTEGER NOT NULL CHECK(valor_centimos>0),
          data_inicio TEXT NOT NULL, data_fim TEXT,
          dia_vencimento INTEGER NOT NULL DEFAULT 10 CHECK(dia_vencimento BETWEEN 1 AND 28),
          estado TEXT NOT NULL DEFAULT 'ATIVO' CHECK(estado IN ('ATIVO','SUSPENSO','ENCERRADO')),
          observacoes TEXT NOT NULL DEFAULT '',
          criado_em TEXT NOT NULL,
          CHECK(data_fim IS NULL OR data_fim >= data_inicio)
        );
        CREATE INDEX IF NOT EXISTS idx_contratos_veiculo_v14 ON contratos_v14(veiculo_id);
        CREATE TABLE IF NOT EXISTS pagamentos_v14 (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          contrato_id INTEGER NOT NULL REFERENCES contratos_v14(id),
          competencia TEXT NOT NULL,
          vencimento TEXT NOT NULL,
          valor_centimos INTEGER NOT NULL CHECK(valor_centimos>0),
          estado TEXT NOT NULL DEFAULT 'PENDENTE' CHECK(estado IN ('PENDENTE','PAGO')),
          pago_em TEXT, referencia TEXT NOT NULL DEFAULT '',
          criado_em TEXT NOT NULL,
          UNIQUE(contrato_id, competencia)
        );
        CREATE INDEX IF NOT EXISTS idx_pagamentos_mes_v14 ON pagamentos_v14(competencia, estado);
    ''')
    db.commit()


def validate_vehicle_selection(db, fleet_id, driver_id, device_id, exclude_id=None):
    if fleet_id is not None:
        r = db.execute('SELECT id,ativo FROM frotas_v14 WHERE id=?', (fleet_id,)).fetchone()
        if not r or not r['ativo']:
            raise ValueError('Frota não encontrada ou inativa.')
    if driver_id is not None:
        driver = db.execute('SELECT id,frota_id,ativo FROM motoristas_v14 WHERE id=?', (driver_id,)).fetchone()
        if not driver or not driver['ativo']:
            raise ValueError('Motorista não encontrado ou inativo.')
        if driver['frota_id'] != fleet_id:
            raise ValueError('O motorista deve pertencer à mesma frota do veículo (ou ambos independentes).')
    if fleet_id is None and driver_id is None:
        raise ValueError('Selecione uma frota ou um motorista individual.')
    if device_id is not None:
        dev = db.execute('SELECT id,ativo FROM dispositivos WHERE id=?', (device_id,)).fetchone()
        if not dev or not dev['ativo']:
            raise ValueError('Ecrã não encontrado ou inativo.')
        assigned = db.execute('SELECT id FROM veiculos_v14 WHERE dispositivo_id=?', (device_id,)).fetchone()
        if assigned and assigned['id'] != exclude_id:
            raise ValueError('Esse ecrã já está associado a outro veículo.')


def valid_payee(db, vehicle, ptype, pid):
    if ptype not in TIPOS:
        raise ValueError('Tipo de beneficiário inválido.')
    if ptype == 'FROTA':
        if not vehicle['frota_id'] or vehicle['frota_id'] != pid:
            raise ValueError('O beneficiário frota deve ser a frota do veículo.')
        payee = db.execute('SELECT ativo FROM frotas_v14 WHERE id=?', (pid,)).fetchone()
    else:
        if not vehicle['motorista_id'] or vehicle['motorista_id'] != pid:
            raise ValueError('O beneficiário motorista deve ser o motorista atribuído ao veículo.')
        payee = db.execute('SELECT ativo FROM motoristas_v14 WHERE id=?', (pid,)).fetchone()
    if not payee or not payee['ativo']:
        raise ValueError('Beneficiário não encontrado ou inativo.')


def check_overlapping_contract(db, vehicle_id, start, end):
    """Uma única cedência ativa por veículo em qualquer data."""
    existing = db.execute('''SELECT id, data_inicio, data_fim FROM contratos_v14
                             WHERE veiculo_id=? AND estado IN ('ATIVO','SUSPENSO')''', (vehicle_id,)).fetchall()
    for r in existing:
        old_start = date.fromisoformat(r['data_inicio'])
        old_end = date.fromisoformat(r['data_fim']) if r['data_fim'] else date.max
        if start <= old_end and old_start <= (end or date.max):
            raise ValueError(f'Já existe contrato ativo/suspenso com período sobreposto (n.º {r["id"]}).')


def generate_payments(db, competence, now):
    competence = validate_month(competence)
    start, end = month_bounds(competence)
    contracts = db.execute('''SELECT c.*, v.ativo AS veiculo_ativo FROM contratos_v14 c
                              JOIN veiculos_v14 v ON v.id=c.veiculo_id WHERE c.estado='ATIVO' ''').fetchall()
    inserted = 0
    for c in contracts:
        if not c['veiculo_ativo']:
            continue
        cs = date.fromisoformat(c['data_inicio'])
        ce = date.fromisoformat(c['data_fim']) if c['data_fim'] else date.max
        if cs > end or ce < start:
            continue
        due = date(start.year, start.month, c['dia_vencimento'])
        result = db.execute('''INSERT OR IGNORE INTO pagamentos_v14
            (contrato_id,competencia,vencimento,valor_centimos,estado,criado_em)
            VALUES(?,?,?,?,?,?)''', (c['id'], competence, due.isoformat(), c['valor_centimos'], 'PENDENTE', now))
        inserted += result.rowcount
    db.commit()
    return inserted


def payment_rows(db, competence):
    return db.execute('''SELECT p.*, c.veiculo_id, v.matricula,
          CASE WHEN c.beneficiario_tipo='FROTA' THEN f.empresa ELSE m.nome END AS beneficiario,
          c.beneficiario_tipo, c.dia_vencimento
          FROM pagamentos_v14 p JOIN contratos_v14 c ON c.id=p.contrato_id
          JOIN veiculos_v14 v ON v.id=c.veiculo_id
          LEFT JOIN frotas_v14 f ON c.beneficiario_tipo='FROTA' AND f.id=c.beneficiario_id
          LEFT JOIN motoristas_v14 m ON c.beneficiario_tipo='MOTORISTA' AND m.id=c.beneficiario_id
          WHERE p.competencia=? ORDER BY p.estado DESC,p.vencimento,p.id''', (competence,)).fetchall()


def summary(db, competence):
    payments = payment_rows(db, competence)
    today = hoje_portugal().isoformat()
    return dict(
        frotas=db.execute('SELECT COUNT(*) FROM frotas_v14 WHERE ativo=1').fetchone()[0],
        motoristas=db.execute('SELECT COUNT(*) FROM motoristas_v14 WHERE ativo=1').fetchone()[0],
        veiculos=db.execute('SELECT COUNT(*) FROM veiculos_v14 WHERE ativo=1').fetchone()[0],
        contratos=db.execute("SELECT COUNT(*) FROM contratos_v14 WHERE estado='ATIVO'").fetchone()[0],
        total=sum(p['valor_centimos'] for p in payments),
        pago=sum(p['valor_centimos'] for p in payments if p['estado']=='PAGO'),
        pendente=sum(p['valor_centimos'] for p in payments if p['estado']=='PENDENTE'),
        vencido=sum(p['valor_centimos'] for p in payments if p['estado']=='PENDENTE' and p['vencimento'] < today),
        sem_pagamento=len(payments)==0,
    )


def v14_routes(app, get_db, admin_required, verify_csrf, now_iso):
    from analytics_v131 import csv_safe
    from pdf_v14 import pdf_contract, pdf_payments
    import secrets
    from flask import session

    app.jinja_env.filters['euros_v14'] = euros

    def field(name, maxlen=160, *, required=False):
        v = str(request.form.get(name, '')).strip()
        if required and not v:
            raise ValueError(f'Preencha o campo {name}.')
        if len(v) > maxlen:
            raise ValueError(f'O campo {name} é demasiado longo (máximo {maxlen}).')
        return v

    def id_field(name):
        raw = field(name)
        if not raw:
            return None
        try:
            v = int(raw)
            if v <= 0:
                raise ValueError()
            return v
        except ValueError:
            raise ValueError(f'O campo {name} deve conter um ID válido.')

    def capacity_field():
        raw = field('capacidade')
        if not raw:
            return 0
        try:
            v = int(raw)
        except ValueError:
            raise ValueError('Número de carros declarados inválido.')
        if v < 0 or v > 100000:
            raise ValueError('Número de carros declarados deve estar entre 0 e 100 000.')
        return v

    def checked_email(name, *, required=False):
        value = field(name, 180, required=required)
        if value and (not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value)):
            raise ValueError('E-mail inválido.')
        return value

    def apply_action(fn, destination):
        verify_csrf()
        try:
            message = fn(get_db())
            flash(message, 'success')
        except (ValueError, sqlite3.IntegrityError) as exc:
            get_db().rollback()
            flash(str(exc) if isinstance(exc, ValueError) else 'Registo duplicado ou incompatível. Confira os dados.', 'error')
        return redirect(url_for(destination))

    def current_month():
        try:
            return validate_month(request.args.get('mes') or hoje_portugal().strftime('%Y-%m'))
        except ValueError:
            abort(400, 'Mês inválido.')

    @app.get('/admin/frotas')
    @admin_required
    def admin_frotas_v14():
        db = get_db()
        m = current_month()
        records = db.execute('''SELECT f.*, COUNT(DISTINCT v.id) AS veiculos,
          COUNT(DISTINCT m.id) AS motoristas
          FROM frotas_v14 f LEFT JOIN veiculos_v14 v ON v.frota_id=f.id
          LEFT JOIN motoristas_v14 m ON m.frota_id=f.id GROUP BY f.id ORDER BY f.ativo DESC, f.empresa''').fetchall()
        return render_template('v14_frotas.html', rows=records, dados=summary(db,m), mes=m)

    @app.post('/admin/frotas/criar')
    @admin_required
    def admin_frota_create_v14():
        def action(db):
            capacity = capacity_field()
            db.execute('''INSERT INTO frotas_v14(nome,empresa,email,telefone,nif,cidade,capacidade,criado_em)
                          VALUES(?,?,?,?,?,?,?,?)''',
                       (field('nome',required=True), field('empresa',required=True), checked_email('email',required=True),
                        field('telefone',40),field('nif',32),field('cidade',100),capacity,now_iso()))
            db.commit()
            return 'Frota cadastrada.'
        return apply_action(action,'admin_frotas_v14')

    @app.post('/admin/frotas/<int:id>/atualizar')
    @admin_required
    def admin_frota_update_v14(id):
        def action(db):
            if not db.execute('SELECT 1 FROM frotas_v14 WHERE id=?', (id,)).fetchone(): abort(404)
            capacity = capacity_field()
            db.execute('''UPDATE frotas_v14 SET nome=?, empresa=?, email=?,telefone=?,nif=?,cidade=?,capacidade=? WHERE id=?''',
                       (field('nome',required=True),field('empresa',required=True),checked_email('email',required=True),
                        field('telefone',40),field('nif',32),field('cidade',100),capacity,id))
            db.commit()
            return 'Dados da frota atualizados.'
        return apply_action(action,'admin_frotas_v14')

    @app.post('/admin/frotas/<int:id>/alternar')
    @admin_required
    def admin_frota_toggle_v14(id):
        def action(db):
            r=db.execute('UPDATE frotas_v14 SET ativo=1-ativo WHERE id=?', (id,))
            if not r.rowcount: abort(404)
            db.commit()
            return 'Estado da frota atualizado. Contratos e pagamentos anteriores foram mantidos.'
        return apply_action(action,'admin_frotas_v14')

    @app.get('/admin/motoristas')
    @admin_required
    def admin_motoristas_v14():
        db=get_db()
        rows=db.execute('''SELECT m.*, f.empresa AS nome_frota FROM motoristas_v14 m
                         LEFT JOIN frotas_v14 f ON f.id=m.frota_id ORDER BY m.ativo DESC,m.nome''').fetchall()
        fleets=db.execute('SELECT id,empresa FROM frotas_v14 WHERE ativo=1 ORDER BY empresa').fetchall()
        return render_template('v14_motoristas.html',rows=rows,frotas=fleets)

    @app.post('/admin/motoristas/criar')
    @admin_required
    def admin_motorista_create_v14():
        def action(db):
            fleet=id_field('frota_id')
            if fleet and not db.execute('SELECT 1 FROM frotas_v14 WHERE id=? AND ativo=1', (fleet,)).fetchone():
                raise ValueError('Frota não encontrada ou inativa.')
            db.execute('''INSERT INTO motoristas_v14(nome,email,telefone,nif,frota_id,criado_em)
                          VALUES(?,?,?,?,?,?)''',(field('nome',required=True),checked_email('email'),
                          field('telefone',40),field('nif',32),fleet,now_iso()))
            db.commit()
            return 'Motorista cadastrado.'
        return apply_action(action,'admin_motoristas_v14')

    @app.post('/admin/motoristas/<int:id>/atualizar')
    @admin_required
    def admin_motorista_update_v14(id):
        def action(db):
            old=db.execute('SELECT * FROM motoristas_v14 WHERE id=?', (id,)).fetchone()
            if not old: abort(404)
            fleet=id_field('frota_id')
            if fleet and not db.execute('SELECT 1 FROM frotas_v14 WHERE id=? AND ativo=1', (fleet,)).fetchone():
                raise ValueError('Frota não encontrada ou inativa.')
            if fleet != old['frota_id'] and db.execute('SELECT 1 FROM veiculos_v14 WHERE motorista_id=?', (id,)).fetchone():
                raise ValueError('Para mudar de frota, desvincule primeiro os veículos deste motorista.')
            db.execute('''UPDATE motoristas_v14 SET nome=?,email=?,telefone=?,nif=?,frota_id=? WHERE id=?''',
                       (field('nome',required=True),checked_email('email'),field('telefone',40),
                        field('nif',32),fleet,id))
            db.commit()
            return 'Dados do motorista atualizados.'
        return apply_action(action,'admin_motoristas_v14')

    @app.post('/admin/motoristas/<int:id>/alternar')
    @admin_required
    def admin_motorista_toggle_v14(id):
        def action(db):
            row=db.execute('UPDATE motoristas_v14 SET ativo=1-ativo WHERE id=?', (id,))
            if not row.rowcount: abort(404)
            db.commit()
            return 'Estado do motorista atualizado; o histórico foi preservado.'
        return apply_action(action,'admin_motoristas_v14')

    @app.get('/admin/veiculos')
    @admin_required
    def admin_veiculos_v14():
        db=get_db()
        rows=db.execute('''SELECT v.*, f.empresa AS frota, m.nome AS motorista,
             d.nome AS ecra,d.ultimo_sinal AS ultimo_sinal
             FROM veiculos_v14 v LEFT JOIN frotas_v14 f ON f.id=v.frota_id
             LEFT JOIN motoristas_v14 m ON m.id=v.motorista_id
             LEFT JOIN dispositivos d ON d.id=v.dispositivo_id
             ORDER BY v.ativo DESC,v.matricula''').fetchall()
        fleets=db.execute('SELECT id,empresa FROM frotas_v14 WHERE ativo=1 ORDER BY empresa').fetchall()
        drivers=db.execute('SELECT id,nome,frota_id FROM motoristas_v14 WHERE ativo=1 ORDER BY nome').fetchall()
        devices=db.execute('''SELECT d.id,d.nome,v.id AS associado FROM dispositivos d
                             LEFT JOIN veiculos_v14 v ON v.dispositivo_id=d.id WHERE d.ativo=1 ORDER BY d.nome''').fetchall()
        return render_template('v14_veiculos.html',rows=rows,frotas=fleets,motoristas=drivers,ecras=devices,
                               agora=datetime.now(timezone.utc))

    def vehicle_payload(db, excluded=None):
        fleet=id_field('frota_id')
        driver=id_field('motorista_id')
        device=id_field('dispositivo_id')
        validate_vehicle_selection(db,fleet,driver,device,excluded)
        plate=field('matricula',18,required=True).upper().replace(' ','').replace('-','')
        if not re.fullmatch(r'[A-Z0-9]{4,12}',plate):
            raise ValueError('Matrícula inválida. Utilize 4 a 12 letras/números.')
        return (plate,field('marca',80),field('modelo',80),fleet,driver,device)

    @app.post('/admin/veiculos/criar')
    @admin_required
    def admin_veiculo_create_v14():
        def action(db):
            data=vehicle_payload(db)
            db.execute('''INSERT INTO veiculos_v14(matricula,marca,modelo,frota_id,motorista_id,dispositivo_id,criado_em)
                          VALUES(?,?,?,?,?,?,?)''',(*data,now_iso()))
            db.commit()
            return 'Veículo cadastrado. O vínculo com o ecrã não altera campanhas existentes.'
        return apply_action(action,'admin_veiculos_v14')

    @app.post('/admin/veiculos/<int:id>/atualizar')
    @admin_required
    def admin_veiculo_update_v14(id):
        def action(db):
            old=db.execute('SELECT * FROM veiculos_v14 WHERE id=?', (id,)).fetchone()
            if not old: abort(404)
            data=vehicle_payload(db,id)
            active_contract=db.execute("SELECT 1 FROM contratos_v14 WHERE veiculo_id=? AND estado IN ('ATIVO','SUSPENSO')", (id,)).fetchone()
            if active_contract and (data[3]!=old['frota_id'] or data[4]!=old['motorista_id']):
                raise ValueError('Não mude a frota ou motorista enquanto existir contrato ativo/suspenso. Encerre-o primeiro.')
            db.execute('''UPDATE veiculos_v14 SET matricula=?,marca=?,modelo=?,frota_id=?,motorista_id=?,dispositivo_id=? WHERE id=?''', (*data,id))
            db.commit()
            return 'Veículo atualizado.'
        return apply_action(action,'admin_veiculos_v14')

    @app.post('/admin/veiculos/<int:id>/alternar')
    @admin_required
    def admin_veiculo_toggle_v14(id):
        def action(db):
            row=db.execute('UPDATE veiculos_v14 SET ativo=1-ativo WHERE id=?', (id,))
            if not row.rowcount: abort(404)
            db.commit()
            return 'Estado do veículo atualizado; contratos e histórico foram mantidos.'
        return apply_action(action,'admin_veiculos_v14')

    @app.get('/admin/contratos')
    @admin_required
    def admin_contratos_v14():
        db=get_db()
        rows=db.execute('''SELECT c.*,v.matricula,
          CASE WHEN c.beneficiario_tipo='FROTA' THEN f.empresa ELSE m.nome END AS beneficiario
          FROM contratos_v14 c JOIN veiculos_v14 v ON v.id=c.veiculo_id
          LEFT JOIN frotas_v14 f ON c.beneficiario_tipo='FROTA' AND c.beneficiario_id=f.id
          LEFT JOIN motoristas_v14 m ON c.beneficiario_tipo='MOTORISTA' AND c.beneficiario_id=m.id
          ORDER BY c.id DESC''').fetchall()
        vehicles=db.execute('''SELECT v.*,f.empresa AS frota,m.nome AS motorista
             FROM veiculos_v14 v LEFT JOIN frotas_v14 f ON f.id=v.frota_id
             LEFT JOIN motoristas_v14 m ON m.id=v.motorista_id WHERE v.ativo=1 ORDER BY v.matricula''').fetchall()
        return render_template('v14_contratos.html',rows=rows,veiculos=vehicles,hoje=hoje_portugal().isoformat())

    @app.post('/admin/contratos/criar')
    @admin_required
    def admin_contrato_create_v14():
        def action(db):
            vid=id_field('veiculo_id')
            vehicle=db.execute('SELECT * FROM veiculos_v14 WHERE id=? AND ativo=1',(vid,)).fetchone()
            if not vehicle: raise ValueError('Selecione um veículo ativo.')
            ptype=field('beneficiario_tipo',20)
            pid=id_field('beneficiario_id')
            valid_payee(db,vehicle,ptype,pid)
            cents=parse_money(field('valor_mensal'))
            start=parse_date(field('data_inicio'),required=True)
            end=parse_date(field('data_fim'))
            if end and end<start: raise ValueError('Data final anterior à data inicial.')
            due=id_field('dia_vencimento')
            if due is None or not 1<=due<=28: raise ValueError('Dia de vencimento deve estar entre 1 e 28.')
            check_overlapping_contract(db,vid,start,end)
            db.execute('''INSERT INTO contratos_v14(veiculo_id,beneficiario_tipo,beneficiario_id,
                   valor_centimos,data_inicio,data_fim,dia_vencimento,observacoes,criado_em)
                   VALUES(?,?,?,?,?,?,?,?,?)''',(vid,ptype,pid,cents,start.isoformat(),
                          end.isoformat() if end else None,due,field('observacoes',1000),now_iso()))
            db.commit()
            return 'Contrato de cedência registado. Gere as mensalidades em Pagamentos.'
        return apply_action(action,'admin_contratos_v14')

    @app.post('/admin/contratos/<int:id>/estado')
    @admin_required
    def admin_contrato_state_v14(id):
        def action(db):
            new=field('estado',20)
            if new not in SITUACOES: raise ValueError('Estado de contrato inválido.')
            contract=db.execute('SELECT * FROM contratos_v14 WHERE id=?',(id,)).fetchone()
            if not contract: abort(404)
            if contract['estado']=='ENCERRADO' and new!='ENCERRADO':
                raise ValueError('Contratos encerrados são históricos e não podem ser reativados.')
            if new=='ATIVO' and contract['estado']=='SUSPENSO':
                check_overlapping_contract_except(db,contract)
            db.execute('UPDATE contratos_v14 SET estado=? WHERE id=?',(new,id))
            db.commit()
            return 'Estado do contrato atualizado; pagamentos anteriores foram preservados.'
        return apply_action(action,'admin_contratos_v14')

    @app.get('/admin/pagamentos')
    @admin_required
    def admin_pagamentos_v14():
        db=get_db(); month=current_month()
        rows=payment_rows(db,month)
        return render_template('v14_pagamentos.html',rows=rows,mes=month,dados=summary(db,month),
                               hoje=hoje_portugal().isoformat())

    @app.post('/admin/pagamentos/gerar')
    @admin_required
    def admin_payment_generate_v14():
        def action(db):
            month=validate_month(field('mes'))
            n=generate_payments(db,month,now_iso())
            return f'{n} mensalidade(s) criada(s) para {month}. As já existentes não foram duplicadas.'
        return apply_action(action,'admin_pagamentos_v14')

    @app.post('/admin/pagamentos/<int:id>/pagar')
    @admin_required
    def admin_payment_mark_v14(id):
        def action(db):
            ref=field('referencia',160)
            if not ref: raise ValueError('Indique a referência de confirmação do pagamento.')
            row=db.execute("UPDATE pagamentos_v14 SET estado='PAGO',pago_em=?,referencia=? WHERE id=? AND estado='PENDENTE'",
                           (now_iso(),ref,id))
            if not row.rowcount: raise ValueError('Mensalidade inexistente ou já registada como paga.')
            db.commit()
            return 'Pagamento confirmado manualmente. Guarde o comprovativo fora do sistema.'
        return apply_action(action,'admin_pagamentos_v14')

    @app.get('/admin/pagamentos.csv')
    @admin_required
    def admin_payment_csv_v14():
        month=current_month(); db=get_db()
        buff=io.StringIO(newline=''); writer=csv.writer(buff,delimiter=';')
        writer.writerow(['RotaAds V1.4 — Pagamentos mensais'])
        writer.writerow(['Competência',month]); writer.writerow([])
        writer.writerow(['ID','Contrato','Matrícula','Beneficiário','Tipo','Valor (€)','Vencimento','Estado','Pago em (UTC)','Referência'])
        for r in payment_rows(db,month):
            writer.writerow([csv_safe(x) for x in (r['id'],r['contrato_id'],r['matricula'],r['beneficiario'],r['beneficiario_tipo'],
                euros(r['valor_centimos']),r['vencimento'],r['estado'],r['pago_em'] or '',r['referencia'])])
        return Response('\ufeff'+buff.getvalue(),mimetype='text/csv',headers={
            'Content-Disposition':f'attachment; filename="rotaads_pagamentos_{month}.csv"',
            'Cache-Control':'private, no-store'})

    @app.get('/admin/contratos/<int:id>/documento.pdf')
    @admin_required
    def admin_contrato_pdf_v14(id):
        db=get_db()
        c=db.execute('SELECT * FROM contratos_v14 WHERE id=?',(id,)).fetchone()
        if not c: abort(404)
        vehicle=db.execute('SELECT * FROM veiculos_v14 WHERE id=?',(c['veiculo_id'],)).fetchone()
        if c['beneficiario_tipo']=='FROTA':
            payee=db.execute('SELECT empresa AS nome FROM frotas_v14 WHERE id=?',(c['beneficiario_id'],)).fetchone()
        else:
            payee=db.execute('SELECT nome FROM motoristas_v14 WHERE id=?',(c['beneficiario_id'],)).fetchone()
        payload=pdf_contract(c,vehicle,payee['nome'] if payee else '—')
        return Response(payload,mimetype='application/pdf',headers={
            'Content-Disposition':f'attachment; filename="rotaads_contrato_{id}_minuta.pdf"',
            'Cache-Control':'private, no-store'})

    @app.get('/admin/pagamentos.pdf')
    @admin_required
    def admin_pagamentos_pdf_v14():
        month=current_month(); db=get_db()
        payload=pdf_payments(month,payment_rows(db,month),summary(db,month))
        return Response(payload,mimetype='application/pdf',headers={
            'Content-Disposition':f'attachment; filename="rotaads_pagamentos_{month}.pdf"',
            'Cache-Control':'private, no-store'})

    @app.get('/admin/frotas/resumo.json')
    @admin_required
    def admin_fleet_summary_v14():
        month=current_month()
        return jsonify({'competencia':month,'indicadores':summary(get_db(),month), 'atualizado_em':now_iso()})


def check_overlapping_contract_except(db, contract):
    """Reserva para reativação: ignora o próprio contrato."""
    start=date.fromisoformat(contract['data_inicio'])
    end=date.fromisoformat(contract['data_fim']) if contract['data_fim'] else date.max
    rs=db.execute('''SELECT id,data_inicio,data_fim FROM contratos_v14
       WHERE veiculo_id=? AND id != ? AND estado IN ('ATIVO','SUSPENSO')''', (contract['veiculo_id'],contract['id'])).fetchall()
    for c in rs:
        s=date.fromisoformat(c['data_inicio']); e=date.fromisoformat(c['data_fim']) if c['data_fim'] else date.max
        if start<=e and s<=end:
            raise ValueError('Outro contrato possui período de cedência sobreposto.')
