"""Testes funcionais da RotaAds V1.1 (banco e uploads TEMPORÁRIOS).
Executar no Windows depois de instalar dependências: python testes_v1_1.py
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

ROOT=Path(__file__).resolve().parent
PIXEL=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/5d8AAAAASUVORK5CYII=')


def main():
  with tempfile.TemporaryDirectory(prefix='rotaads_v11_test_') as folder:
    base=Path(folder)
    dbpath=base/'instance'/'rotaads.sqlite3'
    dbpath.parent.mkdir(parents=True)
    # Simula tabela existente V1.0 para testar migração automática e backup.
    with closing(sqlite3.connect(dbpath)) as db, db:
      db.execute('''CREATE TABLE campanhas(id INTEGER PRIMARY KEY, nome TEXT NOT NULL,
      anunciante TEXT NOT NULL, cidade TEXT DEFAULT '', carros_contratados INTEGER NOT NULL,
      ativo INTEGER DEFAULT 1, data_inicio TEXT, data_fim TEXT, ficheiro TEXT,
      tipo_media TEXT, duracao_seg INTEGER DEFAULT 12, cupao_ativo INTEGER DEFAULT 0,
      cupao_codigo TEXT DEFAULT '', cupao_descricao TEXT DEFAULT '', cupao_url TEXT DEFAULT '',
      criado_em TEXT NOT NULL)''')
      db.execute("INSERT INTO campanhas(id,nome,anunciante,carros_contratados,criado_em) VALUES(99,'Campanha Antiga','Cliente Antigo',2,'2026-01-01T00:00:00+00:00')")
      db.commit()
    os.environ.update(DATABASE_PATH=str(dbpath),UPLOAD_FOLDER=str(base/'uploads'),
      ADMIN_USERNAME='admin',ADMIN_PASSWORD='senha-admin-isolada',
      SECRET_KEY='chave-de-teste-isolada',SITE_URL='http://127.0.0.1:5000')
    spec=importlib.util.spec_from_file_location('rotaads_teste_11',ROOT/'app.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    client=mod.app.test_client()
    def status(r,expect,label):
      assert r.status_code==expect, f'{label} esperava {expect}, recebeu {r.status_code}: {r.get_data(as_text=True)[:200]}'
    def csrf(web):
      with web.session_transaction() as session:
        session.setdefault('_csrf','token-isolado-de-teste')
        return session['_csrf']
    def sql(stmt,params=()):
      with closing(sqlite3.connect(dbpath)) as db, db:
        return db.execute(stmt,params).fetchall()
    def ok(label): print('  OK  '+label)

    assert sql('SELECT nome FROM campanhas WHERE id=99')[0][0]=='Campanha Antiga'
    assert 'anunciante_id' in {col[1] for col in sql('PRAGMA table_info(campanhas)')}, 'Coluna anunciante_id não encontrada após migração'
    assert len(list((dbpath.parent/'backups').glob('rotaads_pre_v1_1_*.sqlite3')))==1
    ok('Migração V1.0 -> V1.1 preserva campanha antiga e cria backup')

    status(client.get('/anunciante'),302,'Portal sem login')
    status(client.get('/api/anunciante/resumo'),401,'API sem login')
    status(client.get('/admin/anunciantes'),302,'Admin sem login')
    status(client.post('/admin/entrar',data={'csrf_token':csrf(client),'username':'admin','password':'senha-admin-isolada'}),302,'Admin login')
    status(client.get('/admin/anunciantes'),200,'Admin anunciantes')
    ok('Rotas protegidas')

    for company,email in [('Empresa A','a@empresa.pt'),('Empresa B','b@empresa.pt')]:
      status(client.post('/admin/anunciantes/criar',data={'csrf_token':csrf(client),'nome':'Pessoa Teste',
          'empresa':company,'email':email,'senha':'palavra-passe-forte-123'}),302,'Criar anunciante')
    accounts=sql('SELECT id,email FROM anunciantes ORDER BY id')
    assert len(accounts)==2
    aid,bid=accounts[0][0],accounts[1][0]
    ok('Criar contas individuais com hash de palavra-passe')

    status(client.post('/admin/campanhas/nova',data={
      'csrf_token':csrf(client),'nome':'Campanha da Empresa A','anunciante':'Empresa A',
      'cidade':'Lisboa','carros_contratados':'1','duracao_seg':'12',
      'cupao_ativo':'sim','cupao_codigo':'DESCONTO10','anunciante_id':str(aid),
      'ficheiro':(io.BytesIO(PIXEL),'criativo.png')},content_type='multipart/form-data'),302,'Campanha A')
    cid=sql('SELECT id FROM campanhas WHERE anunciante_id=?',(aid,))[0][0]
    status(client.post('/admin/ecra/novo',data={'csrf_token':csrf(client),'nome':'Ecrã 1',
      'parceiro':'Frota 1','cidade':'Lisboa'}),302,'Criar ecrã')
    device_id,token=sql('SELECT id,token FROM dispositivos ORDER BY id DESC LIMIT 1')[0]
    status(client.post('/admin/atribuicoes',data={'csrf_token':csrf(client),
      'dispositivo_id':str(device_id),'campanha_id':str(cid),'acao':'atribuir'}),302,'Atribuição')
    status(client.post(f'/api/ecra/{token}/sinal'),200,'Heartbeat')
    status(client.post(f'/api/ecra/{token}/exibicao',json={'campanha_id':cid}),200,'Reprodução')
    status(client.get(f'/oferta/{cid}'),200,'Leitura QR')
    status(client.post(f'/admin/campanhas/{cid}/resgatar',data={'csrf_token':csrf(client),'referencia':'test-resgate'}),302,'Resgate')
    ok('V1.0 intacta: campanha, atribuição, heartbeat, reprodução e QR')

    client.post('/admin/sair',data={'csrf_token':csrf(client)})
    # Anunciante A apenas pode ver a sua própria campanha.
    status(client.post('/anunciante/entrar',data={'csrf_token':csrf(client),
      'email':'a@empresa.pt','senha':'palavra-passe-forte-123'}),302,'Login anunciante A')
    status(client.get('/anunciante'),200,'Dashboard anunciante A')
    summary=client.get('/api/anunciante/resumo')
    status(summary,200,'API resumo A')
    assert summary.json['carros_online']==1,summary.json
    assert summary.json['reproducoes']==1 and summary.json['leituras_qr']==1
    assert summary.json['resgates']==1 and summary.json['carros_contratados']==1
    status(client.get(f'/anunciante/campanhas/{cid}'),200,'Detalhe A')
    status(client.get(f'/api/anunciante/campanhas/{cid}/metricas'),200,'API detalhe A')
    status(client.get(f'/anunciante/campanhas/{cid}/relatorio.csv'),200,'CSV A')
    status(client.get('/anunciante/campanhas/99'),404,'Campanha antiga sem associação')
    ok('Anunciante A vê apenas resultados da sua campanha, incluindo CSV')

    status(client.post('/anunciante/sair',data={'csrf_token':csrf(client)}),302,'Logout A')
    status(client.post('/anunciante/entrar',data={'csrf_token':csrf(client),
      'email':'b@empresa.pt','senha':'palavra-passe-forte-123'}),302,'Login B')
    other=client.get('/api/anunciante/resumo')
    assert other.json['carros_online']==0 and other.json['reproducoes']==0
    assert other.json['campanhas']==[]
    for url in (f'/anunciante/campanhas/{cid}',
                f'/api/anunciante/campanhas/{cid}/metricas',
                f'/anunciante/campanhas/{cid}/relatorio.csv'):
      status(client.get(url),404,'Isolamento entre empresas')
    ok('Segurança: cliente B NÃO consulta campanhas, métricas nem CSV do cliente A')

    status(client.post('/anunciante/sair',data={'csrf_token':csrf(client)}),302,'Sair B')
    client.post('/admin/entrar',data={'csrf_token':csrf(client),'username':'admin','password':'senha-admin-isolada'})
    status(client.post(f'/admin/anunciantes/{aid}/alternar',data={'csrf_token':csrf(client)}),302,'Bloquear A')
    client.post('/admin/sair',data={'csrf_token':csrf(client)})
    client.post('/anunciante/entrar',data={'csrf_token':csrf(client),
        'email':'a@empresa.pt','senha':'palavra-passe-forte-123'})
    status(client.get('/api/anunciante/resumo'),401,'Cliente bloqueado')
    ok('Conta desativada perde acesso à API')
    print('\nRESULTADO: testes funcionais V1.1 concluídos com sucesso.')
    print('Estes testes usam base de dados isolada e não alteram os dados reais.')
    print('Ainda é necessário testar tablets Android reais e sessões concorrentes em rede.')

if __name__=='__main__':
  try: main()
  except Exception as e:
    import traceback
    print('\nFALHA:',repr(e),file=sys.stderr)
    traceback.print_exc()
    raise SystemExit(1)
