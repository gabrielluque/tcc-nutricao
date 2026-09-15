"""
integracao_ia.py - Geracao do cardapio com apoio de IA.

--------------------------------------------------------------------------
O QUE A IA DECIDE E O QUE ELA NAO DECIDE
--------------------------------------------------------------------------
Este e o arquivo mais delicado do sistema, porque e o unico ponto em que um
componente probabilistico participa de uma decisao sobre a alimentacao de
uma pessoa. A regra que organiza tudo aqui e uma so:

    A IA ESCOLHE. O SISTEMA CALCULA.

O modelo recebe o catalogo de alimentos permitidos e devolve apenas DOIS
campos por item: o codigo do alimento na TACO e a quantidade em gramas.
Ele nao escreve nome de alimento, nao informa caloria, nao soma nada.

Toda a aritmetica - kcal, proteina, gordura, carboidrato, fibra, totais da
refeicao e totais do dia - e refeita aqui a partir da tabela TACO, com os
mesmos valores que o resto do sistema usa. Se o modelo alucinar um numero,
o numero e simplesmente ignorado, porque nenhum numero dele e lido.

O que o modelo faz bem, e que nenhuma formula faz, e escolher o que combina:
arroz com feijao e couve, e nao arroz com mamao e sardinha. Esse e o
trabalho dele, e e so esse.

--------------------------------------------------------------------------
AS TRES BARREIRAS
--------------------------------------------------------------------------

1. O CATALOGO JA CHEGA FILTRADO

   Quem monta a lista enviada ao modelo e banco.buscar_catalogo, que ja
   removeu os alimentos incompativeis com as restricoes declaradas. O
   alimento proibido nunca entra no prompt, entao o modelo nao tem como
   sugeri-lo. A restricao alimentar nunca e um PEDIDO em linguagem natural
   dentro do texto - seria a diferenca entre uma trava e um favor.

2. O QUE VOLTA E CONFERIDO CONTRA O CATALOGO

   Todo codigo devolvido e procurado na lista permitida. Codigo inventado,
   codigo de alimento excluido pela restricao ou quantidade fora da faixa
   plausivel sao DESCARTADOS, e o descarte e contado e devolvido. Um numero
   de descartes alto e sinal de que o prompt precisa mudar - e por isso ele
   aparece no resultado em vez de ser engolido.

3. A CONTA FINAL E FECHADA PELO SISTEMA

   O modelo acerta a composicao do prato, mas erra a aritmetica da meta.
   Depois de validar, o sistema mede a diferenca entre o total obtido e a
   meta calorica e reescala as porcoes proporcionalmente. A meta nao e uma
   sugestao que a IA tenta atingir: e uma restricao que o sistema impoe
   depois.

--------------------------------------------------------------------------
BIBLIOTECA
--------------------------------------------------------------------------
Usa google-genai, o SDK atual. O pacote google-generativeai, usado na
primeira versao deste projeto, foi descontinuado pelo Google e nao recebe
mais correcoes.
"""

import json
import os

# Faixa de quantidade aceita para um unico item. Fora disso o item e
# descartado: 3 g de arroz e 900 g de carne sao os dois jeitos de o modelo
# escrever uma refeicao que ninguem faria.
GRAMAS_MINIMO = 10.0
GRAMAS_MAXIMO = 500.0

# Quanto o total pode divergir da meta antes de o sistema reescalar.
TOLERANCIA_CALORICA = 0.05

MODELO_PADRAO = "gemini-2.5-flash"

NOMES_DE_REFEICAO = {
    1: ["Refeição única"],
    2: ["Almoço", "Jantar"],
    3: ["Café da manhã", "Almoço", "Jantar"],
    4: ["Café da manhã", "Almoço", "Lanche da tarde", "Jantar"],
    5: ["Café da manhã", "Lanche da manhã", "Almoço", "Lanche da tarde",
        "Jantar"],
    6: ["Café da manhã", "Lanche da manhã", "Almoço", "Lanche da tarde",
        "Jantar", "Ceia"],
}

# Estrutura exigida da resposta. O modelo devolve codigo e gramas, e nada
# mais - qualquer campo extra seria ignorado de qualquer forma.
ESQUEMA_RESPOSTA = {
    "type": "OBJECT",
    "properties": {
        "refeicoes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "nome": {"type": "STRING"},
                    "itens": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "codigo_taco": {"type": "INTEGER"},
                                "gramas": {"type": "NUMBER"},
                            },
                            "required": ["codigo_taco", "gramas"],
                        },
                    },
                },
                "required": ["nome", "itens"],
            },
        }
    },
    "required": ["refeicoes"],
}


# ==========================================================================
# 1. O PROMPT
# ==========================================================================

