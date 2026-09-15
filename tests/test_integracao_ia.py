"""
test_integracao_ia.py - Testes da camada de IA.

--------------------------------------------------------------------------
COMO SE TESTA UM COMPONENTE PROBABILISTICO
--------------------------------------------------------------------------
Nao se testa. Testa-se o que o sistema faz COM a resposta dele.

A resposta do modelo e imprevisivel por natureza: pedir o mesmo cardapio
duas vezes devolve dois cardapios diferentes, e um teste que dependesse do
conteudo da resposta falharia por motivo nenhum. Por isso nenhum teste deste
arquivo chama a API.

O que se testa aqui e a fronteira: dada uma resposta qualquer - correta,
errada, maliciosa ou absurda - o sistema produz um cardapio seguro e
aritmeticamente correto, ou recusa.

O ponto de injecao e o parametro "chamar" de gerar_cardapio. Ele existe
exatamente para isto: os testes passam uma funcao que devolve uma resposta
pronta, e o codigo de producao fica identico ao codigo testado, menos a
rede.

A pergunta que este arquivo responde e uma so:

    E se o modelo mentir?

Execucao:
    pytest -v
"""

import pytest

import integracao_ia as ia


# ==========================================================================
# CATALOGO DE TESTE
#
# Numeros redondos: a conta esperada e conferivel de cabeca por quem le.
# ==========================================================================

ARROZ = {"codigo_taco": 1, "nome": "Arroz cozido", "grupo": "Cereais",
         "kcal": 100.0, "proteina_g": 2.0, "gordura_g": 0.0,
         "carboidrato_g": 25.0, "fibra_g": 1.0}

FEIJAO = {"codigo_taco": 2, "nome": "Feijão carioca cozido", "grupo": "Leguminosas",
          "kcal": 80.0, "proteina_g": 5.0, "gordura_g": 0.5,
          "carboidrato_g": 14.0, "fibra_g": 8.0}

FRANGO = {"codigo_taco": 3, "nome": "Frango grelhado", "grupo": "Carnes",
          "kcal": 160.0, "proteina_g": 32.0, "gordura_g": 3.0,
          "carboidrato_g": 0.0, "fibra_g": 0.0}

# Este NAO entra no catalogo dos testes de restricao: e o alimento que o
# modelo vai tentar devolver mesmo sem ele ter sido oferecido.
LEITE = {"codigo_taco": 4, "nome": "Leite integral", "grupo": "Leite",
         "kcal": 60.0, "proteina_g": 3.0, "gordura_g": 3.0,
         "carboidrato_g": 5.0, "fibra_g": 0.0}

CATALOGO = [ARROZ, FEIJAO, FRANGO]

PLANO = {
    "meta_calorica": 2000.0,
    "proteina_g": 150.0,
    "gordura_g": 55.0,
    "carboidrato_g": 225.0,
    "fibras_g": 30.0,
}


def resposta_fixa(dados):
    """Devolve uma funcao 'chamar' que ignora o prompt e responde sempre a
    mesma coisa. E o dubles de IA usado no arquivo inteiro."""
    return lambda prompt: dados


CARDAPIO_VALIDO = {
    "refeicoes": [
        {"nome": "Almoço", "itens": [
            {"codigo_taco": 1, "gramas": 200},
            {"codigo_taco": 2, "gramas": 100},
            {"codigo_taco": 3, "gramas": 150},
        ]},
        {"nome": "Jantar", "itens": [
            {"codigo_taco": 1, "gramas": 150},
            {"codigo_taco": 3, "gramas": 120},
        ]},
    ]
}


# ==========================================================================
# O PROMPT
# ==========================================================================

def test_catalogo_vai_inteiro_para_o_prompt():
    texto = ia.catalogo_em_texto(CATALOGO)
    assert len(texto.splitlines()) == len(CATALOGO)
    assert "1|Arroz cozido|100|2.0|0.0|25.0" in texto


def test_prompt_traz_as_metas_e_o_catalogo():
    prompt = ia.montar_prompt(PLANO, 3, CATALOGO)
    assert "2000 kcal" in prompt
    assert "150 g" in prompt
    assert "Arroz cozido" in prompt
    assert "Café da manhã, Almoço, Jantar" in prompt


