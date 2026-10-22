# Publicação da RotaAds V1.4 no Render — demonstração privada

## Objetivo

O seu sobrinho, em Portugal, recebe um **endereço HTTPS do Render** e pode abrir o site e testar os módulos. A aplicação do seu computador não é alterada. A demonstração contém apenas dados inventados.

## 1. Criar o repositório no GitHub

1. Entre em [github.com](https://github.com) e crie um **repositório privado** chamado `rotaads-demo` (não utilize o repositório da versão operacional).
2. Extraia o ZIP da demonstração no Windows. Os arquivos `app.py`, `render.yaml`, `demo_data.py`, `requirements.txt` e as pastas `templates` e `static` devem ficar no mesmo nível.
3. Use o **GitHub Desktop**: `File > Add local repository` (se necessário, criar repositório naquela pasta), `Commit to main` e `Publish repository` mantendo o repositório **privado**.
4. Como alternativa, utilize Git instalado no PowerShell dentro da pasta extraída:

   ```powershell
   git init
   git add .
   git commit -m "RotaAds V1.4 - demonstracao no Render"
   git branch -M main
   git remote add origin https://github.com/SEU_USUARIO/rotaads-demo.git
   git push -u origin main
   ```

   Substitua `SEU_USUARIO` pelo seu nome de utilizador GitHub. Se o Git solicitar, configure o nome/email e autentique-se pelo método aprovado pelo GitHub.

**Não inclua** ficheiros `.env`, pastas `instance`, bases `.sqlite3`, senhas, dados de motoristas reais ou tokens de tablets.

## 2. Criar o serviço no Render

1. Abra [dashboard.render.com](https://dashboard.render.com).
2. Clique em **New > Blueprint** e ligue a conta GitHub, autorizando acesso ao repositório privado `rotaads-demo`.
3. Selecione o repositório e o arquivo `render.yaml` incluído neste pacote.
4. O Render deve criar um serviço Web **Free**, runtime Python, com Gunicorn.
5. Preencha as três variáveis seguras solicitadas:

   | Variável | O que colocar |
   | --- | --- |
   | `DEMO_ACCESS_PASSWORD` | Uma senha forte para o visitante entrar no site |
   | `ADMIN_PASSWORD` | Uma senha forte diferente, para a administração |
   | `DEMO_ADVERTISER_PASSWORD` | Outra senha, para o portal fictício do anunciante |

   `SECRET_KEY` é gerada automaticamente pelo Render. Mantenha as quatro credenciais fora do GitHub e dos prints.

6. Conclua a criação e espere o estado **Live**. Copie o URL HTTPS efetivamente fornecido, como `https://rotaads-demonstracao-xxxx.onrender.com` (apenas exemplo).

### Caso não veja a opção Blueprint

Crie um **Web Service** apontando para o mesmo repositório e configure:

- Language/Runtime: `Python 3`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120 app:app`
- Instance Type: `Free`
- Health Check Path: `/healthz`
- Environment: `DEMO_MODE=1`, `ADMIN_USERNAME=admin`, `APP_NAME=RotaAds - DEMONSTRACAO`, `SECRET_KEY` gerada, e as três senhas acima.

## 3. Entrar e partilhar com o seu sobrinho

1. Abra o URL HTTPS do Render. O navegador pedirá **utilizador `visitante`** e a senha `DEMO_ACCESS_PASSWORD`.
2. Para entrar como **administrador**, aceda a `/admin/entrar` e utilize `admin` + `ADMIN_PASSWORD`.
3. Para entrar como **anunciante de teste**, aceda a `/anunciante/entrar`, e utilize `anunciante.demo@exemplo.pt` + `DEMO_ADVERTISER_PASSWORD`.
4. Envie ao sobrinho o URL e apenas as senhas que ele precisa, por um canal privado. Não partilhe a conta de administrador com terceiros não autorizados.

## 4. Funcionalidades para avaliar

- Site institucional e quatro formulários (anunciante, agência, frota e motorista)
- Gestão de campanhas e ecrãs, player com anúncios fictícios
- Zonas GPS e mapa administrativo (sem simular posição real)
- Rotação inteligente e programação horária
- Métricas por campanha, QR e PDF
- Gestão de frotas TVDE, motoristas, veículos, contratos e mensalidades
- Portal do anunciante com resultados fictícios

A **atividade online** exige que algum tablet/player comunique; não inventamos telemetria em tempo real. Os históricos iniciais são fictícios e rotulados como dados de demonstração.

## Limitação essencial do plano Free

O Render Free adormece após 15 minutos de inatividade. Como esta versão ainda usa **SQLite e carregamento de arquivos locais**, os dados adicionados e alterações feitas no teste perdem-se sempre que a instância reinicia. O site recria os exemplos fictícios no arranque. Não envie leads reais nem documentos de contrato.

Para operação efetiva com dados persistentes, será necessária arquitetura com base de dados e armazenamento persistentes (por exemplo, serviço pago com disco e backups ou migração para Postgres mais armazenamento de mídia). O acesso à internet e testes de tablets reais ainda precisam de validação.

## Se der erro

No Render vá ao serviço > **Logs** e envie somente a mensagem de erro, **sem senhas, tokens ou dados pessoais**.
