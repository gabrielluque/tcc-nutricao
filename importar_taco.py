"""
importar_taco.py - Carrega a Tabela TACO na base de alimentos do sistema.

FONTE DOS DADOS
--------------------------------------------------------------------------
NEPA - NUCLEO DE ESTUDOS E PESQUISAS EM ALIMENTACAO. Tabela brasileira de
composicao de alimentos (TACO). 4. ed. rev. e ampl. Campinas: NEPA-UNICAMP,
2011. 161 p.

O arquivo dados/taco.csv e a planilha oficial da 4a edicao convertida para
CSV e normalizada (projeto brolesi/taco, codigo sob licenca MIT; os dados
permanecem do NEPA/UNICAMP). Todos os valores se referem a 100 g de parte
comestivel.

Do CSV de origem, que traz 32 colunas, ficaram as 11 que o sistema consulta:
identificacao, grupo, energia, os quatro macronutrientes e os tres campos
que descrevem o preparo. Minerais, vitaminas e acidos graxos foram
deixados de fora porque nenhum calculo os utiliza - carregar o que nao se
usa engordaria a base e, mais adiante, o prompt enviado a IA. Os valores
foram arredondados em duas casas; a publicacao traz uma.

Convencoes herdadas da planilha original:

    1e-05   "Tr" na publicacao = traco, quantidade abaixo do limite de
            quantificacao. Entra no sistema como 0.
    vazio   nao analisado / nao se aplica.

--------------------------------------------------------------------------
O QUE ENTRA E O QUE FICA DE FORA
--------------------------------------------------------------------------
A TACO e uma tabela de COMPOSICAO, nao um cardapio: ela descreve o alimento
como ele foi analisado em laboratorio, inclusive cru. Um sistema que sugere
refeicoes precisa de um recorte, e ele esta inteiro aqui - em um lugar so,
declarado e contavel, para poder ser descrito no Capitulo 3 e refeito por
qualquer pessoa que rode este arquivo.

Sao tres regras, nesta ordem:

    1. SEM ENERGIA DECLARADA (6 itens)
       Sem kcal nao ha como fechar a meta calorica. Nao ha o que calcular.

    2. CRU QUE NINGUEM COME CRU (114 itens)
       Duas situacoes diferentes tratadas pela mesma regra:
       a) grupos em que o alimento cru nao e comestivel - carne, pescado,
          ovo e leguminosa. Feijao cru nao vai para o prato;
       b) qualquer outro alimento cru QUANDO a propria TACO ja traz a
          versao preparada do mesmo item. "Arroz, tipo 1, cru" sai porque
          existe "Arroz, tipo 1, cozido"; "Alface, crua" fica, porque
          alface crua e alface de verdade.
       A regra (b) e o que permite manter as 96 frutas e as 78 hortalicas
       sem deixar arroz cru no almoco.

    3. BEBIDA ALCOOLICA (2 itens)
       Aguardente e cerveja. O sistema sera testado por voluntarios de
       faixas de idade diferentes e nao deve conseguir sugerir alcool em um
       plano alimentar. Sao excluidos pelo codigo da TACO, e nao pelo grupo
       inteiro: cafe, chas, agua de coco e sucos continuam na base.

Resultado: 475 alimentos dos 597 publicados.

LIMITACAO CONHECIDA, para o Capitulo 4: alguns itens que a TACO so publica
crus permanecem na base porque nao ha versao preparada - macarrao e canjica
sao os casos claros. Os valores deles sao do alimento CRU, pesado antes do
cozimento. O nome carrega a palavra "cru", mas quem le o cardapio precisa
saber disso.

--------------------------------------------------------------------------
USO
--------------------------------------------------------------------------
    python importar_taco.py                 # carrega no banco padrao
    python importar_taco.py --relatorio      # so mostra o que faria
"""

import argparse
import csv
import os
import sys

import banco

CAMINHO_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "dados", "taco.csv")

# "Tr" na publicacao: quantidade detectada, porem abaixo do limite de
# quantificacao. Para uma meta nutricional isso e zero.
TRACO = 1e-05

# Grupos em que o alimento cru nao e comestivel.
NUNCA_CRU = {
    "Carnes e derivados",
    "Pescados e frutos do mar",
    "Ovos e derivados",
    "Leguminosas e derivados",
}

# Excluidos pelo codigo da TACO, um a um, para nao derrubar o grupo inteiro
# de bebidas junto (cafe, chas, agua de coco e refrigerantes ficam).
ALCOOLICOS = {472, 474}   # 472 Cana, aguardente | 474 Cerveja, pilsen

# Colunas do CSV que o sistema consome. As outras (minerais, vitaminas,
# aminoacidos) ficam de fora porque o calculo nao as utiliza - trazer o que
# nao se usa so aumentaria a base e o prompt enviado a IA.
COLUNAS = {
    "codigo_taco":   "numero_alimento",
    "nome":          "descricao",
    "grupo":         "categoria",
    "kcal":          "energia_kcal",
    "proteina_g":    "proteina_g",
    "gordura_g":     "lipideos_g",
    "carboidrato_g": "carboidrato_g",
    "fibra_g":       "fibra_g",
}


