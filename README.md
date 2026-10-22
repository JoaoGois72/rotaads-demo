# RotaAds V1.4 — Frotas, Motoristas, Veículos e Pagamentos

**Nova versão aditiva**, construída sobre a RotaAds V1.3.1 já validada, **incluindo a correção de exportação PDF**. A V1.3.1 anterior é mantida intocada como ponto de retorno. Este projeto não contém os dados reais do seu computador; a migração copia-os para um novo local.

## Funcionalidades

1. **Frotas TVDE:** cadastro e edição de empresa, responsável, e-mail, cidade, telefone, NIF opcional, capacidade declarada; ativação/inativação sem apagar históricos.
2. **Motoristas:** próprios de frotas ou independentes, com cadastro, edição, vínculo e estado.
3. **Veículos:** matrícula única, marca, modelo, frota, motorista e vínculo **opcional** a um tablet/ecrã Android cadastrado na plataforma. O vínculo não interfere em campanhas nem nas regras de geolocalização.
4. **Contratos de cedência:** um beneficiário (frota ou motorista do veículo), valor fixo mensal em euros, início, término opcional, dia de vencimento, notas e estado (ativo, suspenso, encerrado). O sistema rejeita contratos vigentes sobrepostos para o mesmo veículo.
5. **Mensalidades:** emissão idempotente (sem duplicações) por competência mensal, respeitando vigência e contrato/veículo ativo; valor é congelado no lançamento; marcação manual de pago e referência do comprovativo.
6. **Painel financeiro administrativo:** totais lançados, pagos, pendentes e vencidos; filtro mensal, exportação CSV e PDF em euros. Cada contrato dispõe de uma minuta administrativa em PDF para revisão. **Não existe integração bancária**: marcar como pago é uma confirmação manual, não uma transferência.
7. **Segurança:** só ADMIN pode consultar ou alterar dados de frota/contratos/pagamentos; todas as operações de escrita exigem CSRF; histórico financeiro não pode ser eliminado pela interface; exportação CSV protegida contra injeção de fórmulas.
8. **Compatibilidade:** site público, formulários, campanhas, player Android, GPS, rotas de zonas, otimização e dashboard V1.3.1 (incluindo download direto de PDF) continuam intactos.

## Instalação no Windows — sem perder a V1.3.1

1. **Pare a plataforma V1.3.1 com `Ctrl+C`** no PowerShell e mantenha a pasta anterior guardada. É aconselhável copiar essa pasta para uma unidade externa. **Não extraia a V1.4 por cima da versão anterior.**
2. Extraia o ZIP da V1.4 na pasta **`C:\rotaads_v1_4`**. Confirme que `app.py` existe nesse diretório.
3. Copie o banco SQLite, o `.env` e os arquivos dos anúncios **a partir da pasta da V1.3.1 que já funciona no seu computador**, usando o migrador (não faz migração no local de origem):

```powershell
cd C:\rotaads_v1_4
py migrar_da_v1_3_1.py "C:\Users\engjo\OneDrive\Documentos\Programa rotaads"
```

Se a versão funcional estiver noutro caminho, altere o segundo argumento. O migrador cria automaticamente um **backup ZIP completo em `C:\rotaads_v1_4\backups`** e recusa sobrescrever `.env` ou banco já existentes no destino. Verifique a mensagem `OK` antes de continuar. O SQLite é copiado com a API de backup do SQLite, preservando integridade de transações. O backup pode conter credenciais e dados pessoais; guarde-o fora da pasta pública e não o partilhe.

4. Prepare o ambiente:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python configurar_windows.py
```

5. Execute os testes **em bancos temporários**, sem modificar o banco migrado:

```powershell
python testes_v1_0.py
python testes_v1_1.py
python testes_v1_2.py
python testes_v1_3.py
python testes_v1_3_1.py
python testes_v1_3_1_flask.py
python testes_correcao_pdf_v131.py
python testes_v1_4.py
```

6. Se todos os testes passarem:

```powershell
python app.py
```

Ao iniciar, o Flask cria apenas as **novas tabelas `*_v14`**. Não é necessário alterar as tabelas de campanhas, dispositivos ou anunciantes. A primeira execução gera o esquema V1.4 na **cópia migrada**, sem alterar o banco da V1.3.1.

## Endereços

| Área | Endereço (com servidor local ativo) |
|---|---|
| Página pública | http://127.0.0.1:5000 |
| Administração | http://127.0.0.1:5000/admin/entrar |
| **Frotas** | http://127.0.0.1:5000/admin/frotas |
| **Motoristas** | http://127.0.0.1:5000/admin/motoristas |
| **Veículos** | http://127.0.0.1:5000/admin/veiculos |
| **Contratos** | http://127.0.0.1:5000/admin/contratos |
| **Pagamentos** | http://127.0.0.1:5000/admin/pagamentos |
| Dashboard inteligente | http://127.0.0.1:5000/admin/inteligencia |
| Portal do anunciante | http://127.0.0.1:5000/anunciante/entrar |

### Roteiro de teste funcional

- Criar **Frota Lisboa Exemplo**, uma cidade e capacidade de 3 carros.
- Criar um motorista dessa frota e outro como **individual**.
- Registar dois veículos, vinculando o primeiro ao ecrã de teste já cadastrado.
- Criar contratos: valor `150,00 €` pago à frota e `100,00 €` ao motorista independente.
- Em **Pagamentos**, selecionar mês e clicar em **Gerar mensalidades**. Devem aparecer dois pagamentos, total **250,00 €**.
- Clicar novamente em gerar: **não** podem aparecer mensalidades duplicadas.
- Confirmar como pago um dos pagamentos, com referência do comprovativo; verificar o indicador **Confirmado** e descarregar o CSV.
- Confirmar que campanhas, reprodução GPS e o **PDF do Dashboard V1.3.1** continuam a funcionar.

## Voltar à V1.3.1

Pare a V1.4 com `Ctrl+C`. Entre na **pasta original da V1.3.1** (não alterada), ative o ambiente e execute `python app.py` lá. **Registos criados somente na V1.4 não aparecerão automaticamente na versão antiga.** Guarde uma cópia do banco da V1.4 se pretender voltar mais tarde.

## Notas importantes

- O valor fixo é guardado em **cêntimos de euro**, sem arredondamento binário. Cada mensalidade mantém o valor do contrato na altura em que foi gerada.
- `PAGO` não comprova automaticamente transferência. O sistema não gera documentos fiscais, faturas eletrónicas ou assinaturas jurídicas. O registo de cedência **não substitui um contrato escrito e assinado**.
- NIF, contactos, localização de ecrãs e dados financeiros exigem política de privacidade, limitação de acesso, conservação e procedimentos adequados ao RGPD antes de ir para produção.
- SQLite é adequado ao protótipo e testes pequenos. Para frota comercial grande: PostgreSQL, HTTPS, autenticação reforçada, gestão de credenciais e monitorização.
- O servidor de desenvolvimento Flask não deve ser exposto na internet. Para GPS real dos tablets é necessário HTTPS fora de `localhost`.
- Testes Python, schema SQLite, migração e templates foram verificados isoladamente neste ambiente; as rotas Flask completas devem ser testadas no seu Windows, onde a biblioteca Flask estará instalada.
