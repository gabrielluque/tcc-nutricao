"""
test_banco.py - Testes da camada de acesso a dados.

Cada teste roda contra um banco temporario proprio, criado do zero e
descartado ao final. Nenhum teste toca o saude.db real, e a ordem de
execucao nao importa.

Execucao:
    pytest -v
"""

import datetime
import os
import sqlite3
import tempfile

import pytest

import banco
import calculadora


def plano_exemplo(**ajustes):
    """Plano nutricional de referencia, com ajustes opcionais."""
    base = dict(peso=80, altura_cm=175, idade=30, sexo="M",
                nivel_atividade="moderado", objetivo="perder", bf=30)
    base.update(ajustes)
    return calculadora.montar_plano(**base)


@pytest.fixture
def db():
    """Banco temporario, vazio, com o esquema criado."""
    caminho = tempfile.mktemp(suffix=".db")
    banco.criar_esquema(caminho)
    yield caminho
    if os.path.exists(caminho):
        os.remove(caminho)


@pytest.fixture
def db_com_alimentos(db):
    """Banco com uma amostra de alimentos representando varios grupos."""
    amostra = [
        (1,  "Arroz, integral, cozido",   "Cereais",     124, 2.6,  1.0,  25.8, 2.7),
        (2,  "Feijao, carioca, cozido",   "Leguminosas",  76, 4.8,  0.5,  13.6, 8.5),
        (3,  "Frango, peito, grelhado",   "Carnes",      159, 32.0, 2.5,   0.0, 0.0),
        (4,  "Leite, integral",           "Laticinios",   61, 2.9,  3.2,   4.3, 0.0),
        (5,  "Queijo, minas, frescal",    "Laticinios",  264, 17.4, 20.2,  3.2, 0.0),
        (6,  "Ovo, de galinha, cozido",   "Ovos",        146, 13.3, 9.5,   0.6, 0.0),
        (7,  "Pao, frances",              "Cereais",     300, 8.0,  3.1,  58.6, 2.3),
        (8,  "Banana, prata",             "Frutas",       98, 1.3,  0.1,  26.0, 2.0),
        (9,  "Aveia, flocos",             "Cereais",     394, 13.9, 8.5,  66.6, 9.1),
        (10, "Carne, bovina, patinho",    "Carnes",      219, 35.9, 7.3,   0.0, 0.0),
        # Prato preparado: o nome nao revela que leva creme de leite. Esta
        # aqui para exercitar a regra dos alimentos preparados.
        (11, "Estrogonofe de carne",      "Alimentos preparados",
                                          143, 10.6, 9.4,   3.5, 0.3),
        # Laticinio que a lista original deixava passar: o nome nao tem
        # "leite" nem "queijo", tem "lactea".
        (12, "Bebida lactea, pessego",    "Laticinios",    77, 1.8,  1.2,  14.6, 0.0),
    ]
    for item in amostra:
        banco.inserir_alimento(*item, caminho=db)
    return db


# ==========================================================================
# ESQUEMA
# ==========================================================================

def test_criar_esquema_e_idempotente(db):
    """Rodar o script duas vezes nao pode falhar nem duplicar tabelas."""
    banco.criar_esquema(db)
    banco.criar_esquema(db)
    with banco.conectar(db) as conexao:
        tabelas = {linha["name"] for linha in conexao.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"usuarios", "alimentos", "eventos"} <= tabelas


def test_resultados_sao_acessiveis_por_nome(db_com_alimentos):
    """Regressao do bug do prototipo anterior.

    O historico exibia dados errados porque as colunas eram lidas por
    posicao e a insercao de uma coluna nova deslocou todos os indices. Com
    sqlite3.Row o acesso e por nome, e inserir colunas deixa de quebrar
    qualquer tela.
    """
    with banco.conectar(db_com_alimentos) as conexao:
        linha = conexao.execute(
            "SELECT * FROM alimentos WHERE codigo_taco = 3").fetchone()
    assert linha["nome"] == "Frango, peito, grelhado"
    assert linha["proteina_g"] == 32.0


# ==========================================================================
# USUARIOS E AUTENTICACAO
# ==========================================================================