def numero(bruto):
    """
    Converte uma celula do CSV em numero.

    Celula vazia vira None (nao analisado); traco vira 0. A distincao
    importa: None em energia elimina o alimento, 0 em fibra e um valor
    legitimo.
    """
    bruto = (bruto or "").strip()
    if not bruto:
        return None
    try:
        valor = float(bruto)
    except ValueError:
        return None
    return 0.0 if valor <= TRACO else valor


def chave_do_alimento(linha):
    """Identidade do alimento sem o modo de preparo.

    "Arroz, tipo 1, cru" e "Arroz, tipo 1, cozido" compartilham a mesma
    chave; e por isso que a regra 2b consegue saber que existe uma versao
    preparada do item cru.
    """
    return (linha["base"].strip().lower(),
            linha["qualificadores"].strip().lower())


def motivo_de_exclusao(linha, chaves_preparadas):
    """
    Devolve o motivo pelo qual o alimento NAO entra, ou None se ele entra.

    Devolver o motivo em vez de um booleano e o que permite o relatorio
    dizer quantos alimentos sairam por qual razao - numero que vai para o
    Capitulo 3 e que denuncia na hora se uma regra ficou ampla demais.
    """
    if int(linha["numero_alimento"]) in ALCOOLICOS:
        return "bebida alcoolica"

    if numero(linha["energia_kcal"]) is None:
        return "sem energia declarada"

    if linha["preparo"].strip().lower() == "cru":
        if linha["categoria"] in NUNCA_CRU:
            return "cru em grupo que nao se come cru"
        if chave_do_alimento(linha) in chaves_preparadas:
            return "cru com versao preparada na propria TACO"

    return None


def converter(linha):
    """Traduz uma linha do CSV para os campos da tabela alimentos."""
    return {
        "codigo_taco":   int(linha[COLUNAS["codigo_taco"]]),
        "nome":          linha[COLUNAS["nome"]].strip(),
        "grupo":         linha[COLUNAS["grupo"]].strip(),
        "kcal":          numero(linha[COLUNAS["kcal"]]) or 0.0,
        "proteina_g":    numero(linha[COLUNAS["proteina_g"]]) or 0.0,
        "gordura_g":     numero(linha[COLUNAS["gordura_g"]]) or 0.0,
        "carboidrato_g": numero(linha[COLUNAS["carboidrato_g"]]) or 0.0,
        "fibra_g":       numero(linha[COLUNAS["fibra_g"]]) or 0.0,
    }


def selecionar(linhas):
    """
    Aplica as tres regras e devolve (alimentos, motivos).

    alimentos: lista pronta para o banco.
    motivos:   dicionario motivo -> quantidade, para o relatorio.
    """
    linhas = list(linhas)

    # A regra 2b precisa saber, antes de decidir sobre qualquer item cru,
    # quais alimentos a TACO publica preparados. Por isso o levantamento
    # acontece em uma passada anterior.
    chaves_preparadas = {
        chave_do_alimento(linha) for linha in linhas
        if linha["preparo"].strip().lower() not in ("", "cru")
    }

    alimentos, motivos = [], {}
    for linha in linhas:
        motivo = motivo_de_exclusao(linha, chaves_preparadas)
        if motivo:
            motivos[motivo] = motivos.get(motivo, 0) + 1
        else:
            alimentos.append(converter(linha))

    return alimentos, motivos


def ler_csv(caminho=CAMINHO_CSV):
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def importar(caminho_csv=CAMINHO_CSV, caminho_banco=None, gravar=True):
    """
    Executa a importacao completa e devolve o relatorio.

    Com gravar=False nada e escrito no banco: serve para conferir o recorte
    antes de mexer na base, e e o que o modo --relatorio usa.
    """
    alimentos, motivos = selecionar(ler_csv(caminho_csv))

    if gravar:
        banco.criar_esquema(caminho_banco)
        for alimento in alimentos:
            banco.inserir_alimento(caminho=caminho_banco, **alimento)

    grupos = {}
    for alimento in alimentos:
        grupos[alimento["grupo"]] = grupos.get(alimento["grupo"], 0) + 1

    return {
        "lidos": len(alimentos) + sum(motivos.values()),
        "importados": len(alimentos),
        "excluidos": motivos,
        "grupos": grupos,
    }


def imprimir(relatorio):
    print(f"\nTACO 4a edicao — {relatorio['lidos']} alimentos publicados\n")
    print(f"  importados: {relatorio['importados']}")
    for motivo, quantidade in sorted(relatorio["excluidos"].items(),
                                     key=lambda item: -item[1]):
        print(f"  fora ({quantidade:>3}): {motivo}")

    print("\n  por grupo:")
    for grupo, quantidade in sorted(relatorio["grupos"].items(),
                                    key=lambda item: -item[1]):
        print(f"    {quantidade:>4}  {grupo}")
    print()


if __name__ == "__main__":
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--relatorio", action="store_true",
                            help="mostra o recorte sem gravar no banco")
    analisador.add_argument("--csv", default=CAMINHO_CSV)
    argumentos = analisador.parse_args()

    if not os.path.exists(argumentos.csv):
        sys.exit(f"CSV da TACO nao encontrado em {argumentos.csv}")

    relatorio = importar(argumentos.csv, gravar=not argumentos.relatorio)
    imprimir(relatorio)

    if argumentos.relatorio:
        print("  (nada foi gravado — modo relatorio)\n")
    else:
        print(f"  gravados em {banco.CAMINHO_BANCO}\n")
