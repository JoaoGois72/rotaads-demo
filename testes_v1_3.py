"""Testes RotaAds V1.3: isolados, sem tocar no banco operacional.

Executar no Windows, após pip install -r requirements.txt:
    python testes_v1_3.py
"""
import base64
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from motor_v13 import portugal_now, parse_schedule, schedule_allowed, weighted_playlist, summarize_hours

PIXEL = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/5d8AAAAASUVORK5CYII=')


def ok(message):
    print('  OK  ' + message)


def check(response, status, label):
    assert response.status_code == status, (
        f'{label}: esperado {status}, recebido {response.status_code}. '
        f'Body: {response.get_data(as_text=True)[:350]}')


def pure_tests():
    assert parse_schedule('09:00', '18:30', [0, 4]) == ('09:00', '18:30', '0,4')
    for start, end, days in [('09:00', '', []), ('24:00', '23:00', []), ('18:00','18:00',[]),('09:00','17:00',['9'])]:
        try:
            parse_schedule(start, end, days)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Horário inválido foi aceite: {start}, {end}, {days}')
    from datetime import datetime as DateTime
    from zoneinfo import ZoneInfo
    lisbon = ZoneInfo('Europe/Lisbon')
    class Schedule(dict):
        pass
    campaign = Schedule(horario_inicio='22:00', horario_fim='02:00', dias_semana='0')
    monday_night = DateTime(2026, 10, 19, 23, 0, tzinfo=lisbon).astimezone(timezone.utc)
    tuesday_morning = DateTime(2026, 10, 20, 1, 0, tzinfo=lisbon).astimezone(timezone.utc)
    tuesday_evening = DateTime(2026, 10, 20, 23, 0, tzinfo=lisbon).astimezone(timezone.utc)
    assert schedule_allowed(campaign, monday_night)
    assert schedule_allowed(campaign, tuesday_morning)
    assert not schedule_allowed(campaign, tuesday_evening)
    assert schedule_allowed(Schedule(horario_inicio='', horario_fim='', dias_semana=''), monday_night)
    assert portugal_now(monday_night).hour == 23
    ok('Validação de horários e dias da semana, incluindo madrugada no fuso Portugal')
    items = [{'id': 1, 'peso': 5, 'segmentada': True}, {'id': 2, 'peso': 1, 'segmentada': False}]
    order = weighted_playlist(items, size=48)
    freqs = Counter(item['id'] for item in order)
    assert len(order) == 48 and freqs[1] > freqs[2] > 0, freqs
    assert weighted_playlist([], size=48) == []
    assert len(weighted_playlist(items[:1], size=48)) == 1
    result = summarize_hours([monday_night.isoformat(), tuesday_morning.isoformat(), 'erro'])
    assert sum(result) == 2 and result[23] == 1 and result[1] == 1
    ok('Rotação por prioridades, oportunidades e métricas por hora')


