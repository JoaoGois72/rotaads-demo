"""Execução isolada do teste de rotas; utilizada pelo script público."""
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
from contextlib import closing
import app as m


def check(result, expected, label):
    if result.status_code != expected:
        raise AssertionError(f'{label}: HTTP {result.status_code} esperado {expected}, corpo: {result.get_data(as_text=True)[:450]}')
    print('  OK -', label)


assert os.getenv('ROTAADS_TEST_MODE') == 'v131' and 'rotaads_v131_flask_' in os.environ['DATABASE_PATH']
dbpath = Path(os.environ['DATABASE_PATH'])
with closing(sqlite3.connect(dbpath)) as db:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    db.execute('INSERT INTO anunciantes(id,nome,empresa,email,senha_hash,ativo,criado_em) VALUES(?,?,?,?,?,?,?)',
               (11,'Pessoa A','Empresa A','a@teste.pt','hash',1,now))
    db.execute('INSERT INTO anunciantes(id,nome,empresa,email,senha_hash,ativo,criado_em) VALUES(?,?,?,?,?,?,?)',
               (22,'Pessoa B','Empresa B','b@teste.pt','hash',1,now))
    db.execute('''INSERT INTO campanhas(id,nome,anunciante,anunciante_id,carros_contratados,criado_em)
                  VALUES(1001,'Campanha confidencial A','Empresa A',11,1,?)''', (now,))
    db.execute('''INSERT INTO campanhas(id,nome,anunciante,anunciante_id,carros_contratados,criado_em)
                  VALUES(1002,'Campanha confidencial B','Empresa B',22,1,?)''', (now,))
    db.execute('''INSERT INTO dispositivos(id,nome,parceiro,token,criado_em,ultimo_sinal)
                  VALUES(101,'TESTE ECRÃ','Teste','teste-seguro-um',?,?)''', (now,now))
    db.execute('INSERT INTO atribuicoes(dispositivo_id,campanha_id) VALUES(101,1001)')
    db.execute('INSERT INTO atribuicoes(dispositivo_id,campanha_id) VALUES(101,1002)')
    db.execute('INSERT INTO exibicoes(dispositivo_id,campanha_id,criado_em) VALUES(101,1001,?)', (now,))
    db.execute('INSERT INTO exibicoes(dispositivo_id,campanha_id,criado_em) VALUES(101,1002,?)', (now,))
    db.execute('INSERT INTO leituras_qr(campanha_id,criado_em) VALUES(1001,?)', (now,))
    db.execute('INSERT INTO resgates_cupao(campanha_id,criado_em) VALUES(1001,?)', (now,))
    db.commit()

client = m.app.test_client()
check(client.get('/admin/inteligencia'),302,'Admin exige autenticação')
check(client.get('/anunciante/inteligencia'),302,'Anunciante exige autenticação')
check(client.get('/anunciante/inteligencia.pdf'),302,'PDF do anunciante exige autenticação')
with client.session_transaction() as s: s['admin_logged'] = True
response = client.get('/admin/inteligencia?dias=30')
check(response,200,'Admin consegue abrir dashboard e gráficos')
assert b'Campanha confidencial A' in response.data and b'Campanha confidencial B' in response.data
check(client.get('/admin/inteligencia.csv?dias=7'),200,'Exportação CSV consolidada')
check(client.get('/admin/inteligencia/imprimir?dias=30'),200,'Relatório HTML imprimível')
pdf = client.get('/admin/inteligencia.pdf?dias=30')
check(pdf,200,'Download PDF do administrador')
assert pdf.mimetype == 'application/pdf' and pdf.data.startswith(b'%PDF-') and b'%%EOF' in pdf.data[-64:]
assert 'attachment;' in pdf.headers.get('Content-Disposition', '')
check(client.get('/admin/inteligencia.pdf?dias=100'),400,'PDF rejeita período inválido')
check(client.get('/admin/inteligencia?dias=999'),400,'Período inválido bloqueado')

client_a = m.app.test_client()
with client_a.session_transaction() as s: s['anunciante_id'] = 11
response = client_a.get('/anunciante/inteligencia?dias=30')
check(response,200,'Cliente A consulta dashboard próprio')
assert b'Campanha confidencial A' in response.data and b'Campanha confidencial B' not in response.data
response = client_a.get('/anunciante/inteligencia.csv?dias=30')
check(response,200,'Exportação CSV do cliente A')
assert b'Campanha confidencial A' in response.data and b'Campanha confidencial B' not in response.data
response = client_a.get('/anunciante/inteligencia/imprimir?dias=30')
check(response,200,'Relatório imprimível do cliente A')
pdf_a = client_a.get('/anunciante/inteligencia.pdf?dias=30')
check(pdf_a,200,'PDF exclusivo do anunciante A')
assert pdf_a.mimetype == 'application/pdf' and pdf_a.data.startswith(b'%PDF-')
assert 'attachment;' in pdf_a.headers.get('Content-Disposition', '')
assert b'Campanha confidencial B' not in response.data
client_b = m.app.test_client()
with client_b.session_transaction() as s: s['anunciante_id']=22
response = client_b.get('/anunciante/inteligencia')
check(response,200,'Cliente B consulta dashboard independente')
pdf_b = client_b.get('/anunciante/inteligencia.pdf?dias=30')
check(pdf_b,200,'PDF exclusivo do anunciante B')
assert pdf_b.data.startswith(b'%PDF-') and pdf_b.data != pdf_a.data
assert b'Campanha confidencial B' in response.data and b'Campanha confidencial A' not in response.data
with closing(sqlite3.connect(dbpath)) as db:
    db.execute('UPDATE anunciantes SET ativo=0 WHERE id=22')
    db.commit()
check(client_b.get('/anunciante/inteligencia'),302,'Cliente desativado perde acesso')
print('  OK - Separação entre empresas A e B sem exposição cruzada de dados')
