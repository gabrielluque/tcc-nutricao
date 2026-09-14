"""
calculadora.py - Nucleo de calculo nutricional do sistema.

Este modulo contem exclusivamente FUNCOES PURAS: recebem numeros e devolvem
numeros. Nao importa Flask, nao abre conexao com banco de dados e nao faz
requisicoes de rede.

Essa separacao e deliberada. Ela permite:

  1. Testar toda a regra de negocio de forma automatizada e isolada, sem
     precisar subir o servidor web (ver tests/test_calculadora.py).
  2. Auditar as formulas metabolicas sem precisar entender a aplicacao web.
  3. Reaproveitar o nucleo caso o sistema ganhe outra interface no futuro.

--------------------------------------------------------------------------
CONVENCOES DE UNIDADE  (fixadas para eliminar ambiguidade)
--------------------------------------------------------------------------
    peso .............. quilogramas (kg)
    altura_cm ......... centimetros, SEMPRE. A conversao para metros e interna.
    bf ................ percentual de 0 a 100. O valor 30.0 significa 30%.
                        Nunca decimal (0.30). Convencao unica em todo o
                        sistema, inclusive no banco de dados.
    idade ............. anos completos
    sexo .............. "M" ou "F"
    energia ........... quilocalorias (kcal)
    macronutrientes ... gramas (g)
    agua .............. mililitros (ml)
    ajuste_calorico ... percentual assinado. -22.5 e deficit de 22,5%;
                        +10.0 e superavit de 10%; 0 e manutencao.

--------------------------------------------------------------------------
PADRAO E FAIXA
--------------------------------------------------------------------------
Todo parametro ajustavel pelo usuario e declarado como um par
{"padrao": X, "faixa": (minimo, maximo)}.

O padrao posiciona o controle deslizante quando a tela abre; a faixa define
os limites de onde ele pode ir. A interface le essas estruturas diretamente,
de modo que alterar uma recomendacao nutricional e alterar uma linha deste
arquivo - nunca o HTML.

--------------------------------------------------------------------------
FONTES DAS FORMULAS
--------------------------------------------------------------------------
    Mifflin-St Jeor .................... MIFFLIN, M. D. et al. (1990)
    Katch-McArdle ...................... KATCH, F. I.; McARDLE, W. D.
    Harris-Benedict .................... HARRIS, J. A.; BENEDICT, F. G. (1919)
    Fatores de macronutrientes ......... Tabela 1 do trabalho
    Fatores hidricos ................... Tabela 2 do trabalho
"""

# ==========================================================================
# 1. CONSTANTES
# ==========================================================================

KCAL_POR_GRAMA = {"proteina": 4, "carboidrato": 4, "gordura": 9}

# Fatores multiplicadores do nivel de atividade fisica (secao 1.3).
FATORES_ATIVIDADE = {
    "sedentario":    {"fator": 1.200, "rotulo": "Sedentário (pouca ou nenhuma atividade)"},
    "leve":          {"fator": 1.375, "rotulo": "Leve (treina 1 a 2x por semana)"},
    "moderado":      {"fator": 1.550, "rotulo": "Moderado (treina 3 a 4x por semana)"},
    "intenso":       {"fator": 1.725, "rotulo": "Intenso (treina 5 a 6x por semana)"},
    "muito_intenso": {"fator": 1.900, "rotulo": "Muito intenso (2x por dia ou trabalho pesado)"},
}

# Fator hidrico em ml por kg de peso (Tabela 2). O padrao e o ponto medio
# da faixa indicada na tabela.
FATORES_HIDRICOS = {
    "sedentario":    {"padrao": 32.5, "faixa": (30.0, 35.0)},
    "leve":          {"padrao": 40.0, "faixa": (35.0, 45.0)},
    "moderado":      {"padrao": 40.0, "faixa": (35.0, 45.0)},
    "intenso":       {"padrao": 50.0, "faixa": (45.0, 55.0)},
    "muito_intenso": {"padrao": 62.5, "faixa": (55.0, 70.0)},
}

# Fibras em gramas por kg de peso (secao 1.5).
FIBRAS = {"padrao": 0.4, "faixa": (0.3, 0.5)}

