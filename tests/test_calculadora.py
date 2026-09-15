"""
test_calculadora.py - Testes automatizados do nucleo de calculo.

Cada teste compara o resultado das funcoes com valores calculados a mao a
partir das formulas descritas no Capitulo 1 do trabalho. Nenhum teste
depende do Flask, do banco de dados ou da API de IA: o nucleo e testado
isoladamente.

Perfil de referencia usado na maioria dos testes:
    peso 80 kg | altura 175 cm | 30 anos | masculino | BF 30% | moderado

Execucao:
    pytest -v
"""

import pytest

import calculadora as calc


# ==========================================================================
# COMPOSICAO CORPORAL
# ==========================================================================

def test_sistema_nao_expoe_calculo_de_imc():
    """Decisao de projeto: o IMC foi removido do sistema.

    Este teste guarda essa decisao. Se alguem reintroduzir o IMC no futuro,
    o teste falha e obriga a revisar o motivo documentado no cabecalho da
    secao 2 de calculadora.py - em resumo, a metrica e cega a composicao
    corporal e sua magnitude parecida com a do BF convidava o usuario a
    confundir as duas grandezas.
    """
    assert not hasattr(calc, "calcular_imc")
    assert not hasattr(calc, "classificar_imc")


def test_massa_magra_e_gorda_somam_o_peso_total():
    """Propriedade que deve valer para qualquer entrada: as duas partes
    reconstroem o todo."""
    magra = calc.calcular_massa_magra(80, 30)
    gorda = calc.calcular_massa_gorda(80, 30)
    assert magra == pytest.approx(56.0)
    assert gorda == pytest.approx(24.0)
    assert magra + gorda == pytest.approx(80.0)


# ==========================================================================
# TAXA METABOLICA BASAL
# ==========================================================================

def test_katch_mcardle():
    # 370 + (21.6 x 56) = 370 + 1209.6 = 1579.6
    assert calc.tmb_katch_mcardle(56.0) == pytest.approx(1579.6)


def test_mifflin_masculino():
    # (10x80) + (6.25x175) - (5x30) + 5 = 800 + 1093.75 - 150 + 5
    assert calc.tmb_mifflin_st_jeor(80, 175, 30, "M") == pytest.approx(1748.75)


def test_mifflin_feminino():
    # (10x80) + (6.25x175) - (5x30) - 161 = 800 + 1093.75 - 150 - 161
    assert calc.tmb_mifflin_st_jeor(80, 175, 30, "F") == pytest.approx(1582.75)


def test_roteador_usa_katch_quando_ha_bf():
    tmb, equacao = calc.calcular_tmb(80, 175, 30, "M", bf=30)
    assert equacao == "Katch-McArdle"
    assert tmb == pytest.approx(1579.6)


def test_roteador_usa_mifflin_quando_nao_ha_bf():
    tmb, equacao = calc.calcular_tmb(80, 175, 30, "M", bf=None)
    assert equacao == "Mifflin-St Jeor"
    assert tmb == pytest.approx(1748.75)


def test_altura_e_sempre_em_centimetros():
    """Regressao da confusao de unidade.

    Passar a altura em metros (1.75) onde se espera centimetros (175) nao
    gera excecao - produz silenciosamente uma TMB absurda. Este teste fixa
    a convencao do modulo: as duas chamadas tem de divergir de forma
    grosseira, e a versao em metros fica muito abaixo de qualquer TMB
    fisiologicamente plausivel para um adulto.
    """
    em_cm, _ = calc.calcular_tmb(80, 175, 30, "M")
    em_metros, _ = calc.calcular_tmb(80, 1.75, 30, "M")
    assert em_cm > 1500
    assert em_metros < 1000


# ==========================================================================
# GASTO ENERGETICO E META
# ==========================================================================

def test_get_com_fator_moderado():
    # 1579.6 x 1.55 = 2448.38
    assert calc.calcular_get(1579.6, "moderado") == pytest.approx(2448.38)


def test_ajuste_zero_nao_altera_o_get():
    get = 2448.38
    assert calc.calcular_meta_calorica(get, 0.0) == pytest.approx(get)


def test_percentual_negativo_e_deficit_positivo_e_superavit():
    """Um unico parametro assinado cobre os tres objetivos, o que e o que
    permite o controle deslizante continuo."""
    get = 2000.0
    assert calc.calcular_meta_calorica(get, -20.0) == pytest.approx(1600.0)
    assert calc.calcular_meta_calorica(get, +10.0) == pytest.approx(2200.0)


