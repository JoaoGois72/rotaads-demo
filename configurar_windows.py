"""Configuração inicial de testes locais no Windows, sem dependências externas."""
from pathlib import Path
from secrets import token_urlsafe

root = Path(__file__).resolve().parent
env = root / '.env'
if env.exists():
    print('\nConfiguração .env existente mantida sem alterações.')
    print('Se esqueceu a palavra-passe, abra .env e altere ADMIN_PASSWORD.')
else:
    password = token_urlsafe(18)
    lines = [
        'APP_NAME=RotaAds',
        'SECRET_KEY=' + token_urlsafe(48),
        'ADMIN_USERNAME=admin',
        'ADMIN_PASSWORD=' + password,
        'SITE_URL=http://127.0.0.1:5000',
        'APP_HOST=127.0.0.1',
        'PORT=5000',
    ]
    env.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\nPrimeira configuração gerada com sucesso.')
    print('UTILIZADOR: admin')
    print('PALAVRA-PASSE: ' + password)
    print('Guarde estes dados. Pode alterar ADMIN_PASSWORD no ficheiro .env.')
    print('Para maior segurança, não envie o ficheiro .env a outras pessoas.')