# Parametros por objetivo (Tabela 1).
#
# "ajuste_calorico" e o percentual aplicado sobre o GET. Os padroes usam o
# ponto medio das faixas descritas no trabalho: o deficit moderado de
# "20% a 25%" vira -22,5%. As faixas cobrem do conservador ao agressivo,
# permitindo que o usuario arraste livremente dentro do intervalo seguro.
OBJETIVOS = {
    "perder": {
        "rotulo": "Perder gordura",
        "descricao": "Comer um pouco menos do que você gasta, preservando músculo.",
        "ajuste_calorico": {"padrao": -22.5, "faixa": (-35.0, -10.0)},
        "proteina":        {"padrao": 2.2,   "faixa": (2.0, 2.4)},
        "gordura":         {"padrao": 0.9,   "faixa": (0.8, 1.0)},
    },
    "manter": {
        "rotulo": "Manter o peso",
        "descricao": "Comer exatamente o que você gasta.",
        "ajuste_calorico": {"padrao": 0.0,   "faixa": (-5.0, 5.0)},
        "proteina":        {"padrao": 2.0,   "faixa": (1.8, 2.2)},
        "gordura":         {"padrao": 1.0,   "faixa": (0.9, 1.1)},
    },
    "ganhar": {
        "rotulo": "Ganhar massa muscular",
        "descricao": "Comer acima do seu gasto para dar material ao músculo.",
        "ajuste_calorico": {"padrao": 10.0,  "faixa": (5.0, 25.0)},
        "proteina":        {"padrao": 1.8,   "faixa": (1.6, 2.0)},
        "gordura":         {"padrao": 1.1,   "faixa": (1.0, 1.2)},
    },
}


def padroes_do_objetivo(objetivo, nivel_atividade):
    """
    Devolve todos os parametros ajustaveis com padrao e faixa.

    E a unica fonte que a interface consulta para montar os controles
    deslizantes. Retornar padrao e faixa juntos garante que o valor inicial
    do controle e os seus limites nunca fiquem fora de sincronia.
    """
    parametros = OBJETIVOS[objetivo]
    return {
        "ajuste_calorico": dict(parametros["ajuste_calorico"]),
        "proteina":        dict(parametros["proteina"]),
        "gordura":         dict(parametros["gordura"]),
        "agua":            dict(FATORES_HIDRICOS[nivel_atividade]),
        "fibras":          dict(FIBRAS),
    }


# ==========================================================================
# 2. COMPOSICAO CORPORAL
#
# DECISAO DE PROJETO: o IMC NAO e calculado por este sistema.
#
# O Indice de Massa Corporal e uma razao entre peso e altura que nao
# distingue tecido muscular de tecido adiposo. Duas pessoas de mesma altura
# e mesmo peso recebem o mesmo IMC ainda que uma tenha o dobro de massa
# magra da outra. Para um sistema cujo objetivo e o particionamento de
# macronutrientes, essa cegueira a composicao corporal o torna incapaz de
# informar qualquer decisao de calculo.
#
# Havia ainda um risco concreto de erro: IMC e percentual de gordura sao
# numeros de magnitude parecida (por volta de 25 a 30) e grandezas
# completamente diferentes. Exibir os dois lado a lado convida o usuario a
# digitar um no lugar do outro - erro que existia no prototipo anterior
# deste trabalho.
#
# A rota adotada resolve o problema na origem: sem BF, o sistema usa
# Mifflin-St Jeor, que nao depende de composicao corporal alguma.
# ==========================================================================

def calcular_massa_magra(peso, bf):
    """Massa livre de gordura, em kg.  =  peso x (1 - BF/100)"""
    return peso * (1 - bf / 100)


def calcular_massa_gorda(peso, bf):
    """Massa de tecido adiposo, em kg.  =  peso x (BF/100)"""
    return peso * (bf / 100)


# ==========================================================================
# 3. TAXA METABOLICA BASAL
# ==========================================================================

def tmb_mifflin_st_jeor(peso, altura_cm, idade, sexo):
    """
    Mifflin-St Jeor (1990). Rota PADRAO do sistema.

        Masculino: (10 x peso) + (6,25 x altura_cm) - (5 x idade) + 5
        Feminino:  (10 x peso) + (6,25 x altura_cm) - (5 x idade) - 161

    Adotada como padrao por apresentar menor margem de erro que
    Harris-Benedict para a populacao contemporanea, e por nao exigir o
    percentual de gordura, que a maioria dos usuarios desconhece.
    """
    base = (10 * peso) + (6.25 * altura_cm) - (5 * idade)
    return base + 5 if sexo.upper() == "M" else base - 161