def test_senha_nunca_e_gravada_em_texto_plano(db):
    """O teste mais importante deste arquivo.

    Le a coluna diretamente, sem passar pelas funcoes do modulo, e exige que
    a senha original nao apareca em lugar nenhum do registro.
    """
    banco.criar_usuario("Gabriel", "gabriel@teste.com", "senhaSuperSecreta123",
                        caminho=db)
    with banco.conectar(db) as conexao:
        linha = conexao.execute("SELECT * FROM usuarios").fetchone()

    assert "senhaSuperSecreta123" not in str(dict(linha))
    assert linha["senha_hash"] != "senhaSuperSecreta123"
    assert len(linha["senha_hash"]) > 40


def test_login_com_credenciais_corretas(db):
    banco.criar_usuario("Gabriel", "gabriel@teste.com", "abc123", caminho=db)
    usuario = banco.autenticar("gabriel@teste.com", "abc123", caminho=db)
    assert usuario is not None
    assert usuario["nome"] == "Gabriel"
    assert "senha_hash" not in usuario   # o hash nao vaza para a aplicacao


def test_login_com_senha_errada_falha(db):
    banco.criar_usuario("Gabriel", "gabriel@teste.com", "abc123", caminho=db)
    assert banco.autenticar("gabriel@teste.com", "errada", caminho=db) is None


def test_email_inexistente_e_senha_errada_dao_a_mesma_resposta(db):
    """Nao revelar quais e-mails possuem conta cadastrada."""
    banco.criar_usuario("Gabriel", "gabriel@teste.com", "abc123", caminho=db)
    assert banco.autenticar("naoexiste@teste.com", "abc123", caminho=db) is None
    assert banco.autenticar("gabriel@teste.com", "errada", caminho=db) is None


def test_email_e_normalizado(db):
    """Maiusculas e espacos nao criam contas duplicadas."""
    banco.criar_usuario("Gabriel", "  Gabriel@Teste.COM ", "abc123", caminho=db)
    assert banco.autenticar("gabriel@teste.com", "abc123", caminho=db) is not None


def test_email_duplicado_e_recusado(db):
    banco.criar_usuario("Gabriel", "gabriel@teste.com", "abc123", caminho=db)
    with pytest.raises(banco.EmailJaCadastrado):
        banco.criar_usuario("Outro", "gabriel@teste.com", "xyz789", caminho=db)


# ==========================================================================
# CATALOGO E RESTRICOES ALIMENTARES
#
# O bloco mais critico: o que passar por aqui indevidamente chega ao prato
# de alguem.
# ==========================================================================

def test_catalogo_sem_restricao_devolve_tudo(db_com_alimentos):
    assert len(banco.buscar_catalogo(caminho=db_com_alimentos)) == 12


def test_intolerancia_a_lactose_remove_laticinios(db_com_alimentos):
    catalogo = banco.buscar_catalogo(["lactose"], caminho=db_com_alimentos)
    nomes = " ".join(a["nome"].lower() for a in catalogo)
    assert "leite" not in nomes
    assert "queijo" not in nomes
    assert "frango" in nomes          # o resto do catalogo segue disponivel


def test_laticinio_que_nao_diz_leite_no_nome_tambem_sai(db_com_alimentos):
    """"Bebida lactea" nao contem "leite" nem "queijo".

    Encontrado em teste real contra a base da TACO, com a restricao de
    lactose declarada: o cardapio veio com 250 g de bebida lactea. Aqui o
    nome DIZ o que o alimento e - faltava a palavra no dicionario, e nao
    havia como o filtro descobrir sozinho.
    """
    catalogo = banco.buscar_catalogo(["lactose"], caminho=db_com_alimentos)
    assert all("lactea" not in a["nome_normalizado"] for a in catalogo)


def test_restricao_por_nome_livre(db_com_alimentos):
    """Restricao fora do dicionario e usada literalmente."""
    catalogo = banco.buscar_catalogo(["banana"], caminho=db_com_alimentos)
    assert all("banana" not in a["nome"].lower() for a in catalogo)
    # 12 na base, menos a banana e menos o prato preparado (ver o bloco
    # "ALIMENTOS PREPARADOS" mais abaixo).
    assert len(catalogo) == 10


def test_restricao_ignora_acentos_e_maiusculas(db_com_alimentos):
    """"Glúten", "GLUTEN" e "gluten" precisam ter o mesmo efeito."""
    a = banco.buscar_catalogo(["Glúten"], caminho=db_com_alimentos)
    b = banco.buscar_catalogo(["GLUTEN"], caminho=db_com_alimentos)
    assert {x["id"] for x in a} == {x["id"] for x in b}
    assert all("pao" not in x["nome_normalizado"] for x in a)


