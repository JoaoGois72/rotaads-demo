"""Registos FICTÍCIOS para a demonstração Render — nunca importa dados locais."""
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from werkzeug.security import generate_password_hash

DEMO_EMAIL = 'anunciante.demo@exemplo.pt'


def seed_demo(db, upload_folder: Path, root: Path):
    """Popula somente a base de demonstração vazia. Seguro repetir em novo arranque."""
    if db.execute('SELECT id FROM anunciantes WHERE email=?', (DEMO_EMAIL,)).fetchone():
        return
    now = datetime.now(timezone.utc)
    iso = now.isoformat(timespec='seconds')
    password = os.environ.get('DEMO_ADVERTISER_PASSWORD')
    if not password:
        raise RuntimeError('DEMO_ADVERTISER_PASSWORD obrigatório para a demonstração.')

    def add(sql, params):
        return db.execute(sql, params).lastrowid

    # A conta é fictícia, e a senha é configurada em segredo no Render.
    advertiser = add('''INSERT INTO anunciantes(nome,empresa,email,senha_hash,ativo,criado_em)
                        VALUES(?,?,?,?,1,?)''',
                     ('Ana Demonstração', 'Lisboa Sabores — Exemplo', DEMO_EMAIL,
                      generate_password_hash(password), iso))
    zone = add('''INSERT INTO zonas(nome,cidade,latitude,longitude,raio_m,prioridade,ativo,criado_em)
                  VALUES(?,?,?,?,?,0,1,?)''',
               ('Lisboa Centro (Exemplo)', 'Lisboa', 38.7223, -9.1393, 1500, iso))
    sample_ids = []
    for num, name, brand, peso in (
        (1, 'Restaurante Lisboa — Demonstração', 'Lisboa Sabores (Exemplo)', 5),
        (2, 'Hotel Horizonte — Demonstração', 'Hotel Horizonte (Exemplo)', 1),
    ):
        filename = f'rotaads_demo_campanha_{num}.jpg'
        shutil.copy2(root / 'demo_media' / f'demo_{num}.jpg', upload_folder / filename)
        cid = add('''INSERT INTO campanhas
            (nome,anunciante,cidade,carros_contratados,ativo,data_inicio,data_fim,
             ficheiro,tipo_media,duracao_seg,cupao_ativo,cupao_codigo,cupao_descricao,
             cupao_url,criado_em,anunciante_id,peso_v13)
             VALUES(?,?,?,?,1,NULL,NULL,?,'imagem',12,1,?,?,?, ?,?,?)''',
            (name,brand,'Lisboa',5,filename,
             f'DEMO-{num}', 'Oferta fictícia para avaliação', '', iso,
             advertiser if num == 1 else None, peso))
        sample_ids.append(cid)
        add('INSERT INTO campanhas_zonas(campanha_id,zona_id) VALUES(?,?)', (cid,zone))
    for typ,nome,empresa,qt in (
        ('anunciante','Cliente de exemplo','Restaurante Exemplo',10),
        ('agencia','Agência de exemplo','Agência Visual',25),
        ('frota','Responsável de exemplo','Frota Lisboa',12),
        ('motorista','Motorista de exemplo','Individual',1),
    ):
        add('''INSERT INTO leads(tipo,nome,email,empresa,cidade,carros,criado_em)
               VALUES(?,?,?,?,?,?,?)''',
            (typ,nome,'exemplo@exemplo.pt',empresa,'Lisboa',qt,iso))
    d1=add('''INSERT INTO dispositivos(nome,parceiro,cidade,token,ativo,criado_em,otimizacao_ativa)
              VALUES(?,?,?, ?,1,?,1)''',
           ('LIS-DEMO-01','Frota Lisboa — Exemplo','Lisboa',secrets.token_urlsafe(30),iso))
    d2=add('''INSERT INTO dispositivos(nome,parceiro,cidade,token,ativo,criado_em,otimizacao_ativa)
              VALUES(?,?,?, ?,1,?,0)''',
           ('LIS-DEMO-02','Motorista Independente — Exemplo','Lisboa',secrets.token_urlsafe(30),iso))
    for cid in sample_ids:
        add('INSERT INTO atribuicoes(dispositivo_id,campanha_id) VALUES(?,?)', (d1,cid))
    add('INSERT INTO atribuicoes(dispositivo_id,campanha_id) VALUES(?,?)', (d2,sample_ids[0]))

    fleet=add('''INSERT INTO frotas_v14(nome,empresa,email,telefone,nif,cidade,capacidade,ativo,criado_em)
                  VALUES(?,?,?,?,?,?,?,1,?)''',
              ('Gestor de demonstração','Frota Lisboa — Exemplo','frota@exemplo.pt','', '', 'Lisboa',12,iso))
    driver1=add('''INSERT INTO motoristas_v14(nome,email,frota_id,ativo,criado_em)
                   VALUES(?,?,?,1,?)''',
                ('Motorista Fictício da Frota','motorista1@exemplo.pt',fleet,iso))
    driver2=add('''INSERT INTO motoristas_v14(nome,email,frota_id,ativo,criado_em)
                   VALUES(?,?,NULL,1,?)''',
                ('Motorista Individual Fictício','motorista2@exemplo.pt',iso))
    v1=add('''INSERT INTO veiculos_v14(matricula,marca,modelo,frota_id,motorista_id,dispositivo_id,ativo,criado_em)
               VALUES(?,?,?,?,?,?,1,?)''',
           ('DE-00-01','Peugeot','308',fleet,driver1,d1,iso))
    v2=add('''INSERT INTO veiculos_v14(matricula,marca,modelo,frota_id,motorista_id,dispositivo_id,ativo,criado_em)
               VALUES(?,?,?,NULL,?,?,1,?)''',
           ('DE-00-02','Renault','Captur',driver2,d2,iso))

    today=now.astimezone(ZoneInfo('Europe/Lisbon')).date()
    starts=today.replace(day=1).isoformat()
    month=today.strftime('%Y-%m')
    for vid,typ,beneficiary,cents,day in (
        (v1,'FROTA',fleet,14590,10),(v2,'MOTORISTA',driver2,9900,15)):
        contract=add('''INSERT INTO contratos_v14
            (veiculo_id,beneficiario_tipo,beneficiario_id,valor_centimos,
             data_inicio,dia_vencimento,estado,observacoes,criado_em)
             VALUES(?,?,?,?,?,?,'ATIVO','Documento de demonstração — não assinado',?)''',
             (vid,typ,beneficiary,cents,starts,day,iso))
        add('''INSERT INTO pagamentos_v14
            (contrato_id,competencia,vencimento,valor_centimos,estado,criado_em)
            VALUES(?,?,?,?,'PENDENTE',?)''',
            (contract,month,today.replace(day=day).isoformat(),cents,iso))

    # Históricos fictícios: nunca representam métricas de reprodução reais.
    for delta in range(14, 0, -1):
        day_start=now-timedelta(days=delta)
        for j in range(4):
            stamp=day_start.replace(hour=(9+j*3)%24, minute=10,second=0).isoformat(timespec='seconds')
            for cid in sample_ids:
                add('''INSERT INTO exibicoes(dispositivo_id,campanha_id,criado_em,zona_id)
                       VALUES(?,?,?,?)''', (d1,cid,stamp,zone))
        for j in range(2):
            add('INSERT INTO leituras_qr(campanha_id,criado_em) VALUES(?,?)',
                (sample_ids[0],day_start.replace(hour=13+j).isoformat(timespec='seconds')))
    for delta in (8,4,2):
        add('INSERT INTO resgates_cupao(campanha_id,referencia,criado_em) VALUES(?,?,?)',
            (sample_ids[0],'RESGATE-DEMONSTRATIVO',(now-timedelta(days=delta)).isoformat(timespec='seconds')))
    db.commit()