def tmb_katch_mcardle(massa_magra):
    """
    Katch-McArdle. Rota AVANCADA, usada quando o BF e conhecido.

        TMB = 370 + (21,6 x massa magra)

    Ignora o peso total e considera apenas a massa magra, porque o tecido
    muscular e metabolicamente mais ativo que o adiposo.
    """
    return 370 + (21.6 * massa_magra)


def tmb_harris_benedict(peso, altura_cm, idade, sexo):
    """
    Harris-Benedict (1919). Implementada para comparacao no Capitulo 4.

    Nao e rota padrao por ser a mais antiga das tres e divergir mais da
    populacao atual. Manter as tres disponiveis permite comparar os
    resultados no trabalho.
    """
    if sexo.upper() == "M":
        return 66.47 + (13.75 * peso) + (5.003 * altura_cm) - (6.755 * idade)
    return 655.1 + (9.563 * peso) + (1.850 * altura_cm) - (4.676 * idade)


def calcular_tmb(peso, altura_cm, idade, sexo, bf=None):
    """
    Roteirizacao metabolica: escolhe a equacao conforme os dados disponiveis.

        BF informado  ->  Katch-McArdle
        BF ausente    ->  Mifflin-St Jeor

    Devolve (tmb, nome_da_equacao). O nome acompanha o resultado para que a
    interface e o PDF possam informar qual metodo foi aplicado.
    """
    if bf is not None:
        return tmb_katch_mcardle(calcular_massa_magra(peso, bf)), "Katch-McArdle"
    return tmb_mifflin_st_jeor(peso, altura_cm, idade, sexo), "Mifflin-St Jeor"


# ==========================================================================
# 4. GASTO ENERGETICO E META CALORICA
# ==========================================================================

def calcular_get(tmb, nivel_atividade):
    """Gasto Energetico Total.  =  TMB x fator de atividade"""
    return tmb * FATORES_ATIVIDADE[nivel_atividade]["fator"]


def calcular_meta_calorica(get, ajuste_percentual):
    """
    Aplica o ajuste percentual sobre o GET.

        Meta = GET x (1 + ajuste/100)

    O percentual e assinado: negativo para deficit, positivo para superavit,
    zero para manutencao. Um unico parametro continuo cobre os tres
    objetivos, o que permite o controle deslizante livre e elimina a
    convencao pouco intuitiva do prototipo anterior, onde ganhar peso exigia
    digitar um deficit negativo.
    """
    return get * (1 + ajuste_percentual / 100)


# ==========================================================================
# 5. PARTICIONAMENTO DE MACRONUTRIENTES
# ==========================================================================

def calcular_macros(peso, meta_calorica, objetivo,
                    fator_proteina=None, fator_gordura=None):
    """
    Distribui a meta calorica entre proteina, gordura e carboidrato.

    A ORDEM DE EXECUCAO E ESTRITA e reproduz a secao 1.4 do trabalho:

        1. Proteina e gordura sao definidas em gramas (peso x fator).
        2. Convertidas em calorias e subtraidas da meta.
        3. O que sobra vira carboidrato (dividido por 4).

    O carboidrato e sempre o residuo porque proteina e gordura tem
    necessidade minima definida biologicamente, enquanto o carboidrato atua
    como fonte energetica ajustavel.

    Se a meta calorica nao comportar os fatores escolhidos, o carboidrato
    resultaria negativo - situacao fisicamente impossivel. A funcao zera o
    valor e preenche "aviso", em vez de devolver um numero sem sentido.
    """
    parametros = OBJETIVOS[objetivo]
    if fator_proteina is None:
        fator_proteina = parametros["proteina"]["padrao"]
    if fator_gordura is None:
        fator_gordura = parametros["gordura"]["padrao"]

    proteina_g = peso * fator_proteina
    gordura_g = peso * fator_gordura

    kcal_proteina = proteina_g * KCAL_POR_GRAMA["proteina"]
    kcal_gordura = gordura_g * KCAL_POR_GRAMA["gordura"]
    kcal_restante = meta_calorica - (kcal_proteina + kcal_gordura)

    aviso = None
    if kcal_restante < 0:
        aviso = ("A meta calórica é insuficiente para os fatores de proteína e "
                 "gordura escolhidos. Reduza os fatores ou aumente a meta.")
        kcal_restante = 0

    return {
        "proteina_g": proteina_g,
        "gordura_g": gordura_g,
        "carboidrato_g": kcal_restante / KCAL_POR_GRAMA["carboidrato"],
        "kcal_proteina": kcal_proteina,
        "kcal_gordura": kcal_gordura,
        "kcal_carboidrato": kcal_restante,
        "fator_proteina": fator_proteina,
        "fator_gordura": fator_gordura,
        "aviso": aviso,
    }