@pytest.mark.parametrize("objetivo", ["perder", "manter", "ganhar"])
def test_padroes_trazem_valor_inicial_e_limites(objetivo):
    """A interface monta os controles a partir desta estrutura: o padrao
    posiciona o cursor, a faixa define ate onde ele vai. Padrao fora da
    faixa produziria um controle que abre numa posicao impossivel."""
    padroes = calc.padroes_do_objetivo(objetivo, "moderado")
    assert set(padroes) == {"ajuste_calorico", "proteina", "gordura", "agua", "fibras"}
    for nome, p in padroes.items():
        minimo, maximo = p["faixa"]
        assert minimo <= p["padrao"] <= maximo, f"{nome} abre fora da faixa"


def test_direcao_do_ajuste_corresponde_ao_objetivo():
    assert calc.padroes_do_objetivo("perder", "moderado")["ajuste_calorico"]["padrao"] < 0
    assert calc.padroes_do_objetivo("manter", "moderado")["ajuste_calorico"]["padrao"] == 0
    assert calc.padroes_do_objetivo("ganhar", "moderado")["ajuste_calorico"]["padrao"] > 0


@pytest.mark.parametrize("objetivo", ["perder", "manter", "ganhar"])
def test_controle_calorico_e_exibido_sempre_crescente(objetivo):
    """Um deslizante cresce da esquerda para a direita. Se a faixa visivel do
    deficit fosse (-25, -10), arrastar para a direita significaria comer MAIS -
    o oposto do que se espera de um controle de intensidade. A faixa exibida
    e sempre positiva e ascendente."""
    cal = calc.padroes_do_objetivo(objetivo, "moderado")["ajuste_calorico"]
    minimo, maximo = cal["faixa_visivel"]
    assert 0 <= minimo <= maximo
    assert minimo <= cal["padrao_visivel"] <= maximo


def test_sinal_do_ajuste_volta_no_servidor():
    """A interface manda intensidade positiva; o sinal e do objetivo."""
    assert calc.ajuste_assinado("perder", 20) == -20.0
    assert calc.ajuste_assinado("ganhar", 10) == +10.0
    assert calc.ajuste_assinado("manter", 99) == 0.0
    # Mesmo que a interface envie negativo por engano, o sinal e corrigido.
    assert calc.ajuste_assinado("perder", -20) == -20.0


def test_deficit_maximo_respeita_o_limite_seguro():
    """A literatura recomenda perda de ate ~0,5% do peso por semana para
    preservar massa magra. O teto anterior de 35% era agressivo demais."""
    minimo, maximo = calc.OBJETIVOS["perder"]["ajuste_calorico"]["faixa"]
    assert min(minimo, maximo) >= -25.0


@pytest.mark.parametrize("objetivo", ["perder", "manter", "ganhar"])
def test_faixa_de_proteina_segue_a_literatura(objetivo):
    """1,6 a 2,4 g/kg: plato identificado por Morton et al. (2018), confirmado
    por Nunes et al. (2022) e pelo consenso de entidades internacionais."""
    faixa = calc.OBJETIVOS[objetivo]["proteina"]["faixa"]
    assert faixa == (1.6, 2.4)


# ==========================================================================
# MACRONUTRIENTES
# ==========================================================================

def test_macros_do_perfil_de_referencia():
    macros = calc.calcular_macros(peso=80, meta_calorica=1897.4945, objetivo="perder")
    assert macros["proteina_g"] == pytest.approx(176.0)   # 80 x 2.2
    assert macros["gordura_g"] == pytest.approx(64.0)     # 80 x 0.8
    # Sobra: 1897,4945 - (176x4) - (64x9) = 617,4945 kcal -> /4
    assert macros["carboidrato_g"] == pytest.approx(154.3736, abs=1e-3)
    assert macros["aviso"] is None


def test_soma_das_calorias_dos_macros_bate_com_a_meta():
    """Invariante central do particionamento: nenhuma caloria pode ser
    criada nem perdida na divisao."""
    meta = 2000.0
    m = calc.calcular_macros(peso=70, meta_calorica=meta, objetivo="manter")
    total = m["kcal_proteina"] + m["kcal_gordura"] + m["kcal_carboidrato"]
    assert total == pytest.approx(meta)


def test_fatores_personalizados_sobrescrevem_o_padrao():
    m = calc.calcular_macros(peso=80, meta_calorica=2500, objetivo="perder",
                             fator_proteina=2.4, fator_gordura=1.0)
    assert m["proteina_g"] == pytest.approx(192.0)   # 80 x 2.4
    assert m["gordura_g"] == pytest.approx(80.0)     # 80 x 1.0


