"""Testes de integração Flask V1.3.1 em banco isolado (Windows/Linux).

O processo pai arranca um subprocesso para garantir fecho das conexões antes da
remoção de arquivos temporários no Windows, prevenindo WinError 32.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix='rotaads_v131_flask_') as td:
        env = os.environ.copy()
        env.update(
            DATABASE_PATH=str(Path(td) / 'instance' / 'rotaads.sqlite3'),
            UPLOAD_FOLDER=str(Path(td) / 'uploads'),
            SECRET_KEY='test-secret-key-v131',
            ADMIN_USERNAME='admin',
            ADMIN_PASSWORD='test-password-v131',
            SITE_URL='http://127.0.0.1:5000',
            ROTAADS_TEST_MODE='v131'
        )
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('_testes_v1_3_1_flask_worker.py'))],
                                env=env, text=True, capture_output=True, timeout=90)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            raise RuntimeError('Integração Flask V1.3.1 falhou.')
    print('\nRESULTADO: integração Flask V1.3.1 aprovada.')


if __name__ == '__main__':
    try: main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
