"""Worker de testes V1.4: corre em outro processo para libertar o banco no Windows."""
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from datetime import datetime, timezone

assert os.getenv('ROTAADS_V14_TEST') == '1'
base = Path(sys.argv[1]).resolve()
assert Path(os.environ['DATABASE_PATH']).resolve().is_relative_to(base)

import app as m
from frotas_v14 import parse_money, euros, generate_payments, month_bounds
from migrar_da_v1_3_1 import migrate


def check(v, label):
    if not v: raise AssertionError(label)
    print('  OK -', label)


def status(resp, n, title):
    check(resp.status_code == n,title + f' (HTTP {resp.status_code}, esperado {n})')


client = m.app.test_client()
for route in ('/admin/frotas','/admin/motoristas','/admin/veiculos','/admin/contratos','/admin/pagamentos',
              '/admin/pagamentos.csv','/admin/frotas/resumo.json'):
    status(client.get(route),302,'Sem login bloqueado: ' + route)

with client.session_transaction() as s:
    s['admin_logged'] = True
    s['_csrf'] = 'segredo-csrf-v14'
csrf = {'csrf_token':'segredo-csrf-v14'}

for route in ('/admin/frotas','/admin/motoristas','/admin/veiculos','/admin/contratos','/admin/pagamentos'):
    status(client.get(route),200,'Vista carregada: '+route)
status(client.post('/admin/frotas/criar',data={'nome':'Sem CSRF'}),400,'CSRF impede criação de frota')


def post(route,data):
    return client.post(route,data={**csrf,**data})


def one(sql, par=()):
    with closing(sqlite3.connect(os.environ['DATABASE_PATH'])) as db:
        return db.execute(sql,par).fetchone()


def amount(table):
    return one(f'SELECT COUNT(*) FROM {table}')[0]

status(post('/admin/frotas/criar',{'nome':'Parceiro TVDE','empresa':'Lisboa Fleet, Lda',
    'email':'fleet@teste.pt','cidade':'Lisboa','capacidade':'5'}),302,'Criar frota')
check(amount('frotas_v14')==1,'Frota gravada')
status(post('/admin/motoristas/criar',{'nome':'Motorista Empresa','email':'motorista@teste.pt',
    'frota_id':'1'}),302,'Criar motorista da frota')
status(post('/admin/motoristas/criar',{'nome':'Motorista Individual','email':'individual@teste.pt',
    'frota_id':''}),302,'Criar motorista independente')
check(amount('motoristas_v14')==2,'Motoristas gravados')
with m.app.app_context():
    db=m.get_db()
    db.execute("INSERT INTO dispositivos(nome,token,criado_em) VALUES('Ecrã V1.3.1', 'segredo-apenas-para-testes',?)",(m.now_iso(),))
    db.commit()
status(post('/admin/veiculos/criar',{'matricula':'AA-01-AA','marca':'Tesla','modelo':'3',
    'frota_id':'1','motorista_id':'1','dispositivo_id':'1'}),302,'Criar carro com frota + motorista + ecrã')
check(amount('veiculos_v14')==1 and one('SELECT dispositivo_id FROM veiculos_v14')[0]==1,
      'Ecrã associado a veículo sem modificar o cadastro de dispositivos')
status(post('/admin/veiculos/criar',{'matricula':'AA-01-AB','frota_id':'','motorista_id':'2',
    'dispositivo_id':''}),302,'Criar carro independente')
check(amount('veiculos_v14')==2,'Segundo carro cadastrado')
status(post('/admin/veiculos/criar',{'matricula':'AA-01-AC','frota_id':'','motorista_id':'1'}),302,
    'Tentativa indevida de trocar de frota é processada com validação')
check(amount('veiculos_v14')==2,'Motorista de frota não pode ser atribuído a carro independente')
status(post('/admin/veiculos/criar',{'matricula':'AA-01-AB','motorista_id':'2'}),302,'Matrícula repetida rejeitada')
check(amount('veiculos_v14')==2,'Matrícula duplicada não gera registo')

status(post('/admin/contratos/criar',{'veiculo_id':'1','beneficiario_tipo':'FROTA','beneficiario_id':'1',
       'valor_mensal':'145,90','data_inicio':'2026-10-01','dia_vencimento':'10'}),302,
       'Registar contrato de cedência à frota')
status(post('/admin/contratos/criar',{'veiculo_id':'2','beneficiario_tipo':'MOTORISTA','beneficiario_id':'2',
       'valor_mensal':'99,00','data_inicio':'2026-10-01','dia_vencimento':'15'}),302,
       'Registar contrato de cedência a motorista individual')
check(amount('contratos_v14')==2 and one('SELECT valor_centimos FROM contratos_v14 WHERE id=1')[0]==14590,
      'Mensalidade gravada em cêntimos sem arredondamentos')
status(post('/admin/contratos/criar',{'veiculo_id':'1','beneficiario_tipo':'FROTA','beneficiario_id':'1',
       'valor_mensal':'200,00','data_inicio':'2026-10-02','dia_vencimento':'10'}),302,
       'Tentativa de contrato sobreposto validada')
check(amount('contratos_v14')==2,'Não permite dois contratos ativos sobrepostos no mesmo veículo')
status(post('/admin/contratos/criar',{'veiculo_id':'2','beneficiario_tipo':'FROTA','beneficiario_id':'1',
       'valor_mensal':'120,00','data_inicio':'2026-10-02','dia_vencimento':'10'}),302,
       'Tentativa de beneficiário incorreto validada')