def test_varias_restricoes_se_acumulam(db_com_alimentos):
    catalogo = banco.buscar_catalogo(["lactose", "ovo"], caminho=db_com_alimentos)
    nomes = " ".join(a["nome_normalizado"] for a in catalogo)
    assert "leite" not in nomes
    assert "queijo" not in nomes
    assert "ovo" not in nomes


def test_dieta_vegana_remove_todos_os_produtos_animais(db_com_alimentos):
    catalogo = banco.buscar_catalogo(["vegano"], caminho=db_com_alimentos)
    grupos = {a["grupo"] for a in catalogo}
    assert "Carnes" not in grupos
    assert "Laticinios" not in grupos
    assert "Ovos" not in grupos
    assert "Frutas" in grupos


def test_alimentos_excluidos_sao_reportados(db_com_alimentos):
    """A interface precisa mostrar o que a restricao removeu, para que o
    usuario perceba um filtro amplo demais."""
    excluidos = banco.listar_excluidos(["lactose"], caminho=db_com_alimentos)
    nomes = {a["nome"] for a in excluidos}
    assert "Leite, integral" in nomes
    assert "Queijo, minas, frescal" in nomes


def test_catalogo_e_excluidos_nao_se_sobrepoem(db_com_alimentos):
    """Invariante: nenhum alimento pode estar nas duas listas ao mesmo tempo,
    e juntas elas cobrem o catalogo inteiro."""
    restricoes = ["lactose", "gluten"]
    dentro = {a["id"] for a in banco.buscar_catalogo(restricoes, caminho=db_com_alimentos)}
    fora = {a["id"] for a in banco.listar_excluidos(restricoes, caminho=db_com_alimentos)}
    assert dentro & fora == set()
    assert len(dentro | fora) == banco.contar_alimentos(caminho=db_com_alimentos)


# ==========================================================================
# ALIMENTOS PREPARADOS
#
# Regressao de um erro encontrado contra a base real: com a restricao
# "lactose" declarada, o sistema devolveu 250 g de estrogonofe de carne -
# que leva creme de leite. O filtro nao falhou, leu o nome; o nome e que
# nao diz o que tem dentro.
#
# A regra que corrige isso nao e uma palavra nova na lista: e recusar o que
# nao se consegue verificar.
# ==========================================================================

def test_prato_preparado_sai_quando_ha_restricao(db_com_alimentos):
    """O caso exato que falhou na base real."""
    catalogo = banco.buscar_catalogo(["lactose"], caminho=db_com_alimentos)
    assert all(a["grupo"] != banco.GRUPO_PREPARADO for a in catalogo)
    assert all("estrogonofe" not in a["nome"].lower() for a in catalogo)


def test_a_regra_vale_para_qualquer_restricao(db_com_alimentos):
    """Nao e uma correcao de lactose: e uma posicao sobre ingredientes
    desconhecidos. Vale para gluten, ovo, restricao livre, todas."""
    for restricao in (["gluten"], ["ovo"], ["vegano"], ["quiabo"]):
        catalogo = banco.buscar_catalogo(restricao, caminho=db_com_alimentos)
        assert all(a["grupo"] != banco.GRUPO_PREPARADO for a in catalogo), restricao


def test_sem_restricao_os_pratos_preparados_continuam_disponiveis(db_com_alimentos):
    """Quem nao declarou restricao nenhuma nao perde nada. A exclusao e uma
    precaucao dirigida a quem declarou, e nao um empobrecimento da base."""
    catalogo = banco.buscar_catalogo(caminho=db_com_alimentos)
    assert any(a["grupo"] == banco.GRUPO_PREPARADO for a in catalogo)


def test_restricao_vazia_nao_conta_como_restricao(db_com_alimentos):
    """Lista vazia e string em branco nao sao declaracao de restricao."""
    for nada in ([], None, [""], ["   "]):
        catalogo = banco.buscar_catalogo(nada, caminho=db_com_alimentos)
        assert len(catalogo) == 12, nada


