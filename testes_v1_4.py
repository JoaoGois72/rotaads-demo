"""V1.4 — integração em base temporária isolada; NUNCA modifica a base operacional.

Execute: python testes_v1_4.py
O worker termina antes de eliminar o SQLite, evitando WinError 32 no Windows.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='rotaads_v14_teste_') as td:
        env = os.environ.copy()
        env.update(DATABASE_PATH=str(Path(td)/'instance'/'rotaads.sqlite3'),
                   UPLOAD_FOLDER=str(Path(td)/'uploads'),
                   SECRET_KEY='rotaads-test-v14-isolated',
                   ADMIN_USERNAME='admin',ADMIN_PASSWORD='senha-v14-de-teste',
                   SITE_URL='http://127.0.0.1:5000',
                   ROTAADS_V14_TEST='1')
        run = subprocess.run([sys.executable,str(root/'_testes_v1_4_worker.py'),td],
                             env=env,capture_output=True,text=True,timeout=120)
        print(run.stdout,end='')
        if run.returncode:
            print(run.stderr,file=sys.stderr)
            raise RuntimeError('Teste V1.4 falhou. Verifique o erro acima; dados reais não foram alterados.')
    print('\nRESULTADO: V1.4 testada em banco SQLite temporário, sem tocar nos dados reais.')
    print('Falta validar o funcionamento no navegador e com parceiros reais.')


if __name__ == '__main__':
    try: main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise SystemExit(1)
