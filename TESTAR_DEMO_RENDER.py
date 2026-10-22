"""Smoke-test após instalar as dependências num computador; não requer Render."""
import os, sys, tempfile
from pathlib import Path
from contextlib import closing
import sqlite3

with tempfile.TemporaryDirectory(prefix='rotaads_demo_render_') as td:
    os.environ['DEMO_MODE'] = '1'
    os.environ['DATABASE_PATH'] = str(Path(td)/'instance'/'rotaads.sqlite3')
    os.environ['UPLOAD_FOLDER'] = str(Path(td)/'uploads')
    os.environ['SECRET_KEY'] = 'demo-test-only-keep-secret'
    os.environ['ADMIN_PASSWORD'] = 'password-for-testing-only'
    os.environ['DEMO_ACCESS_PASSWORD'] = 'demo-visitor-testing-only'
    os.environ['DEMO_ADVERTISER_PASSWORD'] = 'demo-advertiser-testing-only'
    import app
    client=app.app.test_client()
    assert client.get('/healthz').status_code == 200
    assert client.get('/').status_code == 401
    import base64
    auth='Basic '+base64.b64encode(b'visitante:demo-visitor-testing-only').decode()
    for url in ('/', '/contacto?tipo=frota','/admin/entrar','/anunciante/entrar'):
        assert client.get(url,headers={'Authorization':auth}).status_code == 200, url
    with closing(sqlite3.connect(os.environ['DATABASE_PATH'])) as db:
        counts = [db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in
            ('leads','campanhas','anunciantes','frotas_v14','motoristas_v14','veiculos_v14','contratos_v14','pagamentos_v14')]
    assert counts == [4,2,1,1,2,2,2,2], counts
    print('OK: demo protegida, rotas acessíveis, dados fictícios, sem alterar SQLite real.')