def test_prato_preparado_aparece_na_lista_de_excluidos(db_com_alimentos):
    """O usuario tem direito de saber que a feijoada sumiu porque o sistema
    nao conhece a composicao dela - e nao porque ela tem lactose."""
    excluidos = banco.listar_excluidos(["lactose"], caminho=db_com_alimentos)
    assert "Estrogonofe de carne" in {a["nome"] for a in excluidos}


def test_filtro_por_grupo(db_com_alimentos):
    catalogo = banco.buscar_catalogo(grupos=["Frutas", "Cereais"],
                                     caminho=db_com_alimentos)
    assert {a["grupo"] for a in catalogo} == {"Frutas", "Cereais"}


# ==========================================================================
# CARDAPIOS GERADOS
# ==========================================================================

def cardapio_exemplo():
    """Cardapio minimo, no formato que integracao_ia.gerar_cardapio devolve."""
    item = {"codigo_taco": 1, "alimento": "Arroz, integral, cozido",
            "grupo": "Cereais", "gramas": 150.0, "kcal": 186.0,
            "proteina_g": 3.9, "gordura_g": 1.5, "carboidrato_g": 38.7,
            "fibra_g": 4.1}
    return {"refeicoes": [{"nome": "Almoço", "itens": [item],
                           "totais": {"kcal": 186.0}}],
            "totais": {"kcal": 186.0}, "comparacao": {},
            "descartados": [{"codigo_taco": 9999, "motivo": "fora do catálogo"}],
            "fator_de_ajuste": 1.08, "modelo": "gemini-2.5-flash"}


def registro_para_cardapio(db):
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    return uid, banco.salvar_registro(uid, 80, 30, "moderado", "perder", 4,
                                      plano_exemplo(), caminho=db)


def test_cardapio_volta_igual_ao_que_foi_gravado(db):
    """O cardapio e guardado para que a pessoa veja O MESMO plano quando
    voltar na tela. Um plano que muda sozinho a cada visita nao e um plano."""
    _, rid = registro_para_cardapio(db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)

    lido = banco.buscar_cardapio(rid, caminho=db)
    assert lido["refeicoes"][0]["itens"][0]["alimento"] == "Arroz, integral, cozido"
    assert lido["refeicoes"][0]["itens"][0]["kcal"] == pytest.approx(186.0)
    assert lido["modelo"] == "gemini-2.5-flash"


def test_registro_sem_cardapio_devolve_none(db):
    _, rid = registro_para_cardapio(db)
    assert banco.buscar_cardapio(rid, caminho=db) is None


def test_numeros_do_capitulo_4_ficam_em_coluna_e_nao_dentro_do_json(db):
    """Descartes e fator de ajuste viram estatistica. Numero que vai ser
    contado em SQL nao pode estar enterrado num campo de texto."""
    _, rid = registro_para_cardapio(db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)

    with banco.conectar(db) as conexao:
        linha = conexao.execute(
            "SELECT descartados, fator_de_ajuste FROM cardapios").fetchone()
    assert linha["descartados"] == 1
    assert linha["fator_de_ajuste"] == pytest.approx(1.08)


def test_gerar_de_novo_substitui_em_vez_de_acumular(db):
    _, rid = registro_para_cardapio(db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)

    with banco.conectar(db) as conexao:
        assert conexao.execute(
            "SELECT COUNT(*) AS n FROM cardapios").fetchone()["n"] == 1


def test_contador_de_trocas_sobrevive_a_um_cardapio_novo(db):
    """O numero de substituicoes mede o quanto as pessoas usam a liberdade de
    ajuste - a hipotese do trabalho. Zerar o contador ao gerar outro cardapio
    apagaria justamente o dado que interessa."""
    _, rid = registro_para_cardapio(db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)
    banco.registrar_substituicao(rid, cardapio_exemplo(), caminho=db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)

    assert banco.buscar_cardapio(rid, caminho=db)["substituicoes"] == 1


def test_excluir_conta_apaga_o_cardapio_junto(db):
    """Direito de eliminacao: o cardapio e dado alimentar do titular."""
    uid, rid = registro_para_cardapio(db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)

    banco.excluir_conta(uid, caminho=db)
    assert banco.buscar_cardapio(rid, caminho=db) is None


