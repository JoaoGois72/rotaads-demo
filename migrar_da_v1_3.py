"""Migração não destrutiva da RotaAds V1.3 validada para a V1.3.1.

Executar: py migrar_da_v1_3.py "C:\\Users\\...\\Programa rotaads"
Copiar APENAS para pasta nova e vazia; a pasta anterior não é modificada.
"""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile


def main():
    new = Path(__file__).resolve().parent
    if len(sys.argv) != 2:
        print(r'USO: py migrar_da_v1_3.py "C:\rotaads_v1_3"')
        return 2
    old = Path(sys.argv[1]).expanduser().resolve()
    if old == new or not (old / 'app.py').is_file():
        print('ERRO: indique uma pasta V1.3 diferente do destino V1.3.1.')
        return 1
    env = old / '.env'
    if env.is_file():
        config = {line.split('=', 1)[0].strip() for line in env.read_text(encoding='utf-8-sig').splitlines()
                  if '=' in line and not line.strip().startswith('#')}
        if 'DATABASE_PATH' in config or 'UPLOAD_FOLDER' in config:
            print('ERRO: configuração DATABASE_PATH/UPLOAD_FOLDER personalizada. Não é seguro copiar automaticamente.')
            return 1
    source_file = old / 'instance' / 'rotaads.sqlite3'
    target_file = new / 'instance' / 'rotaads.sqlite3'
    if not source_file.is_file():
        print('ERRO: banco V1.3 não encontrado em', source_file)
        return 1
    if target_file.exists() or (new / '.env').exists():
        print('SEGURANÇA: banco ou .env V1.3.1 já existe e NÃO será sobrescrito.')
        return 1
    backup_dir = new / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    snapshot = backup_dir / f'v1_3_validada_{stamp}.sqlite3'
    archive = backup_dir / f'v1_3_validada_{stamp}.zip'
    target_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = target_file.parent / 'rotaads.migracao.tmp'
    if temp_file.exists():
        print('ERRO: ficheiro temporário de migração anterior. Confirme antes de continuar.')
        return 1
    try:
        with closing(sqlite3.connect(str(source_file), timeout=20)) as source:
            if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Banco de origem não íntegro.')
            tables = {r[0] for r in source.execute('SELECT name FROM sqlite_master WHERE type="table"')}
            if not {'campanhas', 'dispositivos', 'anunciantes', 'zonas', 'exibicoes'}.issubset(tables):
                raise RuntimeError('O banco não parece pertencer à RotaAds V1.3.')
            campaigns = {r[1] for r in source.execute('PRAGMA table_info(campanhas)')}
            devices = {r[1] for r in source.execute('PRAGMA table_info(dispositivos)')}
            if 'peso_v13' not in campaigns or 'otimizacao_ativa' not in devices:
                raise RuntimeError('A base informada não contém os campos V1.3 esperados.')
            with closing(sqlite3.connect(str(snapshot))) as dst:
                source.backup(dst)
        shutil.copy2(snapshot, temp_file)
        with closing(sqlite3.connect(str(temp_file))) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('O banco copiado não passou na validação.')
        source_uploads = old / 'uploads'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot, 'instance/rotaads.sqlite3')
            if env.is_file():
                z.write(env, '.env')
            if source_uploads.is_dir():
                for f in source_uploads.rglob('*'):
                    if f.is_file() and not f.is_symlink():
                        z.write(f, (Path('uploads') / f.relative_to(source_uploads)).as_posix())
        copied = 0
        if source_uploads.is_dir():
            for f in source_uploads.rglob('*'):
                if f.is_file() and not f.is_symlink():
                    dest = new / 'uploads' / f.relative_to(source_uploads)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        shutil.copy2(f, dest)
                        copied += 1
        if env.is_file():
            shutil.copy2(env, new / '.env')
        temp_file.replace(target_file)
        print('OK: banco copiado de forma consistente, sem alterar a origem V1.3.')
        print('OK:', copied, 'ficheiro(s) de publicidade copiados.')
        print('BACKUP:', archive)
        print('DESTINO:', target_file)
        print('NÃO publique o backup: contém dados e possivelmente credenciais.')
        return 0
    except Exception as e:
        print('ERRO: migração cancelada:', str(e))
        try:
            if temp_file.exists(): temp_file.unlink()
        except OSError:
            print('ATENÇÃO: ficheiro temporário precisa ser verificado manualmente:', temp_file)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