check(amount('contratos_v14')==2,'Não permite pagar frota alheia ao veículo')

status(post('/admin/pagamentos/gerar',{'mes':'2026-10'}),302,'Gerar pagamentos mensais')
check(amount('pagamentos_v14')==2 and one("SELECT valor_centimos FROM pagamentos_v14 WHERE contrato_id=1")[0]==14590,
      'Gerou os dois pagamentos corretos')
status(post('/admin/pagamentos/gerar',{'mes':'2026-10'}),302,'Gerar mensalidades novamente')
check(amount('pagamentos_v14')==2,'Mensalidades são idempotentes e não duplicadas')
with m.app.app_context():
    db=m.get_db()
    check(generate_payments(db,'2026-09',m.now_iso())==0,'Não gera cobranças antes do início do contrato')
check(amount('pagamentos_v14')==2,'Mensalidades fora da vigência não criadas')
status(post('/admin/pagamentos/1/pagar',{'referencia':'TRF-OUT2026-123'}),302,'Confirmar pagamento')
check(one('SELECT estado,referencia FROM pagamentos_v14 WHERE id=1')==('PAGO','TRF-OUT2026-123'),
      'Pagamento e referência persistidos')
status(post('/admin/pagamentos/1/pagar',{'referencia':'DUPLICADO'}),302,'Repetição de confirmação rejeitada')
check(one('SELECT referencia FROM pagamentos_v14 WHERE id=1')[0]=='TRF-OUT2026-123',
      'Registo financeiro pago não é modificado por repetição')
status(client.get('/admin/pagamentos.csv?mes=2026-10'),200,'Exportar CSV de pagamentos')
csv=client.get('/admin/pagamentos.csv?mes=2026-10').data.decode('utf-8-sig')
check('145,90' in csv and 'TRF-OUT2026-123' in csv,'CSV inclui valores e referências de pagamento')
check(client.get('/admin/frotas/resumo.json?mes=2026-10').json['indicadores']['pago']==14590,
      'Indicadores financeiros do mês corretos')
pdf_14 = client.get('/admin/pagamentos.pdf?mes=2026-10')
check(pdf_14.status_code==200 and pdf_14.data.startswith(b'%PDF-'),'Relatório PDF de mensalidades')
contract_14 = client.get('/admin/contratos/1/documento.pdf')
check(contract_14.status_code==200 and contract_14.data.startswith(b'%PDF-'),'Minuta PDF administrativa de contrato')
status(client.get('/admin/inteligencia.pdf?dias=30'),200,'Exportação PDF da V1.3.1 preservada')
status(client.get('/admin/campanhas'),200,'Campanhas V1.3.1 preservadas')

advertiser=m.app.test_client()
with advertiser.session_transaction() as s:
    s['anunciante_id']=1
for url in ('/admin/frotas','/admin/pagamentos','/admin/pagamentos.csv', '/admin/frotas/resumo.json'):
    status(advertiser.get(url),302,'Anunciante sem acesso a dados de frotas/pagamentos')

# Migração é testada numa cópia sintética da base (para não tocar no banco operacional).
old=base/'origem_v131'; dst=base/'destino_v14'
(old/'instance').mkdir(parents=True); (old/'uploads').mkdir()
dst.mkdir()
(old/'app.py').write_text('# V1.3.1',encoding='utf-8')
(old/'.env').write_text('APP_NAME=RotaAds de teste\nADMIN_PASSWORD=segredo-teste\n',encoding='utf-8')
(old/'uploads'/'anuncio.txt').write_text('teste de mídia',encoding='utf-8')
with closing(sqlite3.connect(str(old/'instance'/'rotaads.sqlite3'))) as db:
    db.executescript('''CREATE TABLE campanhas(id INTEGER PRIMARY KEY);
    CREATE TABLE dispositivos(id INTEGER PRIMARY KEY);CREATE TABLE anunciantes(id INTEGER PRIMARY KEY);
    CREATE TABLE zonas(id INTEGER PRIMARY KEY);CREATE TABLE exibicoes(id INTEGER PRIMARY KEY);
    INSERT INTO campanhas(id) VALUES(777);''')
archive,copied,n=migrate(old,dst)
check(archive.is_file() and copied.is_file() and n==1 and (dst/'.env').is_file(),
      'Migração cria backup ZIP e copia mídia, .env e SQLite')
check(one('SELECT COUNT(*) FROM campanhas')==0,'Migração não alterou o banco de testes Flask original')
with closing(sqlite3.connect(str(dst/'instance'/'rotaads.sqlite3'))) as db:
    check(db.execute('SELECT id FROM campanhas').fetchone()[0]==777,'Registos de origem preservados na cópia')
try:
    migrate(old,dst)
except ValueError:
    print('  OK - Migrador impede sobrescrever instalação já existente')
else:
    raise AssertionError('Migrador não bloqueou sobreposição')

check(parse_money('1.250,50')==125050 and euros(125050)=='1.250,50 €','Conversão monetária em euros')
check(month_bounds('2026-02')[1].isoformat()=='2026-02-28','Fecho correto de competência mensal')
print('\nRESULTADO: rotas, regras, isolamento, pagamentos, relatórios e migração V1.4 aprovados.')