def test_resumo_de_cardapios_agrega_para_o_capitulo_4(db):
    uid, rid = registro_para_cardapio(db)
    banco.salvar_cardapio(rid, cardapio_exemplo(), caminho=db)
    banco.registrar_substituicao(rid, cardapio_exemplo(), caminho=db)

    resumo = banco.resumo_de_cardapios(caminho=db)
    assert resumo["gerados"] == 1
    assert resumo["itens_descartados"] == 1
    assert resumo["substituicoes"] == 1
    assert resumo["fator_medio"] == pytest.approx(1.08)


def test_resumo_em_banco_vazio_nao_quebra(db):
    assert banco.resumo_de_cardapios(caminho=db)["gerados"] == 0


# ==========================================================================
# MIGRACAO DO ESQUEMA
#
# O sistema ja esta no ar, com contas de voluntarios dentro. Toda coluna
# nova precisa chegar ao banco existente sem apagar nada - e CREATE TABLE IF
# NOT EXISTS, sozinho, nao faz isso.
# ==========================================================================

def banco_antigo():
    """Um banco no esquema anterior: registros sem as colunas novas."""
    caminho = tempfile.mktemp(suffix=".db")
    esquema = banco.ESQUEMA
    for coluna, _ in banco.COLUNAS_ACRESCENTADAS["registros"]:
        esquema = "\n".join(l for l in esquema.splitlines()
                             if not l.strip().startswith(coluna))
    with banco.conectar(caminho) as conexao:
        conexao.executescript(esquema)
    return caminho


def test_o_banco_antigo_realmente_nao_tem_as_colunas_novas():
    """Guarda o proprio teste: se o cenario deixar de ser o antigo, os testes
    de migracao abaixo passariam sem provar nada."""
    caminho = banco_antigo()
    with banco.conectar(caminho) as conexao:
        colunas = {c["name"] for c in conexao.execute("PRAGMA table_info(registros)")}
    assert "restricoes" not in colunas
    os.remove(caminho)


def test_migracao_acrescenta_as_colunas_sem_perder_dados():
    caminho = banco_antigo()
    uid = banco.criar_usuario("Voluntário", "v@t.com", "x", caminho=caminho)

    # Grava um registro pelo caminho antigo, sem as colunas novas.
    with banco.conectar(caminho) as conexao:
        conexao.execute(
            """INSERT INTO registros (usuario_id, criado_em, peso, bf,
                   nivel_atividade, objetivo, refeicoes_por_dia,
                   ajuste_calorico_padrao, ajuste_calorico_usado,
                   fator_proteina_padrao, fator_proteina_usado,
                   fator_gordura_padrao, fator_gordura_usado,
                   fator_agua_padrao, fator_agua_usado,
                   fator_fibras_padrao, fator_fibras_usado,
                   tmb, equacao_utilizada, get, meta_calorica, proteina_g,
                   gordura_g, carboidrato_g, agua_ml, fibras_g)
               VALUES (?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?)""",
            (uid, "2026-09-01T10:00:00", 82.0, 25.0, "moderado", "perder", 4,
             -0.2, -0.2, 2.2, 2.2, 0.8, 0.8, 35, 35, 14, 14,
             1700.0, "Katch-McArdle", 2400.0, 1920.0, 176.0, 66.0, 200.0,
             2870.0, 27.0))

    banco.criar_esquema(caminho)      # migra
    banco.criar_esquema(caminho)      # e e idempotente

    with banco.conectar(caminho) as conexao:
        linha = conexao.execute("SELECT * FROM registros").fetchone()
    assert linha["peso"] == 82.0            # o dado antigo continua la
    assert linha["restricoes"] == ""        # a coluna nova nasce com o padrao
    assert linha["preferencias"] == ""
    os.remove(caminho)