def migration_test(root):
    """Migrador sobre uma mini base V1.2, sem Flask e sem mudar a origem."""
    old, dest = root / 'antiga', root / 'nova'
    (old / 'instance').mkdir(parents=True)
    (old / 'uploads').mkdir()
    dest.mkdir()
    (old / 'app.py').write_text('# V1.2 de teste\n', encoding='utf-8')
    (old / '.env').write_text('APP_NAME=Teste\nADMIN_PASSWORD=senha-de-teste\n', encoding='utf-8')
    (old / 'uploads' / 'anuncio.png').write_bytes(PIXEL)
    source = old / 'instance' / 'rotaads.sqlite3'
    with closing(sqlite3.connect(source)) as db, db:
        db.executescript('''CREATE TABLE campanhas(id INTEGER PRIMARY KEY, nome TEXT NOT NULL);
        CREATE TABLE dispositivos(id INTEGER PRIMARY KEY, ultima_localizacao_em TEXT);
        CREATE TABLE anunciantes(id INTEGER PRIMARY KEY);
        CREATE TABLE zonas(id INTEGER PRIMARY KEY);
        CREATE TABLE campanhas_zonas(campanha_id INTEGER,zona_id INTEGER);
        INSERT INTO campanhas(id,nome) VALUES(7,'Campanha histórica');''')
    shutil.copy2(ROOT / 'migrar_da_v1_2.py', dest / 'migrar_da_v1_2.py')
    command = [sys.executable, str(dest / 'migrar_da_v1_2.py'), str(old)]
    proc = subprocess.run(command, text=True, capture_output=True, timeout=40)
    assert proc.returncode == 0, proc.stdout + '\n' + proc.stderr
    saved = dest / 'instance' / 'rotaads.sqlite3'
    with closing(sqlite3.connect(saved)) as db:
        assert db.execute('SELECT nome FROM campanhas WHERE id=7').fetchone()[0] == 'Campanha histórica'
    assert (dest / 'uploads' / 'anuncio.png').read_bytes() == PIXEL
    assert list((dest / 'backups').glob('v1_2_original_*.zip'))
    second = subprocess.run(command, text=True, capture_output=True, timeout=40)
    assert second.returncode != 0 and 'NÃO será sobrescrito' in second.stdout
    with closing(sqlite3.connect(source)) as db:
        assert db.execute('SELECT COUNT(*) FROM campanhas').fetchone()[0] == 1
    ok('Migração não destrutiva: cópia SQLite, anúncios, .env, backup e bloqueio de substituição')


