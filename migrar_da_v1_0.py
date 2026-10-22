"""Copia dados locais da V1.0 para a V1.1 sem sobrescrever informação.
USO: python migrar_da_v1_0.py "C:\\rotaads_v1_0"
Execute com a V1.0 PARADA.
"""
import shutil
import sqlite3
import sys
from pathlib import Path

new=Path(__file__).resolve().parent
if len(sys.argv)!=2:
    print('USO: python migrar_da_v1_0.py "C:\\rotaads_v1_0"')
    raise SystemExit(2)
old=Path(sys.argv[1]).expanduser().resolve()
if not (old/'app.py').exists():
    print('ERRO: não existe app.py na pasta V1.0 indicada:',old)
    raise SystemExit(1)
if old==new:
    print('ERRO: indique a pasta ANTIGA (V1.0), não a atual.')
    raise SystemExit(1)
print('Origem:',old,'\nDestino:',new)
# Impedir que um .env personalizado aponte a V1.1 para o banco vivo da V1.0.
old_env=old/'.env'
if old_env.is_file():
    active_config=[line.split('=',1)[0].strip() for line in old_env.read_text(encoding='utf-8-sig').splitlines()
                   if line.strip() and not line.lstrip().startswith('#') and '=' in line]
    if 'DATABASE_PATH' in active_config or 'UPLOAD_FOLDER' in active_config:
        print('ERRO: o .env antigo usa DATABASE_PATH ou UPLOAD_FOLDER personalizados.')
        print('Faça backup desses locais e ajuste manualmente as cópias e o .env para a V1.1;')
        print('o migrador automático foi interrompido para não usar o banco antigo por engano.')
        raise SystemExit(1)
if (old/'.env').exists():
    if not (new/'.env').exists():
        shutil.copy2(old/'.env',new/'.env')
        print('OK: Configuração .env copiada.')
    else:
        print('IGNORADO: .env já existe na V1.1 (não será sobrescrito).')
else:
    print('AVISO: .env não encontrado na V1.0; configurar manualmente a V1.1.')
old_db=old/'instance'/'rotaads.sqlite3'
new_db=new/'instance'/'rotaads.sqlite3'
if old_db.is_file():
    new_db.parent.mkdir(parents=True,exist_ok=True)
    if not new_db.exists():
        with sqlite3.connect(str(old_db)) as source,sqlite3.connect(str(new_db)) as target:
            source.backup(target)
        print('OK: Banco SQLite copiado com backup consistente.')
    else:
        print('IGNORADO: Base de dados V1.1 já existe; não será sobrescrita.')
else:
    print('AVISO: Banco padrão não encontrado. Se DATABASE_PATH foi personalizado, copie-o manualmente com segurança.')
old_upload=old/'uploads'
new_upload=new/'uploads'
if old_upload.exists():
    new_upload.mkdir(parents=True,exist_ok=True)
    copied=0
    for source in old_upload.iterdir():
        if source.is_file() and not (new_upload/source.name).exists():
            shutil.copy2(source,new_upload/source.name)
            copied+=1
    print('OK:',copied,'ficheiros publicitários copiados (existentes preservados).')
print('\nConcluído. Execute python testes_v1_1.py e depois python app.py.')
print('A migração automática da coluna anunciante_id é feita ao iniciar a V1.1.')