# ==========================================================================
# 6. HIDRATACAO E FIBRAS
# ==========================================================================

def calcular_agua(peso, nivel_atividade, fator=None):
    """
    Meta diaria de agua em ml.  =  peso x fator hidrico

    Substitui a recomendacao estatica de "2 litros por dia" por um calculo
    que cruza massa corporal e esforco fisico. O fator pode ser sobrescrito
    pelo usuario dentro da faixa do seu nivel de atividade.
    """
    if fator is None:
        fator = FATORES_HIDRICOS[nivel_atividade]["padrao"]
    return peso * fator


def calcular_fibras(peso, fator=None):
    """Meta diaria de fibras em gramas.  =  peso x fator (padrao 0,4)"""
    if fator is None:
        fator = FIBRAS["padrao"]
    return peso * fator


# ==========================================================================
# 7. ORQUESTRACAO
# ==========================================================================

def montar_plano(peso, altura_cm, idade, sexo, nivel_atividade, objetivo,
                 bf=None, ajuste_calorico=None, fator_proteina=None,
                 fator_gordura=None, fator_agua=None, fator_fibras=None):
    """
    Executa a esteira completa de calculo e devolve o plano nutricional.

    Fronteira do modulo: o app.py chama apenas esta funcao. Toda a
    matematica permanece aqui dentro.

    Qualquer parametro ajustavel deixado como None assume o padrao do
    objetivo ou do nivel de atividade. O resultado devolve lado a lado o
    valor PADRAO e o valor USADO de cada parametro, o que permite registrar
    no banco exatamente o que o usuario alterou - dado que sustenta a
    analise de personalizacao do Capitulo 4.
    """
    padroes = padroes_do_objetivo(objetivo, nivel_atividade)

    if ajuste_calorico is None:
        ajuste_calorico = padroes["ajuste_calorico"]["padrao"]
    if fator_agua is None:
        fator_agua = padroes["agua"]["padrao"]
    if fator_fibras is None:
        fator_fibras = padroes["fibras"]["padrao"]

    tmb, equacao = calcular_tmb(peso, altura_cm, idade, sexo, bf)
    get = calcular_get(tmb, nivel_atividade)
    meta_calorica = calcular_meta_calorica(get, ajuste_calorico)
    macros = calcular_macros(peso, meta_calorica, objetivo,
                             fator_proteina, fator_gordura)

    return {
        "massa_magra": calcular_massa_magra(peso, bf) if bf is not None else None,
        "massa_gorda": calcular_massa_gorda(peso, bf) if bf is not None else None,
        "tmb": tmb,
        "equacao_utilizada": equacao,
        "get": get,
        "fator_atividade": FATORES_ATIVIDADE[nivel_atividade]["fator"],
        "meta_calorica": meta_calorica,
        "agua_ml": calcular_agua(peso, nivel_atividade, fator_agua),
        "fibras_g": calcular_fibras(peso, fator_fibras),
        "fator_agua": fator_agua,
        "fator_fibras": fator_fibras,
        "ajuste_calorico": ajuste_calorico,
        "padroes": padroes,
        **macros,
    }


def comparar_com_padrao(plano):
    """
    Lista os parametros que o usuario alterou em relacao ao padrao sugerido.

    Devolve, para cada parametro modificado, o valor recomendado e o valor
    escolhido. E a materia-prima da analise de personalizacao: permite
    responder, com dados, se as pessoas de fato usam a liberdade de ajuste
    que a hipotese do trabalho pressupoe.
    """
    padroes = plano["padroes"]
    comparacoes = {
        "ajuste_calorico": plano["ajuste_calorico"],
        "proteina":        plano["fator_proteina"],
        "gordura":         plano["fator_gordura"],
        "agua":            plano["fator_agua"],
        "fibras":          plano["fator_fibras"],
    }
    return {
        nome: {"padrao": padroes[nome]["padrao"], "escolhido": usado}
        for nome, usado in comparacoes.items()
        if abs(usado - padroes[nome]["padrao"]) > 1e-9
    }