def test_prompt_nao_oferece_o_alimento_proibido():
    """A barreira 1 do modulo.

    A restricao alimentar nao e um pedido em linguagem natural dentro do
    texto - seria um favor que o modelo pode esquecer. O alimento proibido
    simplesmente nao existe no prompt.
    """
    prompt = ia.montar_prompt(PLANO, 3, CATALOGO)
    assert "Leite" not in prompt


def test_preferencias_entram_quando_existem():
    assert "batata" in ia.montar_prompt(PLANO, 3, CATALOGO, "batata doce")
    assert "gosta destes alimentos" not in ia.montar_prompt(PLANO, 3, CATALOGO, "   ")


def test_numero_de_refeicoes_estranho_nao_quebra_o_prompt():
    prompt = ia.montar_prompt(PLANO, 9, CATALOGO)
    assert "Almoço" in prompt


# ==========================================================================
# VALIDACAO: E SE O MODELO MENTIR?
# ==========================================================================

def test_codigo_inventado_e_descartado():
    resposta = {"refeicoes": [{"nome": "Almoço", "itens": [
        {"codigo_taco": 1, "gramas": 100},
        {"codigo_taco": 9999, "gramas": 100},
    ]}]}
    refeicoes, descartados = ia.validar(resposta, CATALOGO)
    assert len(refeicoes[0]["itens"]) == 1
    assert descartados[0]["codigo_taco"] == 9999


def test_alimento_proibido_e_descartado_mesmo_se_o_modelo_insistir():
    """A barreira 2, e a propriedade de seguranca do arquivo.

    O leite nao foi oferecido no prompt. Se ainda assim o modelo devolver o
    codigo dele - por alucinacao ou porque o usuario pediu no campo de
    preferencias - o item nao entra no cardapio. A restricao alimentar de
    quem tem alergia nao depende de o modelo ter obedecido.
    """
    resposta = {"refeicoes": [{"nome": "Café da manhã", "itens": [
        {"codigo_taco": LEITE["codigo_taco"], "gramas": 200},
        {"codigo_taco": 1, "gramas": 100},
    ]}]}
    refeicoes, descartados = ia.validar(resposta, CATALOGO)

    nomes = [item["alimento"] for item in refeicoes[0]["itens"]]
    assert "Leite integral" not in nomes
    assert len(descartados) == 1


def test_quantidade_absurda_e_descartada():
    resposta = {"refeicoes": [{"nome": "Almoço", "itens": [
        {"codigo_taco": 1, "gramas": 3},      # abaixo do minimo
        {"codigo_taco": 2, "gramas": 900},    # acima do maximo
        {"codigo_taco": 3, "gramas": 150},
    ]}]}
    refeicoes, descartados = ia.validar(resposta, CATALOGO)
    assert len(refeicoes[0]["itens"]) == 1
    assert len(descartados) == 2


def test_quantidade_nao_numerica_e_descartada():
    """O esquema pede NUMBER, mas o esquema e uma promessa, nao uma
    garantia: quem valida e quem recebe."""
    resposta = {"refeicoes": [{"nome": "Almoço", "itens": [
        {"codigo_taco": 1, "gramas": "cem gramas"},
    ]}]}
    refeicoes, descartados = ia.validar(resposta, CATALOGO)
    assert refeicoes == []
    assert descartados[0]["motivo"] == "quantidade inválida"


def test_refeicao_que_perdeu_todos_os_itens_nao_aparece_vazia():
    resposta = {"refeicoes": [
        {"nome": "Almoço", "itens": [{"codigo_taco": 9999, "gramas": 100}]},
        {"nome": "Jantar", "itens": [{"codigo_taco": 1, "gramas": 100}]},
    ]}
    refeicoes, _ = ia.validar(resposta, CATALOGO)
    assert len(refeicoes) == 1
    assert refeicoes[0]["nome"] == "Jantar"


def test_resposta_malformada_nao_derruba_o_sistema():
    for lixo in ({}, {"refeicoes": []}, {"refeicoes": [{"nome": "x"}]}):
        refeicoes, _ = ia.validar(lixo, CATALOGO)
        assert refeicoes == []


# ==========================================================================
# A ARITMETICA E DO SISTEMA
# ==========================================================================

