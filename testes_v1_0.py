"""Teste funcional isolado da V1.0. Não altera a base de dados do utilizador.

Executar depois de instalar requisitos: python testes_v1_0.py
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
ONE_PIXEL_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/5d8AAAAASUVORK5CYII='
)


def main():
    with tempfile.TemporaryDirectory(prefix='rotaads_teste_') as td:
        temp = Path(td)
        os.environ['DATABASE_PATH'] = str(temp / 'teste.sqlite3')
        os.environ['UPLOAD_FOLDER'] = str(temp / 'uploads')
        os.environ['ADMIN_USERNAME'] = 'admin'
        os.environ['ADMIN_PASSWORD'] = 'senha-temporaria-usada-apenas-no-teste'
        os.environ['SECRET_KEY'] = 'chave-aleatoria-apenas-para-teste-isolado'
        os.environ['SITE_URL'] = 'http://127.0.0.1:5000'

        spec = importlib.util.spec_from_file_location('rotaads_app_teste', ROOT / 'app.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        web = mod.app.test_client()

        def assert_status(response, expected, description):
            if response.status_code != expected:
                raise AssertionError(f'{description}: esperado HTTP {expected}, obtido HTTP {response.status_code}. Resposta: {response.get_data(as_text=True)[:350]}')

        def token():
            with web.session_transaction() as s:
                if '_csrf' not in s:
                    s['_csrf'] = 'token-de-teste-isolado'
                return s['_csrf']

        def db_one(sql, params=()):
            with closing(sqlite3.connect(str(temp / 'teste.sqlite3'))) as conn, conn:
                return conn.execute(sql, params).fetchone()

        def ok(label):
            print('  OK - ' + label)

        # 1. Site e os quatro formulários.
        assert_status(web.get('/'), 200, 'Página inicial')
        for kind in ('anunciante', 'agencia', 'frota', 'motorista'):
            assert_status(web.get('/contacto?tipo=' + kind), 200, 'Formulário ' + kind)
        ok('Site e quatro formulários')

        # 2. Obrigatoriedade de token CSRF.
        assert_status(web.post('/contacto?tipo=anunciante', data={'nome': 'Sem token'}), 400, 'Proteção do formulário')
        ok('Proteção básica dos formulários')

        # 3. Submissão e persistência dos quatro perfis.
        for kind in ('anunciante', 'agencia', 'frota', 'motorista'):
            r = web.post('/contacto?tipo=' + kind, data={
                'csrf_token': token(),
                'nome': 'Pessoa Teste',
                'email': 'exemplo@teste.pt',
                'empresa': 'Empresa Exemplo',
                'cidade': 'Lisboa',
                'carros': '1' if kind == 'motorista' else '10',
                'privacidade': 'sim',
            })
            assert_status(r, 302, 'Pedido ' + kind)
        assert db_one('SELECT count(*) FROM leads')[0] == 4
        ok('Envio dos quatro pedidos e gravação em SQLite')

        # 4. Autenticação do painel.
        assert_status(web.get('/admin'), 302, 'Área protegida')
        r = web.post('/admin/entrar', data={
            'username': 'admin',
            'password': 'senha-temporaria-usada-apenas-no-teste',
            'csrf_token': token(),
        })
        assert_status(r, 302, 'Login administrativo')
        assert_status(web.get('/admin'), 200, 'Painel')
        assert_status(web.get('/admin/pedidos'), 200, 'Pedidos')
        exported = web.get('/admin/pedidos.csv')
        assert_status(exported, 200, 'Exportação CSV')
        assert b'Pessoa Teste' in exported.data
        ok('Login, painel, pedidos e exportação CSV')

        # 5. Criação de campanha de pacote com cupão.
        r = web.post('/admin/campanhas/nova', data={
            'csrf_token': token(),
            'nome': 'Campanha Teste',
            'anunciante': 'Restaurante Exemplo',
            'cidade': 'Lisboa',
            'carros_contratados': '1',
            'duracao_seg': '12',
            'cupao_ativo': 'sim',
            'cupao_codigo': 'TESTE10',
            'cupao_descricao': '10 por cento de desconto',
            'ficheiro': (io.BytesIO(ONE_PIXEL_PNG), 'anuncio.png'),
        }, content_type='multipart/form-data')
        assert_status(r, 302, 'Nova campanha')
        row = db_one('SELECT id, ficheiro FROM campanhas ORDER BY id DESC LIMIT 1')
        assert row is not None, 'A campanha não foi gravada'
        campaign_id, uploaded_filename = row
        assert_status(web.get('/media/' + uploaded_filename), 200, 'Média da campanha')
        ok('Criar campanha, carregar imagem e ativar cupão')

        # 6. Dispositivos e limite contratado (um carro).
        for device in ('TVDE 001', 'TVDE 002'):
            r = web.post('/admin/ecra/novo', data={
                'csrf_token': token(), 'nome': device,
                'parceiro': 'Frota Exemplo', 'cidade': 'Lisboa',
            })
            assert_status(r, 302, 'Registo de ecrã')
        devices = db_one('SELECT count(*) FROM dispositivos')[0]
        assert devices == 2
        with closing(sqlite3.connect(str(temp / 'teste.sqlite3'))) as conn, conn:
            items = conn.execute('SELECT id, token FROM dispositivos ORDER BY id').fetchall()
        first_id, device_token = items[0]
        second_id, _ = items[1]
        for device_id in (first_id, second_id):
            r = web.post('/admin/atribuicoes', data={
                'csrf_token': token(),
                'dispositivo_id': str(device_id),
                'campanha_id': str(campaign_id),
                'acao': 'atribuir',
            })
            assert_status(r, 302, 'Atribuição')
        assert db_one('SELECT count(*) FROM atribuicoes')[0] == 1, 'O sistema excedeu o pacote de um carro'
        ok('Registar ecrãs e respeitar limite de carros contratado')

        # 7. Player, playlist, sinal online, exibição contabilizada.
        assert_status(web.get('/player/' + device_token), 200, 'Player')
        r = web.get('/api/ecra/' + device_token + '/playlist')
        assert_status(r, 200, 'Playlist')
        assert len(r.json['campanhas']) == 1
        assert_status(web.post('/api/ecra/' + device_token + '/sinal'), 200, 'Sinal online')
        assert db_one('SELECT ultimo_sinal FROM dispositivos WHERE id=?', (first_id,))[0]
        for _ in range(2):
            assert_status(web.post('/api/ecra/' + device_token + '/exibicao', json={'campanha_id': campaign_id}), 200, 'Exibição')
        assert db_one('SELECT count(*) FROM exibicoes')[0] == 1, 'Duas exibições quase simultâneas não deveriam duplicar'
        ok('Player, playlist, sinal de atividade e exibições')

        # 8. QR e resgate.
        r = web.get('/qr/' + str(campaign_id) + '.png')
        assert_status(r, 200, 'Imagem QR Code')
        assert r.mimetype == 'image/png'
        assert_status(web.get('/oferta/' + str(campaign_id)), 200, 'Página da oferta')
        assert db_one('SELECT count(*) FROM leituras_qr')[0] == 1
        r = web.post('/admin/campanhas/' + str(campaign_id) + '/resgatar', data={
            'csrf_token': token(), 'referencia': 'TESTE-RESGATE',
        })
        assert_status(r, 302, 'Resgate manual')
        assert db_one('SELECT count(*) FROM resgates_cupao')[0] == 1
        ok('QR Code, acesso à oferta e resgate manual')

        # 9. Pausa da campanha deixa playlist vazia.
        r = web.post('/admin/campanhas/' + str(campaign_id) + '/alternar', data={'csrf_token': token()})
        assert_status(r, 302, 'Pausar campanha')
        r = web.get('/api/ecra/' + device_token + '/playlist')
        assert_status(r, 200, 'Playlist pausada')
        assert r.json['campanhas'] == [], 'Campanha pausada continuou em reprodução'
        ok('Pausa de campanha impede novas reproduções')

        # 10. Proteção contra dispositivos inexistentes.
        assert_status(web.get('/api/ecra/token-inexistente/playlist'), 404, 'Token inválido')
        ok('Player não acessível sem token válido')

        print('\nRESULTADO: todos os testes automáticos passaram.')
        print('IMPORTANTE: ainda falta testar a reprodução visual num navegador Android real.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('\nFALHA NOS TESTES: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
