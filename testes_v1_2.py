"""Testes de integração da RotaAds V1.2: tudo numa pasta SQLite TEMPORÁRIA.

NUNCA utiliza o banco operacional. Executar: python testes_v1_2.py
"""
import base64
import importlib.util
import io
import os
import sqlite3
from contextlib import closing
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
PIXEL = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/5d8AAAAASUVORK5CYII=')


def main():
    with tempfile.TemporaryDirectory(prefix='rotaads_v12_teste_') as temp:
        dbpath = Path(temp)/'instance'/'rotaads.sqlite3'
        dbpath.parent.mkdir(parents=True)
        # Um subconjunto real do esquema V1.1: sem colunas/zonas V1.2.
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.executescript('''
            CREATE TABLE campanhas(
                id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
                anunciante TEXT NOT NULL, cidade TEXT NOT NULL DEFAULT '',
                carros_contratados INTEGER NOT NULL, ativo INTEGER NOT NULL DEFAULT 1,
                data_inicio TEXT,data_fim TEXT,ficheiro TEXT,tipo_media TEXT,
                duracao_seg INTEGER NOT NULL DEFAULT 12,cupao_ativo INTEGER NOT NULL DEFAULT 0,
                cupao_codigo TEXT NOT NULL DEFAULT '',cupao_descricao TEXT NOT NULL DEFAULT '',
                cupao_url TEXT NOT NULL DEFAULT '',criado_em TEXT NOT NULL,anunciante_id INTEGER
            );
            CREATE TABLE dispositivos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL,parceiro TEXT NOT NULL DEFAULT '',
                cidade TEXT NOT NULL DEFAULT '',token TEXT NOT NULL UNIQUE,ativo INTEGER NOT NULL DEFAULT 1,
                ultimo_sinal TEXT,ultima_lat REAL,ultima_lon REAL,criado_em TEXT NOT NULL
            );
            CREATE TABLE exibicoes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,dispositivo_id INTEGER NOT NULL,
                campanha_id INTEGER NOT NULL,criado_em TEXT NOT NULL
            );
            INSERT INTO campanhas(id,nome,anunciante,carros_contratados,criado_em)
                VALUES(99,'Campanha preservada V1.1','Cliente antigo',2,'2026-01-01T00:00:00+00:00');
            INSERT INTO dispositivos(id,nome,token,criado_em)
                VALUES(88,'Ecrã anterior','token-preservado','2026-01-01T00:00:00+00:00');
            ''')
        os.environ.update(
            DATABASE_PATH=str(dbpath), UPLOAD_FOLDER=str(Path(temp)/'uploads'),
            ADMIN_USERNAME='admin', ADMIN_PASSWORD='senha-admin-v12',
            SECRET_KEY='segredo-de-teste-12', SITE_URL='http://127.0.0.1:5000'
        )
        spec = importlib.util.spec_from_file_location('rotaads_teste_12', ROOT/'app.py')
        appmod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(appmod)
        app = appmod.app
        client = app.test_client()

        def sql(query, args=()):
            with closing(sqlite3.connect(dbpath)) as conn, conn:
                return conn.execute(query, args).fetchall()
        def csrf(web):
            with web.session_transaction() as sess:
                sess.setdefault('_csrf', 'csrf-isolado-12')
                return sess['_csrf']
        def check(resp, code, detail):
            assert resp.status_code == code, f'{detail}: esperado {code}, recebido {resp.status_code}, body={resp.get_data(as_text=True)[:250]}'
        def ok(txt):
            print('  OK  ' + txt)

        assert sql('SELECT nome FROM campanhas WHERE id=99')[0][0] == 'Campanha preservada V1.1'
        assert sql('SELECT nome FROM dispositivos WHERE id=88')[0][0] == 'Ecrã anterior'
        assert len(list((dbpath.parent/'backups').glob('rotaads_pre_v1_2_*.sqlite3'))) == 1
        assert 'zona_id' in [x[1] for x in sql('PRAGMA table_info(exibicoes)')]
        assert 'ultima_localizacao_em' in [x[1] for x in sql('PRAGMA table_info(dispositivos)')]
        assert sql('SELECT COUNT(*) FROM zonas')[0][0] == 0
        ok('Migração V1.1 -> V1.2 e backup automático preservam os registos antigos')

        check(client.get('/admin/zonas'), 302, 'Zonas não autenticado')
        check(client.get('/admin/mapa'), 302, 'Mapa não autenticado')
        check(client.get('/api/admin/mapa'), 302, 'API GPS não autenticada')
        check(client.get('/api/anunciante/campanhas/99/zonas'), 401, 'API anunciante não autenticado')
        check(client.post('/admin/zonas/nova',data={'nome':'Sem CSRF'}), 302, 'Admin não autenticado')
        check(client.post('/admin/entrar', data={'csrf_token':csrf(client), 'username':'admin', 'password':'senha-admin-v12'}),302,'Login admin')
        check(client.post('/admin/zonas/nova',data={'nome':'Sem CSRF'}),400,'Bloqueio CSRF')
        ok('Mapa e zonas protegidos por autenticação e validação CSRF')

        def add_zone(nome, lat, lon, raio=1200, prioridade=0):
            check(client.post('/admin/zonas/nova',data={'csrf_token':csrf(client),
                'nome':nome,'cidade':'Lisboa','latitude':str(lat),'longitude':str(lon),
                'raio_m':str(raio),'prioridade':str(prioridade)}),302,'Criar zona')
            return sql('SELECT id FROM zonas ORDER BY id DESC LIMIT 1')[0][0]
        zone_id = add_zone('Lisboa Centro',38.7223,-9.1393)
        check(client.get('/admin/zonas'),200,'Página zonas')
        check(client.post('/admin/zonas/nova',data={'csrf_token':csrf(client),'nome':'Errada',
             'latitude':'100','longitude':'-9','raio_m':'1000','prioridade':'0'}),302,'Validar zonas')
        assert sql('SELECT COUNT(*) FROM zonas')[0][0] == 1
        check(client.post(f'/admin/zonas/{zone_id}/editar',data={'csrf_token':csrf(client),
            'nome':'Lisboa Centro','cidade':'Lisboa','latitude':'38.7223','longitude':'-9.1393',
            'raio_m':'1500','prioridade':'2'}),302,'Editar zona')
        assert sql('SELECT raio_m FROM zonas WHERE id=?',(zone_id,))[0][0] == 1500
        ok('Criar, validar e editar zonas circulares com prioridade')

        for company,email in [('Cliente A','cliente.a@teste.pt'),('Cliente B','cliente.b@teste.pt')]:
            check(client.post('/admin/anunciantes/criar',data={'csrf_token':csrf(client),
                'nome':'Pessoa Teste','empresa':company,'email':email,'senha':'senha-grande-teste-123'}),302,'Criar anunciante')
        aid,bid = [x[0] for x in sql('SELECT id FROM anunciantes ORDER BY id')]
        def make_campaign(name, account):
            check(client.post('/admin/campanhas/nova',data={
                'csrf_token':csrf(client), 'nome':name,'anunciante':'Cliente A',
                'cidade':'Lisboa','carros_contratados':'1','duracao_seg':'12',
                'anunciante_id':str(account),'ficheiro':(io.BytesIO(PIXEL), 'imagem.png')
            }, content_type='multipart/form-data'),302,'Criar campanha')
            return sql('SELECT id FROM campanhas ORDER BY id DESC LIMIT 1')[0][0]
        target_id = make_campaign('Anúncio Lisboa', aid)
        regular_id = make_campaign('Anúncio genérico', aid)
        other_id = make_campaign('Outra empresa', bid)
        check(client.post('/admin/ecra/novo',data={'csrf_token':csrf(client),
            'nome':'Carro Lisboa','parceiro':'TVDE','cidade':'Lisboa'}),302,'Ecrã')
        device_id, token = sql('SELECT id,token FROM dispositivos ORDER BY id DESC LIMIT 1')[0]
        # Associa 2 campanhas à mesma viatura; pacotes de 1 carro por campanha.
        for cid in (target_id, regular_id):
            check(client.post('/admin/atribuicoes', data={'csrf_token':csrf(client),
                'dispositivo_id':str(device_id),'campanha_id':str(cid),'acao':'atribuir'}),302,'Atribuir ecrã')
        check(client.post(f'/admin/campanhas/{target_id}/zonas', data={'csrf_token':csrf(client),
            'zona_ids':[str(zone_id)]}),302,'Vincular zona à campanha')
        check(client.get(f'/admin/campanhas/{target_id}'),200,'Detalhe campanha com zonas')
        ok('Campanhas e atribuições V1.1 continuam operacionais; zona associada por campanha')

        def playlist():
            r=client.get(f'/api/ecra/{token}/playlist')
            check(r,200,'Playlist');return [c['id'] for c in r.json['campanhas']]
        check(client.post(f'/api/ecra/{token}/sinal',json={}),200,'Heartbeat sem GPS')
        assert regular_id in playlist() and target_id not in playlist()
        pos={'consentimento_gps':True,'lat':38.7223,'lon':-9.1393,'precisao_m':15}
        check(client.post(f'/api/ecra/{token}/sinal',json=pos),200,'Sinal GPS')
        assert regular_id in playlist() and target_id in playlist()
        check(client.post(f'/api/ecra/{token}/exibicao',json={'campanha_id':target_id}),200,'Reprodução geolocalizada')
        assert sql('SELECT zona_id FROM exibicoes WHERE campanha_id=?',(target_id,))[0][0] == zone_id
        status=client.get('/api/admin/mapa')
        check(status,200,'Mapa admin')
        assert status.json['com_gps']==1
        assert status.json['online']>=1
        assert all('token' not in d for d in status.json['dispositivos'])
        check(client.get('/admin/mapa'),200,'Página mapa')
        ok('GPS recente dentro da zona: campanha liberada, mapa protegido, exposição por zona')

        invalid={'consentimento_gps':True,'lat':180,'lon':-9.1393,'precisao_m':1}
        check(client.post(f'/api/ecra/{token}/sinal',json=invalid),400,'Coordenadas inválidas')
        check(client.post(f'/api/ecra/{token}/sinal',json={'consentimento_gps':True,'lat':0,'lon':0,'precisao_m':15}),200,'Muda de zona')
        assert target_id not in playlist() and regular_id in playlist()
        check(client.post(f'/api/ecra/{token}/exibicao',json={'campanha_id':target_id}),403,'Bloquear reprodução fora da zona')
        check(client.post(f'/api/ecra/{token}/sinal',json={'consentimento_gps':False}),200,'Desligar GPS')
        assert sql('SELECT ultima_lat,ultima_lon,ultima_localizacao_em FROM dispositivos WHERE id=?',(device_id,))[0] == (None,None,None)
        assert target_id not in playlist() and regular_id in playlist()
        ok('GPS inválido rejeitado; fora de zona não reproduz; desligar apaga localização')

        check(client.post(f'/admin/zonas/{zone_id}/alternar',data={'csrf_token':csrf(client)}),302,'Pausar zona')
        check(client.post(f'/api/ecra/{token}/sinal',json=pos),200,'Voltar ao centro')
        assert target_id not in playlist()
        check(client.post(f'/admin/zonas/{zone_id}/alternar',data={'csrf_token':csrf(client)}),302,'Ativar zona')
        assert target_id in playlist()
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute("UPDATE dispositivos SET ultima_localizacao_em='2020-01-01T00:00:00+00:00' WHERE id=?",(device_id,))
            db.commit()
        assert target_id not in playlist()
        ok('Pausar zona e localização desatualizada bloqueiam anúncios segmentados')

        check(client.post('/admin/sair',data={'csrf_token':csrf(client)}),302,'Sair admin')
        check(client.post('/anunciante/entrar',data={'csrf_token':csrf(client),
            'email':'cliente.a@teste.pt','senha':'senha-grande-teste-123'}),302,'Anunciante A')
        check(client.get('/anunciante'),200,'Dashboard anunciantes')
        geo=client.get(f'/api/anunciante/campanhas/{target_id}/zonas')
        check(geo,200,'Métricas geográficas')
        assert geo.json['zonas'][0]['nome']=='Lisboa Centro'
        assert geo.json['zonas'][0]['reproducoes']==1
        assert 'lat' not in str(geo.json).lower() and 'lon' not in str(geo.json).lower()
        check(client.get(f'/anunciante/campanhas/{target_id}/zonas.csv'),200,'CSV agregado')
        check(client.get(f'/api/anunciante/campanhas/{other_id}/zonas'),404,'Bloqueio de empresa B')
        check(client.get('/api/admin/mapa'),302,'Mapa apenas para admin')
        ok('Portal preservado, estatísticas por zona, CSV e separação entre empresas')

        check(client.post('/anunciante/sair',data={'csrf_token':csrf(client)}),302,'Sair A')
        check(client.post('/anunciante/entrar',data={'csrf_token':csrf(client),
            'email':'cliente.b@teste.pt','senha':'senha-grande-teste-123'}),302,'Anunciante B')
        check(client.get(f'/api/anunciante/campanhas/{target_id}/zonas'),404,'B não vê A')
        check(client.get(f'/anunciante/campanhas/{target_id}/zonas.csv'),404,'B não exporta A')
        ok('Anunciante B não obtém resultados geográficos do anunciante A')
        print('\nRESULTADO: testes V1.2 concluídos (ambiente temporário e sem alterar a base operacional).')
        print('Teste físico com tablet GPS + HTTPS ainda é necessário.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('\nFALHA:',repr(error),file=sys.stderr)
        raise