def test_migracao_cria_a_tabela_de_cardapios_no_banco_antigo():
    caminho = banco_antigo()
    banco.criar_esquema(caminho)
    with banco.conectar(caminho) as conexao:
        tabelas = {l["name"] for l in conexao.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "cardapios" in tabelas
    os.remove(caminho)


# ==========================================================================
# EVENTOS ANONIMOS
# ==========================================================================

def test_evento_e_registrado(db):
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    banco.registrar_evento(uid, "dieta_gerada", caminho=db)
    assert banco.contar_eventos_hoje(uid, "dieta_gerada", caminho=db) == 1


def test_tipo_de_evento_invalido_e_recusado(db):
    """Lista fechada de eventos: rotulos livres poluiriam a analise."""
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    with pytest.raises(ValueError):
        banco.registrar_evento(uid, "qualquer_coisa", caminho=db)


def test_contador_serve_de_base_para_o_limite_de_uso(db):
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    for _ in range(5):
        banco.registrar_evento(uid, "dieta_gerada", caminho=db)
    assert banco.contar_eventos_hoje(uid, "dieta_gerada", caminho=db) == 5
    assert banco.contar_eventos_hoje(uid, "pdf_baixado", caminho=db) == 0


def test_contador_e_por_usuario(db):
    a = banco.criar_usuario("A", "a@t.com", "x", caminho=db)
    b = banco.criar_usuario("B", "b@t.com", "x", caminho=db)
    banco.registrar_evento(a, "dieta_gerada", caminho=db)
    banco.registrar_evento(a, "dieta_gerada", caminho=db)
    banco.registrar_evento(b, "dieta_gerada", caminho=db)
    assert banco.contar_eventos_hoje(a, "dieta_gerada", caminho=db) == 2
    assert banco.contar_eventos_hoje(b, "dieta_gerada", caminho=db) == 1


def test_eventos_nao_guardam_dado_biometrico(db):
    """Garante o principio de minimizacao: a tabela nao tem onde guardar
    peso, altura ou percentual de gordura, ainda que alguem tente."""
    with banco.conectar(db) as conexao:
        colunas = {c[1] for c in conexao.execute("PRAGMA table_info(eventos)")}
    assert colunas == {"id", "usuario_id", "tipo", "detalhe", "criado_em"}
    for proibido in ("peso", "altura", "bf", "gordura", "idade"):
        assert proibido not in colunas


def test_eventos_contam_acoes_do_sistema(db):
    """Os eventos medem ACOES (quantas dietas, quantos PDFs); os registros
    medem CONTEUDO (quais objetivos, quais ajustes). Separar os dois evita
    que o contador de cota da IA se misture com a analise nutricional."""
    a = banco.criar_usuario("A", "a@t.com", "x", caminho=db)
    b = banco.criar_usuario("B", "b@t.com", "x", caminho=db)

    banco.registrar_evento(a, "dieta_gerada", caminho=db)
    banco.registrar_evento(a, "ajuste_pedido", caminho=db)
    banco.registrar_evento(a, "pdf_baixado", caminho=db)
    banco.registrar_evento(b, "dieta_gerada", caminho=db)

    resumo = banco.resumo_de_uso(caminho=db)
    assert resumo["eventos_por_tipo"]["dieta_gerada"] == 2
    assert resumo["eventos_por_tipo"]["pdf_baixado"] == 1


# ==========================================================================
# INTEGRIDADE
# ==========================================================================

def test_evento_exige_usuario_existente(db):
    """A chave estrangeira impede registro orfao."""
    with pytest.raises(sqlite3.IntegrityError):
        banco.registrar_evento(9999, "dieta_gerada", caminho=db)


def test_codigo_taco_duplicado_atualiza_em_vez_de_duplicar(db):
    """Reimportar a TACO nao pode multiplicar os alimentos."""
    banco.inserir_alimento(1, "Arroz", "Cereais", 124, 2.6, 1.0, 25.8, 2.7, caminho=db)
    banco.inserir_alimento(1, "Arroz, integral", "Cereais", 124, 2.6, 1.0, 25.8, 2.7, caminho=db)
    assert banco.contar_alimentos(caminho=db) == 1


# ==========================================================================
# PERFIL
# ==========================================================================

def test_perfil_e_salvo_e_reaproveitado(db):
    """Na segunda visita o usuario confirma apenas o peso."""
    uid = banco.criar_usuario("Gabriel", "g@t.com", "x", caminho=db)
    banco.atualizar_perfil(uid, sexo="M", altura_cm=175,
                           data_nascimento="1996-03-15", caminho=db)
    perfil = banco.buscar_perfil(uid, caminho=db)
    assert perfil["sexo"] == "M"
    assert perfil["altura_cm"] == 175


def test_atualizar_perfil_parcialmente_preserva_o_resto(db):
    """COALESCE: passar apenas um campo nao apaga os demais."""
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    banco.atualizar_perfil(uid, sexo="F", altura_cm=165,
                           data_nascimento="2000-01-01", caminho=db)
    banco.atualizar_perfil(uid, altura_cm=166, caminho=db)
    perfil = banco.buscar_perfil(uid, caminho=db)
    assert perfil["altura_cm"] == 166
    assert perfil["sexo"] == "F"


def test_idade_e_derivada_da_data_de_nascimento(db):
    """Armazenar idade a deixaria desatualizada com o tempo, alimentando o
    calculo metabolico com um valor errado. Derivando da data, isso nao
    acontece."""
    assert banco.calcular_idade("1996-03-15", hoje=datetime.date(2026, 3, 14)) == 29
    assert banco.calcular_idade("1996-03-15", hoje=datetime.date(2026, 3, 15)) == 30
    assert banco.calcular_idade("1996-03-15", hoje=datetime.date(2027, 3, 15)) == 31
    assert banco.calcular_idade(None) is None


def test_consentimento_lgpd_e_registrado_com_data(db):
    """O registro precisa ter valor probatorio: quem consentiu e quando."""
    uid = banco.criar_usuario("G", "g@t.com", "x", consentiu_lgpd=True, caminho=db)
    with banco.conectar(db) as conexao:
        linha = conexao.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    assert linha["consentiu_lgpd"] == 1
    assert linha["consentimento_em"] is not None


# ==========================================================================
# HISTORICO
# ==========================================================================

def test_registro_guarda_padrao_e_escolhido(db):
    """Sem o valor padrao gravado junto, seria impossivel saber depois se o
    usuario aceitou a recomendacao ou a alterou."""
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    plano = plano_exemplo(fator_proteina=2.4)
    rid = banco.salvar_registro(uid, 80, 30, "moderado", "perder", 5, plano, caminho=db)

    registro = banco.buscar_registro(rid, caminho=db)
    assert registro["fator_proteina_padrao"] == 2.2
    assert registro["fator_proteina_usado"] == 2.4
    assert registro["equacao_utilizada"] == "Katch-McArdle"
    assert registro["tmb"] == pytest.approx(1579.6)


def test_historico_vem_do_mais_recente_para_o_mais_antigo(db):
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    for peso in (80, 79, 78):
        banco.salvar_registro(uid, peso, 30, "moderado", "perder", 4,
                              plano_exemplo(peso=peso), caminho=db)
    historico = banco.listar_registros(uid, caminho=db)
    assert len(historico) == 3
    assert historico[0]["peso"] == 78


def test_usuario_nao_ve_registro_de_outro(db):
    """Impede que alguem acesse o historico alheio trocando o numero na
    barra de enderecos."""
    a = banco.criar_usuario("A", "a@t.com", "x", caminho=db)
    b = banco.criar_usuario("B", "b@t.com", "x", caminho=db)
    rid = banco.salvar_registro(a, 80, 30, "moderado", "perder", 4,
                                plano_exemplo(), caminho=db)
    assert banco.buscar_registro(rid, usuario_id=a, caminho=db) is not None
    assert banco.buscar_registro(rid, usuario_id=b, caminho=db) is None


def test_evolucao_de_peso_vem_em_ordem_cronologica(db):
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    for peso in (82, 80, 78):
        banco.salvar_registro(uid, peso, 30, "moderado", "perder", 4,
                              plano_exemplo(peso=peso), caminho=db)
    serie = banco.evolucao_de_peso(uid, caminho=db)
    assert [r["peso"] for r in serie] == [82, 80, 78]


# ==========================================================================
# PEDIDOS DE AJUSTE DO CARDAPIO
# ==========================================================================

def test_pedidos_preservam_a_ordem_da_conversa(db):
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    rid = banco.salvar_registro(uid, 80, 30, "moderado", "perder", 4,
                                plano_exemplo(), caminho=db)
    banco.salvar_pedido_ajuste(rid, "não como aveia de manhã", caminho=db)
    banco.salvar_pedido_ajuste(rid, "prefiro pão com ovo", caminho=db)

    pedidos = banco.listar_pedidos(rid, caminho=db)
    assert [p["ordem"] for p in pedidos] == [1, 2]
    assert pedidos[0]["texto"] == "não como aveia de manhã"


# ==========================================================================
# LGPD - DIREITO DE ELIMINACAO
# ==========================================================================

def test_excluir_conta_apaga_tudo_em_cascata(db):
    """Direito de eliminacao (Lei 13.709/2018, art. 18). A remocao e
    definitiva: nao ha copia nem marcacao de inativo."""
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    rid = banco.salvar_registro(uid, 80, 30, "moderado", "perder", 4,
                                plano_exemplo(), caminho=db)
    banco.salvar_pedido_ajuste(rid, "sem lactose", caminho=db)
    banco.registrar_evento(uid, "dieta_gerada", caminho=db)

    banco.excluir_conta(uid, caminho=db)

    with banco.conectar(db) as conexao:
        for tabela in ("usuarios", "registros", "pedidos_ajuste", "eventos"):
            n = conexao.execute(f"SELECT COUNT(*) AS n FROM {tabela}").fetchone()["n"]
            assert n == 0, f"sobrou dado em {tabela}"


def test_excluir_conta_nao_afeta_outros_usuarios(db):
    a = banco.criar_usuario("A", "a@t.com", "x", caminho=db)
    b = banco.criar_usuario("B", "b@t.com", "x", caminho=db)
    banco.salvar_registro(a, 80, 30, "moderado", "perder", 4, plano_exemplo(), caminho=db)
    banco.salvar_registro(b, 70, None, "leve", "ganhar", 3, plano_exemplo(), caminho=db)

    banco.excluir_conta(a, caminho=db)

    assert banco.buscar_perfil(b, caminho=db) is not None
    assert len(banco.listar_registros(b, caminho=db)) == 1


# ==========================================================================
# ANALISE PARA O CAPITULO 4
# ==========================================================================

def test_analise_detecta_quem_aceitou_e_quem_alterou(db):
    """O teste empirico da hipotese do trabalho."""
    a = banco.criar_usuario("A", "a@t.com", "x", caminho=db)
    b = banco.criar_usuario("B", "b@t.com", "x", caminho=db)

    # A aceita tudo como veio.
    banco.salvar_registro(a, 80, 30, "moderado", "perder", 4,
                          plano_exemplo(), caminho=db)
    # B aumenta a proteina.
    banco.salvar_registro(b, 75, None, "intenso", "ganhar", 6,
                          plano_exemplo(fator_proteina=2.4), caminho=db)

    analise = banco.analise_de_personalizacao(caminho=db)
    assert analise["participantes"] == 2
    assert analise["usuarios_que_ajustaram"] == 1
    assert analise["percentual_de_usuarios"] == 50.0
    assert analise["por_parametro"]["proteina"]["alteracoes"] == 1
    assert analise["por_parametro"]["proteina"]["desvio_medio"] == pytest.approx(0.2)
    assert analise["por_parametro"]["gordura"]["alteracoes"] == 0


def test_analise_em_banco_vazio_nao_quebra(db):
    """Divisao por zero e o jeito mais facil de derrubar uma tela de
    estatisticas no dia da apresentacao."""
    analise = banco.analise_de_personalizacao(caminho=db)
    assert analise["percentual_de_usuarios"] == 0.0
    assert analise["por_parametro"]["proteina"]["percentual"] == 0.0
    assert banco.resumo_de_uso(caminho=db)["participantes"] == 0


def test_resumo_de_uso_agrega_objetivos_e_refeicoes(db):
    a = banco.criar_usuario("A", "a@t.com", "x", caminho=db)
    b = banco.criar_usuario("B", "b@t.com", "x", caminho=db)
    banco.salvar_registro(a, 80, 30, "moderado", "perder", 4, plano_exemplo(), caminho=db)
    banco.salvar_registro(b, 75, None, "intenso", "ganhar", 6, plano_exemplo(), caminho=db)

    resumo = banco.resumo_de_uso(caminho=db)
    assert resumo["total_de_calculos"] == 2
    assert resumo["objetivos_escolhidos"] == {"perder": 1, "ganhar": 1}
    assert resumo["refeicoes_por_dia"] == {4: 1, 6: 1}


def test_pedidos_mais_comuns_nao_expoe_quem_pediu(db):
    """Interessa o que foi pedido, nao quem pediu."""
    uid = banco.criar_usuario("G", "g@t.com", "x", caminho=db)
    rid = banco.salvar_registro(uid, 80, 30, "moderado", "perder", 4,
                                plano_exemplo(), caminho=db)
    banco.salvar_pedido_ajuste(rid, "trocar o almoço", caminho=db)
    assert banco.pedidos_mais_comuns(caminho=db) == ["trocar o almoço"]