def test_nenhum_numero_do_modelo_atravessa_a_validacao():
    """A regra que organiza o modulo inteiro: A IA ESCOLHE, O SISTEMA CALCULA.

    Aqui o modelo devolve valores nutricionais junto - inventados e errados
    de proposito. O sistema recalcula tudo a partir da TACO e os numeros do
    modelo simplesmente nao aparecem em lugar nenhum do resultado.
    """
    resposta = {"refeicoes": [{"nome": "Almoço", "itens": [
        {"codigo_taco": 1, "gramas": 200,
         "kcal": 9999, "proteina_g": 777, "nome": "Lagosta ao champanhe"},
    ]}]}
    refeicoes, _ = ia.validar(resposta, CATALOGO)
    item = refeicoes[0]["itens"][0]

    assert item["kcal"] == pytest.approx(200.0)       # 100 kcal/100g x 200 g
    assert item["proteina_g"] == pytest.approx(4.0)   # 2 g/100g x 200 g
    assert item["alimento"] == "Arroz cozido"


def test_totais_da_refeicao_sao_a_soma_dos_itens():
    refeicoes, _ = ia.validar(CARDAPIO_VALIDO, CATALOGO)
    for refeicao in refeicoes:
        soma = sum(item["kcal"] for item in refeicao["itens"])
        assert refeicao["totais"]["kcal"] == pytest.approx(soma)


# ==========================================================================
# FECHAMENTO DA META
# ==========================================================================

def test_ajuste_leva_o_total_para_perto_da_meta():
    refeicoes, _ = ia.validar(CARDAPIO_VALIDO, CATALOGO)
    refeicoes, fator = ia.ajustar_para_a_meta(refeicoes, 2000.0)

    total = ia.somar([i for r in refeicoes for i in r["itens"]])["kcal"]
    # O arredondamento de 5 em 5 g impede o valor exato; 3% e a folga.
    assert total == pytest.approx(2000.0, rel=0.03)


def test_ajuste_preserva_as_proporcoes_escolhidas_pela_ia():
    """O sistema muda o tamanho do prato, nao o prato.

    Se o ajuste mexesse item a item, ele estaria refazendo a composicao -
    justamente a parte que a IA fez bem e que o sistema nao sabe fazer.
    """
    refeicoes, _ = ia.validar(CARDAPIO_VALIDO, CATALOGO)
    antes = [i["gramas"] for r in refeicoes for i in r["itens"]]
    proporcao_antes = [g / antes[0] for g in antes]

    refeicoes, _ = ia.ajustar_para_a_meta(refeicoes, 2000.0)
    depois = [i["gramas"] for r in refeicoes for i in r["itens"]]
    proporcao_depois = [g / depois[0] for g in depois]

    for a, d in zip(proporcao_antes, proporcao_depois):
        assert d == pytest.approx(a, rel=0.10)


def test_quantidades_ajustadas_sao_pesaveis():
    """Ninguem pesa 87,3 g de arroz."""
    refeicoes, _ = ia.validar(CARDAPIO_VALIDO, CATALOGO)
    refeicoes, _ = ia.ajustar_para_a_meta(refeicoes, 2600.0)
    for refeicao in refeicoes:
        for item in refeicao["itens"]:
            assert item["gramas"] % 5 == pytest.approx(0.0)


def test_diferenca_pequena_nao_dispara_reescala():
    """Mexer em tudo para corrigir 2% seria trocar quantidades redondas por
    quantidades tortas em troca de nada."""
    refeicoes, _ = ia.validar(CARDAPIO_VALIDO, CATALOGO)
    total = ia.somar([i for r in refeicoes for i in r["itens"]])["kcal"]

    gramas_antes = [i["gramas"] for r in refeicoes for i in r["itens"]]
    refeicoes, fator = ia.ajustar_para_a_meta(refeicoes, total * 1.02)

    assert fator == 1.0
    assert [i["gramas"] for r in refeicoes for i in r["itens"]] == gramas_antes


def test_ajuste_nunca_reduz_um_item_abaixo_do_minimo():
    refeicoes, _ = ia.validar(CARDAPIO_VALIDO, CATALOGO)
    refeicoes, _ = ia.ajustar_para_a_meta(refeicoes, 300.0)
    for refeicao in refeicoes:
        for item in refeicao["itens"]:
            assert item["gramas"] >= ia.GRAMAS_MINIMO


def test_macros_acompanham_a_mudanca_de_quantidade():
    """Reescalar as gramas sem reescalar os macros produziria um cardapio
    que mente sobre si mesmo."""
    refeicoes, _ = ia.validar(CARDAPIO_VALIDO, CATALOGO)
    refeicoes, _ = ia.ajustar_para_a_meta(refeicoes, 3000.0)
    item = refeicoes[0]["itens"][0]
    assert item["kcal"] == pytest.approx(ARROZ["kcal"] * item["gramas"] / 100)


