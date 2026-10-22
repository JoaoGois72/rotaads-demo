"""Simula UMA última posição GPS no sistema LOCAL para ensaios.

Uso: py simular_gps_v1_2.py TOKEN 38.7223 -9.1393
Permite repetir a cada 30 s: --continuo (Ctrl+C para parar).
Não contém GPS real; envio utiliza o token secreto do ecrã.
"""
import json
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def main():
    if len(sys.argv) < 4 or (len(sys.argv) > 5 or (len(sys.argv) == 5 and sys.argv[4] != '--continuo')):
        print('USO: py simular_gps_v1_2.py TOKEN LATITUDE LONGITUDE [--continuo]')
        return 2
    token = sys.argv[1]
    try:
        lat, lon = float(sys.argv[2]), float(sys.argv[3])
    except ValueError:
        print('ERRO: Latitude e longitude inválidas. Utilize ponto decimal.')
        return 1
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not token:
        print('ERRO: token ou coordenadas inválidas.')
        return 1
    base = 'http://127.0.0.1:5000/api/ecra/' + token
    print(f'A simular GPS em {lat:.5f}, {lon:.5f} no servidor LOCAL.')
    print('Este teste não mede a localização real do carro.')
    try:
        while True:
            body = json.dumps({'consentimento_gps':True,'lat':lat,'lon':lon,'precisao_m':15}).encode()
            r = Request(base+'/sinal', data=body, headers={'Content-Type':'application/json'}, method='POST')
            with urlopen(r, timeout=10) as response:
                print('Sinal GPS:', response.status)
            with urlopen(base+'/playlist',timeout=10) as response:
                data = json.load(response)
                print('Campanhas disponíveis:', ', '.join(x['nome'] for x in data['campanhas']) or '(nenhuma)')
            if '--continuo' not in sys.argv:
                break
            time.sleep(30)
    except KeyboardInterrupt:
        print('\nSimulação terminada.')
    except (URLError, OSError) as e:
        print('ERRO: verifique se o servidor está em execução, e se o token é válido:', e)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
