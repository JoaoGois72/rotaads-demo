"""Migração não destrutiva da RotaAds V1.2 para V1.3.

Pare o processo V1.2 primeiro. Não apaga nem altera a pasta de origem.
Uso: py migrar_da_v1_2.py "C:\\rotaads_v1_2"
"""
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path


def main():
    new = Path(__file__).resolve().parent
    if len(sys.argv) != 2:
        print(r'USO: py migrar_da_v1_2.py "C:\rotaads_v1_2"')
        return 2
    old = Path(sys.argv[1]).expanduser().resolve()
    if old == new or not (old / 'app.py').is_file():
        print('ERRO: indique a pasta da V1.2, diferente da pasta da V1.3.')
        return 1
    env = old / '.env'
    if env.is_file():
        config = [line.split('=', 1)[0].strip() for line in env.read_text(encoding='utf-8-sig').splitlines()
                  if '=' in line and not line.strip().startswith('#')]
        if 'DATABASE_PATH' in config or 'UPLOAD_FOLDER' in config:
            print('ERRO: DATABASE_PATH ou UPLOAD_FOLDER personalizados no .env da V1.2.')
            print('Para garantir o backup correto, faça a migração desses dados manualmente.')
            return 1
    original_db = old / 'instance' / 'rotaads.sqlite3'
    target_db = new / 'instance' / 'rotaads.sqlite3'
    if not original_db.is_file():
        print('ERRO: base V1.2 não encontrada em', original_db)
        return 1
    if target_db.exists():
        print('SEGURANÇA: o banco V1.3 já existe e NÃO será sobrescrito.')
        print('Para evitar perda de dados, não continue até confirmar a situação.')
        return 1
    if (new / '.env').exists():
        print('SEGURANÇA: .env da V1.3 já existe e NÃO será sobrescrito.')
        print('Confirme que não aponta para uma base ou pastas da V1.2 antes de continuar.')
        return 1
    backups = new / 'backups'
    backups.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    snapshot = backups / f'v1_2_original_{timestamp}.sqlite3'
    archive = backups / f'v1_2_original_{timestamp}.zip'
    target_db.parent.mkdir(parents=True, exist_ok=True)
    temp_db = target_db.with_suffix('.sqlite3.tmp')
    if temp_db.exists():
        print('ERRO: existe uma cópia temporária pendente de verificação:', temp_db)
        return 1

    # Backup SQLite transacional consistente, mesmo que o SQLite utilize WAL.
    try:
        with closing(sqlite3.connect(str(original_db), timeout=15)) as source:
            # Verifica integridade e origem ANTES de escrever no destino.
            if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('A base original não passou na verificação de integridade.')
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'campanhas', 'dispositivos', 'anunciantes', 'zonas', 'campanhas_zonas'}.issubset(tables):
                raise RuntimeError('O banco informado não parece ser a RotaAds V1.2.')
            device_columns = {r[1] for r in source.execute('PRAGMA table_info(dispositivos)')}
            if 'ultima_localizacao_em' not in device_columns:
                raise RuntimeError('A base não tem GPS da V1.2.')
            campaign_columns = {r[1] for r in source.execute('PRAGMA table_info(campanhas)')}
            if 'peso_v13' in campaign_columns:
                raise RuntimeError('A base já contém estrutura V1.3; evite migrar a mesma base novamente.')
            with closing(sqlite3.connect(str(snapshot))) as target:
                source.backup(target)
            shutil.copy2(snapshot, temp_db)
        with closing(sqlite3.connect(str(temp_db))) as verify:
            if verify.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Cópia do banco não íntegra.')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot, 'instance/rotaads.sqlite3')
            if env.is_file():
                zf.write(env, '.env')
            uploads = old / 'uploads'
            if uploads.is_dir():
                for src in uploads.iterdir():
                    if src.is_file() and not src.is_symlink():
                        zf.write(src, f'uploads/{src.name}')
        target_uploads = new / 'uploads'
        target_uploads.mkdir(exist_ok=True)
        copied = 0
        if uploads.is_dir():
            for src in uploads.iterdir():
                if src.is_file() and not src.is_symlink():
                    dst = target_uploads / src.name
                    if not dst.exists():
                        shutil.copy2(src, dst)
                        copied += 1
        if env.is_file():
            shutil.copy2(env, new / '.env')
        temp_db.replace(target_db)
        print('OK: cópia consistente do SQLite V1.2 (sem alterar a original).')
        print('OK:', copied, 'ficheiros publicitários copiados.')
        print('BACKUP:', archive)
        print('Banco destino:', target_db)
        print('V1.2 mantém-se intacta. Instale as dependências e inicie a V1.3.')
        print('ATENÇÃO: o ZIP de backup contém dados e credenciais; guarde-o num local seguro.')
        return 0
    except Exception as exc:
        print('ERRO: migração cancelada:', exc)
        if temp_db.exists():
            try:
                temp_db.unlink()
            except OSError:
                print('AVISO: remova manualmente o ficheiro temporário:', temp_db)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
