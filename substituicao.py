"""
substituicao.py - Motor de substituicao de alimentos.

Responde a uma pergunta so: "nao quero comer isto, o que como no lugar?"

Como calculadora.py, este modulo contem FUNCOES PURAS. Recebe o alimento, a
quantidade e uma lista de alimentos disponiveis; devolve alternativas. Nao
abre banco, nao importa Flask e nao chama IA.

--------------------------------------------------------------------------
POR QUE ISTO NAO E TRABALHO DA IA
--------------------------------------------------------------------------
Pedir a um modelo de linguagem "troque o arroz por algo equivalente" produz
uma resposta plausivel, nao uma resposta correta: o modelo estima, e a
estimativa as vezes erra por um fator de tres. Substituicao e aritmetica
sobre a tabela TACO, e aritmetica nao se delega a um componente
probabilistico.

A divisao de trabalho do sistema fica assim:

    banco.py          decide o que PODE ser comido (restricoes, em SQL)
    substituicao.py   decide o que EQUIVALE (aritmetica, aqui)
    integracao_ia.py  decide o que fica GOSTOSO junto (linguagem, na IA)

--------------------------------------------------------------------------
AS QUATRO DECISOES DESTE ARQUIVO
--------------------------------------------------------------------------

1. A EQUIVALENCIA E POR ENERGIA, NAO POR PESO

   Trocar 100 g de arroz por 100 g de azeite multiplicaria as calorias da
   refeicao por sete. A quantidade do substituto e recalculada para entregar
   a MESMA energia da porcao original.

2. O RANKING E PELO PERFIL DE MACRONUTRIENTES

   Duas porcoes podem ter a mesma energia e significados opostos: 150 kcal
   de peito de frango e 150 kcal de acucar. Por isso os candidatos sao
   ordenados pela semelhanca do PERFIL - quanto da energia vem de proteina,
   de gordura e de carboidrato. Peito de frango substitui patinho antes de
   substituir batata, e isso cai por si, sem regra escrita a mao.

3. PORCOES IMPOSSIVEIS SAO DESCARTADAS

   Alface tem 10 kcal por 100 g. Para igualar um prato de arroz seriam
   quase 2 kg de alface - aritmeticamente correto, gastronomicamente
   absurdo. Substitutos que exijam menos de 20 g ou mais de 400 g saem da
   lista. E um limite de bom senso, e esta aqui declarado justamente para
   poder ser discutido.

4. O CATALOGO JA CHEGA FILTRADO

   Quem monta a lista de candidatos e banco.buscar_catalogo, que ja removeu
   os alimentos incompativeis com as restricoes declaradas. Este modulo
   nunca reintroduz um alergenico porque nunca ve um. A propriedade e
   testada em tests/test_substituicao.py.

--------------------------------------------------------------------------
LIMITACAO CONHECIDA, para o Capitulo 4
--------------------------------------------------------------------------
A semelhanca considera apenas os tres macronutrientes. Dois alimentos com
perfil identico podem diferir em micronutrientes, em indice glicemico e em
saciedade - e a TACO tem essas colunas, que o sistema nao usa. Uma
substituicao correta em energia e macros nao e, portanto, uma substituicao
nutricionalmente equivalente em todos os sentidos. O sistema e um apoio, e
esta e uma das fronteiras em que isso aparece.
"""

KCAL_POR_GRAMA = {"proteina": 4, "gordura": 9, "carboidrato": 4}

# Faixa de porcao considerada realista para um unico alimento em uma
# refeicao. Ver decisao 3 no cabecalho.
PORCAO_MINIMA = 20.0
PORCAO_MAXIMA = 400.0

# Abaixo deste valor o alimento nao serve de base para equivalencia: um
# alimento quase sem energia exigiria uma porcao gigantesca para igualar
# qualquer outra coisa. Chas e refrigerantes zero caem aqui.
KCAL_MINIMA_POR_100G = 5.0


def energia_da_porcao(alimento, gramas):
    """Energia de uma porcao, em kcal.  =  kcal/100g x gramas / 100"""
    return alimento["kcal"] * gramas / 100.0


def montar_porcao(alimento, gramas):
    """
    Descreve a porcao inteira: quanto de cada coisa ela entrega.

    Devolve dicionario pronto para exibicao e para somatoria de refeicao.
    """
    fator = gramas / 100.0
    return {
        "alimento": alimento["nome"],
        "codigo_taco": alimento.get("codigo_taco"),
        "grupo": alimento["grupo"],
        "gramas": round(gramas, 1),
        "kcal": alimento["kcal"] * fator,
        "proteina_g": alimento["proteina_g"] * fator,
        "gordura_g": alimento["gordura_g"] * fator,
        "carboidrato_g": alimento["carboidrato_g"] * fator,
        "fibra_g": alimento.get("fibra_g", 0.0) * fator,
    }


def gramas_para_energia(alimento, kcal_desejadas):
    """
    Quantos gramas deste alimento entregam a energia pedida.

    Devolve None quando o alimento nao tem energia suficiente para servir de
    substituto (ver KCAL_MINIMA_POR_100G): a divisao seria valida, mas o
    resultado seria uma porcao sem sentido pratico.
    """
    if alimento["kcal"] < KCAL_MINIMA_POR_100G:
        return None
    return kcal_desejadas * 100.0 / alimento["kcal"]


