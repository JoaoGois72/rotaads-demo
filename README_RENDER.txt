ROTAADS V1.4 — DEMONSTRAÇÃO PRIVADA NO RENDER
==============================================
ESTE ZIP NÃO INCLUI BASE DE DADOS REAL, SENHAS, TOKENS REAIS OU CLIENTES.

1) Extrair os ficheiros deste ZIP para uma pasta nova no Windows.
   Não misturar com a pasta "Programa rotaads" que já funciona.

2) Criar um repositório NOVO e PRIVADO no GitHub, por exemplo rotaads-demo.
   Enviar para o repositório TODOS OS FICHEIROS desta pasta, incluindo
   render.yaml, app.py, frotas_v14.py, demo_data.py, templates e static.
   NÃO publicar .env, instance/ ou uploads/ (existe .gitignore).

3) Em https://dashboard.render.com/ iniciar sessão, escolher New > Blueprint,
   conectar o repositório privado no GitHub e selecionar o render.yaml.
   Se a conta mostrar uma interface diferente: New > Web Service > escolher
   o repositório, linguagem Python, build pip install -r requirements.txt,
   start gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 120 app:app.

4) Preencher no Render (Environment), com VALORES DIFERENTES entre si:
   ADMIN_PASSWORD            senha forte do administrador
   DEMO_ACCESS_PASSWORD      senha para o sobrinho abrir todo o site
   DEMO_ADVERTISER_PASSWORD  senha da conta fictícia do anunciante
   SECRET_KEY é gerada automaticamente pelo Blueprint.
   Não colocar estas senhas no código e não enviar por esta conversa.

5) Esperar que o Render indique "Live" e copiar o URL HTTPS gerado,
   algo como https://rotaads-demonstracao.onrender.com (URL ILUSTRATIVO).
   Não há qualquer domínio .pt reservado por este pacote.

6) Para o sobrinho abrir:
   - URL HTTPS real do Render
   - Credenciais da PORTA DA DEMO: usuário visitante e DEMO_ACCESS_PASSWORD
   - Área ADMIN em /admin/entrar: usuário admin + ADMIN_PASSWORD
   - Área ANUNCIANTE em /anunciante/entrar:
       email anunciante.demo@exemplo.pt + DEMO_ADVERTISER_PASSWORD
   Enviar senhas por canal privado; não publicar em GitHub ou redes sociais.

7) O que testar: site e quatro formulários, campanhas, player de anúncios,
   dashboard, relatórios, zonas GPS simuladas, frotas, motoristas, veículos,
   contratos e pagamentos. Tudo é dado fictício. O contador online fica
   OFFLINE até um player real/simulador enviar sinal.

ATENÇÃO AO RENDER FREE
- O plano gratuito entra em suspensão após 15 minutos sem utilização.
- O SQLite e imagens carregadas no servidor desaparecem quando reinicia.
- Ao acordar, o sistema recria as contas e dados EXCLUSIVAMENTE de demonstração.
- Não utilizar com clientes reais, documentos assinados, ou operação comercial.
- Para testes persistentes recomenda-se adaptar para Postgres e armazenamento
  permanente de media, ou contratar uma instância com disco persistente e backups.
- O SITE_URL no Render é deduzido de RENDER_EXTERNAL_URL; HTTPS já é disponibilizado.
- O vídeo GPS com localização real ainda requer validação em tablet Android.

VERIFICAÇÃO
- No Render Logs deve aparecer Gunicorn sem exceção.
- https://SEU-DOMINIO-REAL/healthz responde ok, sem pedir senha.
- Abrir / pede usuário "visitante" e senha definida.
- NUNCA copiar a pasta "instance" ou o "uploads" do Windows para este repo.

OBS.: Não é um ambiente de produção. O controlo por senha partilhada é
adequado apenas a avaliação temporária por pessoas de confiança.