def test_carboidrato_nunca_fica_negativo():
    """Meta calorica baixa demais para os fatores escolhidos.

    Proteina e gordura sozinhas ja consomem mais calorias do que a meta.
    O prototipo anterior devolveria um numero negativo de gramas; aqui o
    valor e zerado e um aviso e emitido.
    """
    m = calc.calcular_macros(peso=100, meta_calorica=800, objetivo="perder")
    assert m["carboidrato_g"] == 0
    assert m["aviso"] is not None


# ==========================================================================
# HIDRATACAO E FIBRAS
# ==========================================================================

def test_agua_varia_com_o_nivel_de_atividade():
    assert calc.calcular_agua(80, "moderado") == pytest.approx(3200.0)   # 80 x 40
    assert calc.calcular_agua(80, "sedentario") < calc.calcular_agua(80, "muito_intenso")


def test_agua_aceita_fator_personalizado():
    assert calc.calcular_agua(80, "moderado", fator=45.0) == pytest.approx(3600.0)


def test_fibras_seguem_a_energia_e_nao_o_peso():
    """A recomendacao oficial e de 14 g por 1000 kcal (Institute of Medicine),
    e nao gramas por quilo.

    Este teste fixa a mudanca de base: a meta de fibra acompanha a meta
    calorica. Uma dieta de 2000 kcal pede 28 g independentemente de a pessoa
    pesar 60 ou 90 kg.
    """
    assert calc.calcular_fibras(2000) == pytest.approx(28.0)
    assert calc.calcular_fibras(1000) == pytest.approx(14.0)
    assert calc.calcular_fibras(2500, fator=20) == pytest.approx(50.0)


def test_fibras_de_2000_kcal_batem_com_a_faixa_oficial():
    """25 g/dia para mulheres e 38 g/dia para homens sao os valores de
    referencia; uma dieta tipica precisa cair perto dessa faixa."""
    assert 25 <= calc.calcular_fibras(2200) <= 38


# ==========================================================================
# ORQUESTRACAO
# ==========================================================================

def test_plano_completo_reproduz_os_dados_do_prototipo():
    """O prototipo original, com peso 80 e BF 30% no nivel moderado,
    registrou TMB 1579.6 e GET 2448.38 no banco. O novo nucleo precisa
    reproduzir exatamente os mesmos numeros, garantindo que a reescrita
    nao alterou a matematica ja validada."""
    plano = calc.montar_plano(
        peso=80, altura_cm=175, idade=30, sexo="M",
        nivel_atividade="moderado", objetivo="perder", bf=30,
    )
    assert plano["tmb"] == pytest.approx(1579.6)
    assert plano["get"] == pytest.approx(2448.38)
    assert plano["equacao_utilizada"] == "Katch-McArdle"


def test_plano_sem_bf_omite_composicao_corporal():
    plano = calc.montar_plano(
        peso=80, altura_cm=175, idade=30, sexo="M",
        nivel_atividade="moderado", objetivo="manter", bf=None,
    )
    assert plano["massa_magra"] is None
    assert plano["massa_gorda"] is None
    assert plano["equacao_utilizada"] == "Mifflin-St Jeor"
    assert "imc" not in plano


# ==========================================================================
# MEDICAO DA PERSONALIZACAO
#
# A hipotese do trabalho afirma que permitir ajuste dinamico das metas
# confere maior autonomia ao usuario. Para verificar isso com dados, o
# sistema precisa saber distinguir "aceitou a recomendacao" de "alterou".
# ==========================================================================

def test_plano_sem_ajustes_nao_registra_alteracao():
    plano = calc.montar_plano(peso=80, altura_cm=175, idade=30, sexo="M",
                              nivel_atividade="moderado", objetivo="perder")
    assert calc.comparar_com_padrao(plano) == {}


def test_plano_com_ajustes_registra_padrao_e_escolhido():
    plano = calc.montar_plano(peso=80, altura_cm=175, idade=30, sexo="M",
                              nivel_atividade="moderado", objetivo="perder",
                              fator_proteina=2.4, ajuste_calorico=-15.0)
    alteracoes = calc.comparar_com_padrao(plano)
    assert set(alteracoes) == {"proteina", "ajuste_calorico"}
    assert alteracoes["proteina"] == {"padrao": 2.2, "escolhido": 2.4}
    assert alteracoes["ajuste_calorico"]["escolhido"] == -15.0


def test_plano_devolve_os_padroes_para_a_interface():
    """O plano carrega os padroes usados, de modo que a tela de resultado
    consiga redesenhar os controles na posicao correta sem recalcular."""
    plano = calc.montar_plano(peso=80, altura_cm=175, idade=30, sexo="M",
                              nivel_atividade="intenso", objetivo="ganhar")
    assert plano["padroes"]["agua"]["padrao"] == 45.0      # nivel intenso
    assert plano["fator_atividade"] == pytest.approx(1.725)
