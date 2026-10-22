"""Copia base SQLite, media e configurações da V1.3.1 validada, sem modificá-la.

USO: py migrar_da_v1_3_1.py "C:\\Users\\...\\Programa rotaads"
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import shutil
import sqlite3
import sys
import zipfile


def migrate(old, new):
    old = Path(old).expanduser().resolve()
    new = Path(new).resolve()
    if old == new or not (old / 'app.py').is_file():
        raise ValueError('Indique a pasta correta da V1.3.1; a origem e o destino devem ser diferentes.')
    env = old / '.env'
    if env.is_file():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if line.strip().startswith('#') or '=' not in line:
                continue
            name = line.partition('=')[0].strip()
            if name in {'DATABASE_PATH', 'UPLOAD_FOLDER'}:
                raise ValueError('Configuração de caminhos personalizada. Não é seguro migrar automaticamente.')
    source = old / 'instance' / 'rotaads.sqlite3'
    target = new / 'instance' / 'rotaads.sqlite3'
    if not source.is_file():
        raise ValueError('Banco de dados da V1.3.1 não localizado: ' + str(source))
    if target.exists() or (new / '.env').exists():
        raise ValueError('O destino já contém .env ou SQLite; migração cancelada para evitar sobreposição.')
    if any(f for f in (new/'uploads').rglob('*') if f.is_file() and f.name != '.gitkeep'):
        raise ValueError('Já existem ficheiros de anúncios no destino. Migração cancelada.')

    target.parent.mkdir(parents=True, exist_ok=True)
    backups = new / 'backups'
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup_database = backups / f'v1_3_1_VALIDADA_{stamp}.sqlite3'
    archive = backups / f'v1_3_1_VALIDADA_{stamp}.zip'
    temp = target.parent / 'rotaads_v14_migracao.tmp'
    if temp.exists():
        raise ValueError('Já existe ficheiro temporário de migração; verifique antes de continuar.')
    try:
        with closing(sqlite3.connect(str(source), timeout=30)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('O banco original não passou no teste de integridade.')
            tables = {r[0] for r in db.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            if not {'campanhas','dispositivos','anunciantes','zonas','exibicoes'}.issubset(tables):
                raise RuntimeError('Banco inválido: não possui as tabelas essenciais da RotaAds.')
            with closing(sqlite3.connect(str(backup_database))) as destination:
                db.backup(destination)
        with closing(sqlite3.connect(str(backup_database))) as check:
            if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('A cópia SQLite falhou a verificação de integridade.')
        shutil.copy2(backup_database, temp)
        uploads = old / 'uploads'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.write(backup_database, 'instance/rotaads.sqlite3')
            if env.is_file():
                z.write(env, '.env')
            if uploads.is_dir():
                for f in uploads.rglob('*'):
                    if f.is_file() and not f.is_symlink():
                        z.write(f, (Path('uploads')/f.relative_to(uploads)).as_posix())
        n = 0
        if uploads.is_dir():
            for f in uploads.rglob('*'):
                if f.is_file() and not f.is_symlink():
                    dest = new/'uploads'/f.relative_to(uploads)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
                    n += 1
        if env.is_file():
            shutil.copy2(env, new / '.env')
        temp.replace(target)
        return archive, target, n
    except Exception:
        if temp.exists():
            temp.unlink()
        raise


def main():
    if len(sys.argv) != 2:
        print('USO: py migrar_da_v1_3_1.py "C:\\Users\\...\\Programa rotaads"')
        return 2
    try:
        archive, dest, count = migrate(sys.argv[1], Path(__file__).resolve().parent)
        print('OK: V1.3.1 original preservada; base SQLite migrada de forma consistente.')
        print('OK:', count, 'ficheiro(s) de anúncios copiados.')
        print('BACKUP COMPLETO:', archive)
        print('BASE COPIADA:', dest)
        print('AVISO: o backup contém dados e credenciais. Não o publique.')
        return 0
    except Exception as e:
        print('FALHA / NENHUM DADO DA ORIGEM ALTERADO:', e)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