# ==========================================================================
# COMPARACAO COM AS METAS
# ==========================================================================

def test_comparacao_mostra_alvo_obtido_e_diferenca():
    totais = {"kcal": 1900.0, "proteina_g": 150.0, "gordura_g": 50.0,
              "carboidrato_g": 220.0, "fibra_g": 28.0}
    c = ia.comparar_com_as_metas(totais, PLANO)

    assert c["kcal"]["alvo"] == 2000.0
    assert c["kcal"]["diferenca"] == pytest.approx(-100.0)
    assert c["kcal"]["percentual"] == pytest.approx(-5.0)
    assert c["proteina_g"]["diferenca"] == pytest.approx(0.0)


def test_comparacao_com_meta_zero_nao_divide_por_zero():
    plano = dict(PLANO, fibras_g=0.0)
    c = ia.comparar_com_as_metas({"fibra_g": 10.0}, plano)
    assert c["fibra_g"]["percentual"] == 0.0


# ==========================================================================
# ORQUESTRACAO PONTA A PONTA (sem rede)
# ==========================================================================

def test_gerar_cardapio_devolve_tudo_o_que_a_tela_precisa():
    r = ia.gerar_cardapio(PLANO, 2, CATALOGO,
                          chamar=resposta_fixa(CARDAPIO_VALIDO))

    assert len(r["refeicoes"]) == 2
    assert r["totais"]["kcal"] == pytest.approx(2000.0, rel=0.03)
    assert r["descartados"] == []
    assert "comparacao" in r and "fator_de_ajuste" in r


def test_gerar_cardapio_nao_toca_a_rede_nos_testes():
    """Se a injecao de 'chamar' falhasse, este teste tentaria a API real e
    quebraria - que e exatamente o aviso que se quer."""
    chamadas = []

    def espiao(prompt):
        chamadas.append(prompt)
        return CARDAPIO_VALIDO

    ia.gerar_cardapio(PLANO, 3, CATALOGO, chamar=espiao)
    assert len(chamadas) == 1
    assert "CATÁLOGO PERMITIDO" in chamadas[0]


def test_descartes_sao_devolvidos_para_o_capitulo_4():
    """O numero de descartes e dado de avaliacao, nao detalhe interno: e ele
    que mede o quanto o modelo respeita o catalogo."""
    resposta = {"refeicoes": [{"nome": "Almoço", "itens": [
        {"codigo_taco": 1, "gramas": 200},
        {"codigo_taco": 8888, "gramas": 100},
    ]}]}
    r = ia.gerar_cardapio(PLANO, 3, CATALOGO, chamar=resposta_fixa(resposta))
    assert len(r["descartados"]) == 1


def test_cardapio_inteiramente_invalido_e_recusado():
    """Melhor um erro visivel do que uma tela vazia que parece um cardapio."""
    resposta = {"refeicoes": [{"nome": "Almoço", "itens": [
        {"codigo_taco": 7777, "gramas": 100},
    ]}]}
    with pytest.raises(ValueError):
        ia.gerar_cardapio(PLANO, 3, CATALOGO, chamar=resposta_fixa(resposta))


def test_catalogo_vazio_e_recusado_antes_de_gastar_cota():
    """Catalogo vazio significa restricoes que nao sobraram nada. Chamar a
    API nesse estado gastaria cota para receber um cardapio impossivel."""
    with pytest.raises(ValueError):
        ia.gerar_cardapio(PLANO, 3, [], chamar=resposta_fixa(CARDAPIO_VALIDO))


def test_todo_item_do_resultado_veio_do_catalogo():
    """Varredura final: qualquer caminho do modulo que deixasse passar um
    codigo de fora cairia aqui."""
    permitidos = {a["codigo_taco"] for a in CATALOGO}
    resposta = {"refeicoes": [{"nome": "Almoço", "itens": [
        {"codigo_taco": c, "gramas": 100} for c in (1, 2, 3, 4, 99, -1)
    ]}]}
    r = ia.gerar_cardapio(PLANO, 3, CATALOGO, chamar=resposta_fixa(resposta))
    for refeicao in r["refeicoes"]:
        for item in refeicao["itens"]:
            assert item["codigo_taco"] in permitidos
