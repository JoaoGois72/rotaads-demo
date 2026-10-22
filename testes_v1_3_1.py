"""Testes de dashboard V1.3.1, em base temporária sem afetar dados reais.

Ao contrário dos anteriores, também testa filtro de anunciante, acesso e exportação.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from analytics_v131 import csv_safe, dashboard_data, period_days


def check(cond, label):
    if not cond:
        raise AssertionError(label)
    print('  OK - ' + label)


def create_fixture(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path))) as db:
        db.executescript('''
        CREATE TABLE campanhas(id INTEGER PRIMARY KEY,nome TEXT,anunciante TEXT,anunciante_id INTEGER,
          ativo INTEGER,data_inicio TEXT,data_fim TEXT,carros_contratados INTEGER,cupao_ativo INTEGER,peso_v13 INTEGER);
        CREATE TABLE dispositivos(id INTEGER PRIMARY KEY,ativo INTEGER,ultimo_sinal TEXT);
        CREATE TABLE atribuicoes(campanha_id INTEGER,dispositivo_id INTEGER);
        CREATE TABLE exibicoes(id INTEGER PRIMARY KEY,campanha_id INTEGER,dispositivo_id INTEGER,criado_em TEXT,zona_id INTEGER);
        CREATE TABLE leituras_qr(id INTEGER PRIMARY KEY,campanha_id INTEGER,criado_em TEXT);
        CREATE TABLE resgates_cupao(id INTEGER PRIMARY KEY,campanha_id INTEGER,criado_em TEXT);
        CREATE TABLE zonas(id INTEGER PRIMARY KEY,nome TEXT);
        INSERT INTO campanhas VALUES (1,'Cliente A','Empresa A',11,1,NULL,NULL,2,1,5);
        INSERT INTO campanhas VALUES (2,'Cliente B','Empresa B',22,1,NULL,NULL,1,1,1);
        INSERT INTO dispositivos(id,ativo,ultimo_sinal) VALUES(7,1,'2026-10-21T12:00:00+00:00');
        INSERT INTO atribuicoes VALUES(1,7);
        INSERT INTO atribuicoes VALUES(2,7);
        INSERT INTO zonas VALUES(3,'Lisboa Centro');
        INSERT INTO exibicoes VALUES(1,1,7,'2026-10-21T11:00:00+00:00',3);
        INSERT INTO exibicoes VALUES(2,1,7,'2026-10-21T11:10:00+00:00',3);
        INSERT INTO exibicoes VALUES(3,2,7,'2026-10-21T11:15:00+00:00',3);
        INSERT INTO leituras_qr VALUES(1,1,'2026-10-21T11:20:00+00:00');
        INSERT INTO resgates_cupao VALUES(1,1,'2026-10-21T11:25:00+00:00');
        INSERT INTO exibicoes VALUES(4,2,7,'2026-08-02T11:00:00+00:00',3);
        ''')
        db.commit()


def analytics_tests(root):
    dbpath = root / 'fixture.sqlite3'
    create_fixture(dbpath)
    current = datetime(2026,10,21,12,0,tzinfo=timezone.utc)
    with closing(sqlite3.connect(dbpath)) as db:
        db.row_factory = sqlite3.Row
        all_data = dashboard_data(db, 30, current=current)
        a = dashboard_data(db, 30, advertiser_id=11, current=current)
        b = dashboard_data(db, 30, advertiser_id=22, current=current)
        long = dashboard_data(db, 90, advertiser_id=22, current=current)
        check(all_data['resumo']['reproducoes']==3 and all_data['resumo']['leituras']==1 and
              all_data['resumo']['resgates']==1, 'Métricas consolidadas e período de 30 dias')
        check(a['resumo']['reproducoes']==2 and b['resumo']['reproducoes']==1 and
              len(a['campanhas'])==1 and a['campanhas'][0]['nome']=='Cliente A' and
              len(b['campanhas'])==1, 'Isolamento das campanhas por anunciante')
        check(b['resumo']['leituras']==0 and b['resumo']['resgates']==0 and
              all(z['nome'] != 'Cliente A' for z in b['zonas']), 'Separação de indicadores QR/resgates')
        check(long['resumo']['reproducoes']==2 and len(long['diario'])==90, 'Filtros 7/30/90 dias')
        check(all_data['resumo']['ecra_online']==1 and a['resumo']['ecra_online']==1,
              'Ecrãs online com deduplicação por anunciante')
        check(sum(x['reproducoes'] for x in all_data['horario'])==3 and all_data['zonas'][0]['reproducoes']==3,
              'Horários em Portugal e zonas agregadas')
        check(all_data['resumo']['leituras_por_100_reproducoes']==round(100/3,1),
              'Indicador QR com denominador correto')
    for x in ('4', '100', 'abc', '', '../'):
        try: period_days(x)
        except ValueError: pass
        else: raise AssertionError('Deveria rejeitar período ' + x)
    check(csv_safe('=SUM(A1:A4)').startswith("'=") and csv_safe('Empresa Boa') == 'Empresa Boa',
          'Exportação CSV protegida contra fórmulas de células')


def migration_tests(root):
    old = root / 'old'
    new = root / 'new'
    (old / 'instance').mkdir(parents=True)
    (old / 'uploads').mkdir()
    new.mkdir()
    (old / 'app.py').write_text('# V1.3\n', encoding='utf-8')
    (old / '.env').write_text('APP_NAME=Teste V1.3\nADMIN_PASSWORD=senha-de-teste\n',encoding='utf-8')
    (old / 'uploads' / 'file.png').write_bytes(b'jpeg-test-data')
    source = old / 'instance' / 'rotaads.sqlite3'
    create_fixture(source)
    with closing(sqlite3.connect(source)) as db:
        db.execute('ALTER TABLE campanhas ADD COLUMN horario_inicio TEXT')
        db.execute('ALTER TABLE dispositivos ADD COLUMN otimizacao_ativa INTEGER DEFAULT 0')
        db.execute('CREATE TABLE anunciantes(id INTEGER PRIMARY KEY)')
        db.commit()
    shutil.copy2(ROOT / 'migrar_da_v1_3.py', new / 'migrar_da_v1_3.py')
    run = [sys.executable,str(new / 'migrar_da_v1_3.py'),str(old)]
    process = subprocess.run(run, capture_output=True, text=True, timeout=30)
    check(process.returncode == 0, 'Cópia transacional da V1.3 e backup imutável')
    check((new / 'uploads' / 'file.png').is_file() and
          list((new / 'backups').glob('v1_3_validada_*.zip')) and (new / '.env').is_file(),
          'Criativos, configurações e ZIP de retorno preservados')
    second = subprocess.run(run, capture_output=True, text=True, timeout=30)
    check(second.returncode != 0 and 'NÃO será sobrescrito' in second.stdout,
          'Migração recusa sobrescrever destino já instalado')
    with closing(sqlite3.connect(source)) as source_db:
        check(source_db.execute('SELECT COUNT(*) FROM exibicoes').fetchone()[0]==4,
              'Banco operacional de origem não modificado')


def print_summary():
    print('Execute também testes_v1_3_1_flask.py para validar as rotas, templates e sessões.')


def main():
    with tempfile.TemporaryDirectory(prefix='rotaads_v131_') as td:
        root = Path(td)
        analytics_tests(root)
        migration_tests(root)
    print('\nRESULTADO: testes de métricas e migração da V1.3.1 aprovados.')
    print_summary()


if __name__=='__main__':
    try: main()
    except Exception as error:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