def catalogo_em_texto(catalogo):
    """
    Converte o catalogo permitido em linhas compactas para o prompt.

    Formato: codigo|nome|kcal|proteina|gordura|carboidrato, por 100 g.

    O catalogo inteiro vai no prompt, e nao um subconjunto por refeicao.
    Enviar tudo custa alguns milhares de caracteres a mais e evita um
    problema pior: escolher de antemao quais grupos "servem" para o cafe da
    manha seria justamente o tipo de julgamento cultural que se esta
    delegando ao modelo.
    """
    linhas = []
    for a in catalogo:
        linhas.append(
            f"{a['codigo_taco']}|{a['nome']}|{a['kcal']:.0f}|"
            f"{a['proteina_g']:.1f}|{a['gordura_g']:.1f}|"
            f"{a['carboidrato_g']:.1f}"
        )
    return "\n".join(linhas)


def montar_prompt(plano, refeicoes_por_dia, catalogo, preferencias=""):
    """Texto enviado ao modelo. Metas, catalogo e regras do formato."""
    nomes = NOMES_DE_REFEICAO.get(refeicoes_por_dia,
                                  NOMES_DE_REFEICAO[3])

    pedido_preferencias = ""
    if preferencias.strip():
        pedido_preferencias = (
            f"\nA pessoa gosta destes alimentos: {preferencias.strip()}. "
            "Use os que estiverem no catálogo, sempre que couberem nas metas."
        )

    return f"""Você monta cardápios usando SOMENTE os alimentos do catálogo abaixo.

METAS DO DIA
Energia:      {plano['meta_calorica']:.0f} kcal
Proteína:     {plano['proteina_g']:.0f} g
Gordura:      {plano['gordura_g']:.0f} g
Carboidrato:  {plano['carboidrato_g']:.0f} g
Fibras:       {plano['fibras_g']:.0f} g

REFEIÇÕES: {refeicoes_por_dia} — {', '.join(nomes)}
{pedido_preferencias}

CATÁLOGO PERMITIDO (código|nome|kcal|proteína|gordura|carboidrato por 100 g)
{catalogo_em_texto(catalogo)}

REGRAS
1. Use exclusivamente códigos que aparecem no catálogo acima. Um código
   fora da lista invalida o item.
2. Informe apenas o código e a quantidade em gramas. Não escreva nomes de
   alimentos, calorias ou somas: esses valores são calculados pelo sistema.
3. Quantidades entre {GRAMAS_MINIMO:.0f} e {GRAMAS_MAXIMO:.0f} gramas por item.
4. De 2 a 5 itens por refeição, montando pratos que façam sentido na
   comida brasileira do dia a dia.
5. Aproxime-se das metas, mas priorize combinações que uma pessoa comeria
   de verdade. O ajuste fino das quantidades é feito depois pelo sistema.
"""


# ==========================================================================
# 2. A CHAMADA
#
# Unica funcao deste arquivo que toca a rede. Fica isolada de proposito:
# todo o resto e testavel sem internet e sem cota de API.
# ==========================================================================

def chamar_gemini(prompt, modelo=MODELO_PADRAO, chave=None):
    """Envia o prompt e devolve a resposta ja convertida em dicionario."""
    from google import genai
    from google.genai import types

    chave = chave or os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY não definida.")

    cliente = genai.Client(api_key=chave)
    resposta = cliente.models.generate_content(
        model=modelo,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ESQUEMA_RESPOSTA,
            # Temperatura baixa, e nao zero: zero deixaria o cardapio
            # identico a cada geracao, e a variedade entre os dias e parte
            # do que se esta avaliando com os voluntarios.
            temperature=0.4,
        ),
    )
    return json.loads(resposta.text)


# ==========================================================================
# 3. VALIDACAO CONTRA A TACO
# ==========================================================================

def validar(resposta, catalogo):
    """
    Confere a resposta do modelo contra o catalogo permitido.

    Devolve (refeicoes, descartados). Cada item aceito ja vem com os valores
    nutricionais recalculados a partir da TACO - nenhum numero vindo do
    modelo atravessa esta funcao.

    Os descartes sao devolvidos com o motivo. Nao sao erro fatal: um item
    invalido no meio de um cardapio nao justifica recusar o cardapio
    inteiro. Mas sao contados, porque um numero alto significa que o prompt
    precisa mudar - e essa informacao vira dado do Capitulo 4.
    """
    permitidos = {a["codigo_taco"]: a for a in catalogo}
    refeicoes, descartados = [], []

    for bruta in resposta.get("refeicoes", []):
        itens = []
        for item in bruta.get("itens", []):
            codigo = item.get("codigo_taco")
            gramas = item.get("gramas")

            alimento = permitidos.get(codigo)
            if alimento is None:
                descartados.append({"codigo_taco": codigo,
                                    "motivo": "código fora do catálogo"})
                continue

            if not isinstance(gramas, (int, float)):
                descartados.append({"codigo_taco": codigo,
                                    "motivo": "quantidade inválida"})
                continue

            if not (GRAMAS_MINIMO <= gramas <= GRAMAS_MAXIMO):
                descartados.append({"codigo_taco": codigo,
                                    "nome": alimento["nome"],
                                    "motivo": f"quantidade fora da faixa "
                                              f"({gramas:.0f} g)"})
                continue

            itens.append(_montar_item(alimento, float(gramas)))

        if itens:
            refeicoes.append({"nome": bruta.get("nome", "Refeição"),
                              "itens": itens,
                              "totais": somar(itens)})

    return refeicoes, descartados