def app_tests(root):
    dbpath = root / 'instance' / 'rotaads.sqlite3'
    dbpath.parent.mkdir(parents=True)
    # Estrutura e dados V1.2 pré-V1.3 (dados simulados para testar migração in-place).
    with closing(sqlite3.connect(dbpath)) as db, db:
        db.executescript('''
          CREATE TABLE campanhas(id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL,
           anunciante TEXT NOT NULL,cidade TEXT NOT NULL DEFAULT '',carros_contratados INTEGER NOT NULL,
           ativo INTEGER NOT NULL DEFAULT 1,data_inicio TEXT,data_fim TEXT,ficheiro TEXT,tipo_media TEXT,
           duracao_seg INTEGER NOT NULL DEFAULT 12,cupao_ativo INTEGER NOT NULL DEFAULT 0,
           cupao_codigo TEXT NOT NULL DEFAULT '',cupao_descricao TEXT NOT NULL DEFAULT '',
           cupao_url TEXT NOT NULL DEFAULT '',criado_em TEXT NOT NULL,anunciante_id INTEGER);
          CREATE TABLE dispositivos(id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL,
           parceiro TEXT NOT NULL DEFAULT '',cidade TEXT NOT NULL DEFAULT '',token TEXT NOT NULL UNIQUE,
           ativo INTEGER NOT NULL DEFAULT 1,ultimo_sinal TEXT,ultima_lat REAL,ultima_lon REAL,
           ultima_precisao_m REAL,ultima_localizacao_em TEXT,criado_em TEXT NOT NULL);
          INSERT INTO campanhas(id,nome,anunciante,carros_contratados,criado_em)
            VALUES(91,'Campanha preservada V1.2','Cliente anterior',3,'2026-01-01T00:00:00+00:00');
          INSERT INTO dispositivos(id,nome,token,criado_em)
            VALUES(91,'Ecrã preservado','token-antigo-funciona','2026-01-01T00:00:00+00:00');
        ''')
    os.environ.update(DATABASE_PATH=str(dbpath), UPLOAD_FOLDER=str(root / 'uploads'),
       SECRET_KEY='senha-secret-teste-v13',ADMIN_USERNAME='admin',
       ADMIN_PASSWORD='senha-admin-teste-v13',SITE_URL='http://127.0.0.1:5000')
    spec = importlib.util.spec_from_file_location('rotaads_teste_v13', ROOT / 'app.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    client = mod.app.test_client()

    def sql(query, params=()):
        with closing(sqlite3.connect(dbpath)) as db:
            return db.execute(query, params).fetchall()

    def csrf():
        with client.session_transaction() as session:
            session.setdefault('_csrf', 'token-csrf-teste-v13')
            return session['_csrf']

    assert sql('SELECT nome FROM campanhas WHERE id=91')[0][0] == 'Campanha preservada V1.2'
    assert sql('SELECT token FROM dispositivos WHERE id=91')[0][0] == 'token-antigo-funciona'
    assert sql('SELECT otimizacao_ativa FROM dispositivos WHERE id=91')[0][0] == 0
    assert sql('SELECT peso_v13,horario_inicio,dias_semana FROM campanhas WHERE id=91')[0] == (3,'','')
    assert len(list((dbpath.parent / 'backups').glob('rotaads_pre_v1_3_*.sqlite3'))) == 1
    ok('Schema V1.3 aplicado com backup e preservação de campanhas e tokens V1.2')
    check(client.get('/admin/otimizacao'), 302, 'Otimização sem login')
    check(client.get('/api/anunciante/campanhas/91/horarios'), 401, 'Horário de anunciante sem login')
    check(client.post('/admin/entrar', data={'csrf_token':csrf(), 'username':'admin',
                                             'password':'senha-admin-teste-v13'}),302,'Login admin')
    check(client.get('/admin/otimizacao'),200,'Página otimização admin')
    check(client.get('/admin/ecra/novo'),200,'Página de ecrãs')
    check(client.post('/admin/ecra/91/otimizacao',data={'ativo':'1'}),400,'Bloqueio CSRF')
    ok('Painel restrito ao administrador e proteção CSRF')
    for company,email in [('Empresa A','a@teste.pt'),('Empresa B','b@teste.pt')]:
        check(client.post('/admin/anunciantes/criar',data={'csrf_token':csrf(),
           'nome':'Pessoa','empresa':company,'email':email,
           'senha':'senha-robusta-de-teste-v13'}),302,'Criar anunciante')
    aid,bid = [x[0] for x in sql('SELECT id FROM anunciantes ORDER BY id')]
    def new_campaign(name,aid):
        check(client.post('/admin/campanhas/nova',data={
          'csrf_token':csrf(), 'nome':name, 'anunciante':'Empresa',
          'cidade':'Lisboa', 'carros_contratados':'1','duracao_seg':'12',
          'anunciante_id':str(aid),'ficheiro':(io.BytesIO(PIXEL),'criativo.png')
        },content_type='multipart/form-data'),302,'Criar campanha')
        return sql('SELECT id FROM campanhas ORDER BY id DESC LIMIT 1')[0][0]
    ca = new_campaign('Anúncio A',aid)
    cb = new_campaign('Anúncio B',bid)
    check(client.post('/admin/ecra/novo',data={'csrf_token':csrf(),
         'nome':'Lisboa Smart','parceiro':'Frota','cidade':'Lisboa'}),302,'Novo ecrã')
    did,token = sql('SELECT id,token FROM dispositivos ORDER BY id DESC LIMIT 1')[0]
    for campaign in (ca,cb):
        check(client.post('/admin/atribuicoes',data={'csrf_token':csrf(),
             'dispositivo_id':str(did),'campanha_id':str(campaign),'acao':'atribuir'}),302,'Atribuir campanha')
    def playlist():
        response = client.get(f'/api/ecra/{token}/playlist')
        check(response,200,'Playlist')
        return response.json
    p = playlist()
    assert p['modo'] == 'classico' and [x['id'] for x in p['campanhas']] == [ca,cb]
    ok('Modo clássico por defeito preserva seleção e ordem V1.2')
    check(client.post(f'/admin/campanhas/{ca}/inteligencia',data={
        'csrf_token':csrf(),'peso_v13':'5','horario_inicio':'','horario_fim':''}),302,'Peso 5')
    check(client.post(f'/admin/campanhas/{cb}/inteligencia',data={
        'csrf_token':csrf(),'peso_v13':'1','horario_inicio':'','horario_fim':''}),302,'Peso 1')
    check(client.post(f'/admin/ecra/{did}/otimizacao',data={'csrf_token':csrf(),'ativo':'1'}),302,'Ligar inteligente')
    smart = playlist()
    freq = Counter(x['id'] for x in smart['campanhas'])
    assert smart['modo'] == 'inteligente' and freq[ca] > freq[cb] > 0, freq
    check(client.post(f'/api/ecra/{token}/sinal',json={}),200,'Heartbeat')
    check(client.post(f'/api/ecra/{token}/exibicao',json={'campanha_id':ca}),200,'Registo reprodução')
    ok('Ativação por ecrã e alternância ponderada, com reprodução antiga intacta')
    # Pôr uma janela duas horas à frente, bloqueando a campanha A na hora atual.
    now = portugal_now()
    start = (now + timedelta(hours=2)).strftime('%H:%M')
    end = (now + timedelta(hours=3)).strftime('%H:%M')
    check(client.post(f'/admin/campanhas/{ca}/inteligencia',data={
        'csrf_token':csrf(),'peso_v13':'5','horario_inicio':start,'horario_fim':end}),302,'Janela futura')
    assert ca not in [x['id'] for x in playlist()['campanhas']]
    check(client.post(f'/api/ecra/{token}/exibicao',json={'campanha_id':ca}),403,'Bloqueio pelo horário')
    check(client.post(f'/admin/campanhas/{ca}/inteligencia',data={
        'csrf_token':csrf(),'peso_v13':'5','horario_inicio':'','horario_fim':''}),302,'Remover janela')
    assert ca in [x['id'] for x in playlist()['campanhas']]
    ok('Horários bloqueiam campanhas fora da janela; remoção restaura exibição')
    check(client.get('/admin/otimizacao'),200,'Relatório de otimização')
    check(client.post(f'/admin/ecra/{did}/renovar-token',data={'csrf_token':csrf()}),302,'Renovar token')
    new_token = sql('SELECT token FROM dispositivos WHERE id=?',(did,))[0][0]
    assert new_token != token
    check(client.get(f'/api/ecra/{token}/playlist'),404,'Token antigo revogado')
    check(client.get(f'/api/ecra/{new_token}/playlist'),200,'Token novo funciona')
    ok('Rotação de token revoga o acesso antigo, mantendo os dados')
    check(client.post('/admin/sair',data={'csrf_token':csrf()}),302,'Sair admin')
    check(client.post('/anunciante/entrar',data={'csrf_token':csrf(),
         'email':'a@teste.pt','senha':'senha-robusta-de-teste-v13'}),302,'Login A')
    check(client.get(f'/api/anunciante/campanhas/{ca}/horarios'),200,'Horas de A')
    check(client.get(f'/anunciante/campanhas/{ca}/horarios.csv'),200,'CSV A')
    check(client.get(f'/api/anunciante/campanhas/{cb}/horarios'),404,'Proibir API B')
    check(client.get(f'/anunciante/campanhas/{cb}/horarios.csv'),404,'Proibir CSV B')
    check(client.get('/admin/otimizacao'),302,'Proibir painel admin')
    ok('Métricas horárias e CSV separados entre anunciantes')
    check(client.post('/anunciante/sair',data={'csrf_token':csrf()}),302,'Logout A')
    check(client.post('/anunciante/entrar',data={'csrf_token':csrf(),
         'email':'b@teste.pt','senha':'senha-robusta-de-teste-v13'}),302,'Login B')
    check(client.get(f'/api/anunciante/campanhas/{ca}/horarios'),404,'Proibir API A a B')
    ok('Anunciante B não acede ao relatório de A')


def main():
    pure_tests()
    with tempfile.TemporaryDirectory(prefix='rotaads_v13_test_') as folder:
        root = Path(folder)
        migration_test(root / 'migracao')
        app_tests(root / 'aplicacao')
    print('\nRESULTADO: testes automáticos da V1.3 concluídos com sucesso.')
    print('Ainda é necessário validar o tablet Android e a operação sob rede real.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('FALHA NOS TESTES V1.3:', repr(exc), file=sys.stderr)
        raise