def perfil_energetico(alimento):
    """
    Fracao da energia que vem de cada macronutriente.

    Devolve (proteina, gordura, carboidrato), somando aproximadamente 1.

    Trabalhar com fracoes, e nao com gramas, e o que torna alimentos de
    densidades muito diferentes comparaveis: azeite e manteiga tem perfis
    quase identicos ainda que as quantidades sejam diferentes.

    A soma raramente fecha exatamente 1: a TACO mede energia em bomba
    calorimetrica, e nao pela conta 4/9/4. A diferenca e pequena e nao
    atrapalha a comparacao, que so olha proporcoes relativas.
    """
    kcal_p = alimento["proteina_g"] * KCAL_POR_GRAMA["proteina"]
    kcal_g = alimento["gordura_g"] * KCAL_POR_GRAMA["gordura"]
    kcal_c = alimento["carboidrato_g"] * KCAL_POR_GRAMA["carboidrato"]
    total = kcal_p + kcal_g + kcal_c

    if total <= 0:
        return (0.0, 0.0, 0.0)
    return (kcal_p / total, kcal_g / total, kcal_c / total)


def distancia_de_perfil(alimento_a, alimento_b):
    """
    Quanto dois alimentos diferem em composicao, de 0 a 2.

    0 significa perfis identicos; 2, opostos completos (100% de um
    macronutriente contra 100% de outro). E a soma das diferencas absolutas
    entre as tres fracoes.

    Escolhi a soma das diferencas, e nao a distancia euclidiana, porque o
    numero fica interpretavel: 0,40 quer dizer "40% da composicao mudou de
    lugar". Isso importa porque este valor vai aparecer na tela, explicando
    ao usuario o quanto a troca altera o prato.
    """
    return sum(abs(x - y) for x, y in
               zip(perfil_energetico(alimento_a), perfil_energetico(alimento_b)))


def substitutos(alimento, gramas, catalogo, limite=5, mesmo_grupo=True,
                porcao_minima=PORCAO_MINIMA, porcao_maxima=PORCAO_MAXIMA):
    """
    Alternativas para uma porcao, da mais parecida para a menos parecida.

    Parametros:
        alimento   dicionario do alimento a ser trocado (linha de alimentos)
        gramas     quantidade da porcao original
        catalogo   alimentos disponiveis, JA filtrados pelas restricoes
        limite     quantas alternativas devolver
        mesmo_grupo   restringe ao grupo do alimento original

    Cada item devolvido traz a porcao equivalente ja calculada e a distancia
    de perfil, para que a interface possa mostrar nao so o que trocar, mas
    quanto a troca muda.

    O proprio alimento nunca aparece entre os substitutos: ele e reconhecido
    pelo codigo da TACO e, quando este falta, pelo nome.
    """
    kcal_alvo = energia_da_porcao(alimento, gramas)
    if kcal_alvo <= 0:
        return []

    encontrados = []
    for candidato in catalogo:
        if _e_o_mesmo(candidato, alimento):
            continue
        if mesmo_grupo and candidato["grupo"] != alimento["grupo"]:
            continue

        gramas_equivalentes = gramas_para_energia(candidato, kcal_alvo)
        if gramas_equivalentes is None:
            continue
        if not (porcao_minima <= gramas_equivalentes <= porcao_maxima):
            continue

        porcao = montar_porcao(candidato, gramas_equivalentes)
        porcao["distancia"] = round(distancia_de_perfil(alimento, candidato), 3)
        encontrados.append(porcao)

    # Empate em distancia e desempatado pelo nome, para que a mesma consulta
    # devolva sempre a mesma ordem. Sem isso, a lista mudaria de posicao
    # entre dois cliques e pareceria instavel a quem esta usando.
    encontrados.sort(key=lambda p: (p["distancia"], p["alimento"]))
    return encontrados[:limite]


def _e_o_mesmo(candidato, alimento):
    codigo_a = candidato.get("codigo_taco")
    codigo_b = alimento.get("codigo_taco")
    if codigo_a is not None and codigo_b is not None:
        return codigo_a == codigo_b
    return candidato["nome"] == alimento["nome"]


def explicar(porcao_original, substituto):
    """
    Frase curta explicando o que a troca faz com o prato.

    A interface precisa dizer mais do que "troque X por Y": precisa dizer o
    que muda. Sem isso a pessoa aceita a sugestao sem entender o efeito, que
    e exatamente o comportamento que este trabalho quer evitar.
    """
    diferenca_proteina = substituto["proteina_g"] - porcao_original["proteina_g"]

    if substituto["distancia"] < 0.15:
        semelhanca = "praticamente a mesma composição"
    elif substituto["distancia"] < 0.50:
        semelhanca = "composição parecida"
    else:
        semelhanca = "composição bem diferente"

    if abs(diferenca_proteina) < 1:
        proteina = "com a mesma proteína"
    elif diferenca_proteina > 0:
        proteina = f"com {diferenca_proteina:.0f} g a mais de proteína"
    else:
        proteina = f"com {abs(diferenca_proteina):.0f} g a menos de proteína"

    return (f"{substituto['gramas']:.0f} g de {substituto['alimento']} — "
            f"{semelhanca}, {proteina}.")