def _montar_item(alimento, gramas):
    """Item do cardapio, com os numeros vindos da TACO."""
    fator = gramas / 100.0
    return {
        "codigo_taco": alimento["codigo_taco"],
        "alimento": alimento["nome"],
        "grupo": alimento["grupo"],
        "gramas": round(gramas, 1),
        "kcal": alimento["kcal"] * fator,
        "proteina_g": alimento["proteina_g"] * fator,
        "gordura_g": alimento["gordura_g"] * fator,
        "carboidrato_g": alimento["carboidrato_g"] * fator,
        "fibra_g": alimento.get("fibra_g", 0.0) * fator,
    }


def somar(itens):
    """Soma dos valores nutricionais de uma lista de itens."""
    campos = ("kcal", "proteina_g", "gordura_g", "carboidrato_g", "fibra_g")
    return {campo: sum(item[campo] for item in itens) for campo in campos}


# ==========================================================================
# 4. FECHAMENTO DA CONTA
# ==========================================================================

def ajustar_para_a_meta(refeicoes, meta_calorica):
    """
    Reescala as porcoes ate o total bater com a meta.

    O modelo monta pratos coerentes, mas raramente fecha a conta: erra por
    10% ou 15% para cima ou para baixo. Em vez de pedir de novo - o que
    gastaria cota e devolveria outro erro parecido - o sistema multiplica
    todas as quantidades pelo mesmo fator.

    Escalar tudo junto preserva as PROPORCOES escolhidas pelo modelo: o
    prato continua sendo o mesmo prato, apenas maior ou menor. Ajustar item
    a item mudaria a composicao que a IA compos, que e justamente a parte
    que ela fez bem.

    As quantidades sao arredondadas a cada 5 g, porque ninguem pesa 87,3 g
    de arroz.
    """
    total = somar([item for r in refeicoes for item in r["itens"]])
    if total["kcal"] <= 0:
        return refeicoes, 1.0

    fator = meta_calorica / total["kcal"]
    if abs(fator - 1) <= TOLERANCIA_CALORICA:
        return refeicoes, 1.0

    for refeicao in refeicoes:
        novos = []
        for item in refeicao["itens"]:
            gramas = max(GRAMAS_MINIMO,
                         round(item["gramas"] * fator / 5.0) * 5.0)
            proporcao = gramas / item["gramas"]
            ajustado = dict(item)
            ajustado["gramas"] = round(gramas, 1)
            for campo in ("kcal", "proteina_g", "gordura_g",
                          "carboidrato_g", "fibra_g"):
                ajustado[campo] = item[campo] * proporcao
            novos.append(ajustado)
        refeicao["itens"] = novos
        refeicao["totais"] = somar(novos)

    return refeicoes, fator


def comparar_com_as_metas(totais, plano):
    """
    Diferenca entre o que o cardapio entrega e o que a meta pedia.

    Vai para a tela. O usuario tem direito de ver o quanto o cardapio ficou
    longe do alvo, em vez de receber um resultado que se apresenta como
    exato.
    """
    alvos = {
        "kcal": plano["meta_calorica"],
        "proteina_g": plano["proteina_g"],
        "gordura_g": plano["gordura_g"],
        "carboidrato_g": plano["carboidrato_g"],
        "fibra_g": plano["fibras_g"],
    }
    comparacao = {}
    for campo, alvo in alvos.items():
        obtido = totais.get(campo, 0.0)
        comparacao[campo] = {
            "alvo": alvo,
            "obtido": obtido,
            "diferenca": obtido - alvo,
            "percentual": round(100 * (obtido - alvo) / alvo, 1) if alvo else 0.0,
        }
    return comparacao


# ==========================================================================
# 5. ORQUESTRACAO
# ==========================================================================

def gerar_cardapio(plano, refeicoes_por_dia, catalogo, preferencias="",
                   chamar=None, modelo=MODELO_PADRAO, chave=None):
    """
    Monta o cardapio do dia. Fronteira do modulo: o app.py chama so isto.

    O parametro "chamar" existe para os testes: permite injetar uma funcao
    que devolve uma resposta pronta, sem rede e sem consumir cota. Em
    producao ele fica None e a chamada real acontece.
    """
    if not catalogo:
        raise ValueError("Catálogo vazio: nenhum alimento disponível.")

    chamar = chamar or (lambda p: chamar_gemini(p, modelo=modelo, chave=chave))
    prompt = montar_prompt(plano, refeicoes_por_dia, catalogo, preferencias)

    resposta = chamar(prompt)
    refeicoes, descartados = validar(resposta, catalogo)

    if not refeicoes:
        raise ValueError(
            "Nenhum item do cardápio sobreviveu à validação contra a TACO.")

    refeicoes, fator = ajustar_para_a_meta(refeicoes, plano["meta_calorica"])
    totais = somar([item for r in refeicoes for item in r["itens"]])

    return {
        "refeicoes": refeicoes,
        "totais": totais,
        "comparacao": comparar_com_as_metas(totais, plano),
        "descartados": descartados,
        "fator_de_ajuste": round(fator, 3),
        "modelo": modelo,
    }
