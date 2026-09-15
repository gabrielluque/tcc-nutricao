"""
test_importar_taco.py - Testes do importador da Tabela TACO.

Duas camadas, de proposito:

  1. As regras de recorte testadas contra linhas inventadas, pequenas e
     legiveis. Sao elas que dizem o que entra na base e o que fica de fora,
     e um erro aqui vira alimento cru dentro de um almoco.
  2. Uma passada contra o CSV REAL da TACO, verificando os numeros que o
     Capitulo 3 vai citar e o comportamento do filtro de restricoes sobre a
     base de verdade.

O segundo grupo existe porque as regras podem estar certas em teoria e
erradas contra os dados: basta a publicacao escrever "cru" de outro jeito
para a regra deixar de casar sem que nenhum teste unitario perceba.

Execucao:
    pytest -v
"""

import os
import tempfile

import pytest

import banco
import importar_taco as imp


# ==========================================================================
# CONVERSAO DE VALORES
# ==========================================================================

def test_traco_vira_zero():
    """"Tr" na publicacao significa quantidade abaixo do limite de
    quantificacao. Para uma meta nutricional, isso e zero - e nao 0,00001,
    que apareceria arredondado como "0" mas somaria lixo em 40 alimentos."""
    assert imp.numero("1e-05") == 0.0


def test_celula_vazia_vira_none():
    """Vazio e "nao analisado", que e diferente de zero: em energia, elimina
    o alimento; em fibra, seria um zero legitimo."""
    assert imp.numero("") is None
    assert imp.numero("   ") is None
    assert imp.numero(None) is None


def test_numero_normal_atravessa():
    assert imp.numero("123.45") == pytest.approx(123.45)


# ==========================================================================
# REGRAS DE RECORTE
# ==========================================================================

def linha(numero=1, descricao="Teste", categoria="Cereais e derivados",
          energia="100", preparo="", base="teste", qualificadores=""):
    """Monta uma linha do CSV com o minimo que as regras consultam.

    Os macronutrientes entram com valores neutros porque as regras de
    recorte nao os consultam - mas converter() sim, e uma linha sem eles
    quebraria o teste por um motivo que nada tem a ver com o que ele
    verifica.
    """
    return {
        "numero_alimento": str(numero),
        "descricao": descricao,
        "categoria": categoria,
        "energia_kcal": energia,
        "preparo": preparo,
        "base": base,
        "qualificadores": qualificadores,
        "proteina_g": "1",
        "lipideos_g": "1",
        "carboidrato_g": "1",
        "fibra_g": "1",
    }


def test_alimento_comum_entra():
    assert imp.motivo_de_exclusao(linha(), set()) is None


def test_sem_energia_declarada_sai():
    assert imp.motivo_de_exclusao(linha(energia=""), set()) == \
        "sem energia declarada"


@pytest.mark.parametrize("grupo", [
    "Carnes e derivados",
    "Pescados e frutos do mar",
    "Ovos e derivados",
    "Leguminosas e derivados",
])
def test_cru_sai_nos_grupos_que_nao_se_come_cru(grupo):
    """Feijao cru e carne crua nao vao para o prato, exista ou nao uma
    versao cozida publicada."""
    fora = imp.motivo_de_exclusao(linha(categoria=grupo, preparo="cru"), set())
    assert fora == "cru em grupo que nao se come cru"


def test_fruta_crua_fica():
    """A regra nao pode esvaziar a fruteira: quase toda fruta da TACO esta
    registrada como crua, e crua e exatamente como se come."""
    assert imp.motivo_de_exclusao(
        linha(descricao="Banana, prata, crua", categoria="Frutas e derivados",
              preparo="cru", base="banana", qualificadores="prata"),
        set()) is None


def test_cru_sai_quando_a_taco_publica_a_versao_preparada():
    """Arroz cru sai porque existe arroz cozido na propria tabela."""
    preparadas = {("arroz", "tipo 1")}
    fora = imp.motivo_de_exclusao(
        linha(descricao="Arroz, tipo 1, cru", preparo="cru",
              base="Arroz", qualificadores="tipo 1"),
        preparadas)
    assert fora == "cru com versao preparada na propria TACO"


def test_cru_fica_quando_nao_ha_versao_preparada():
    """Alface so existe crua na TACO. Se a regra olhasse apenas a palavra
    "cru", a salada inteira sumiria da base."""
    assert imp.motivo_de_exclusao(
        linha(descricao="Alface, crespa, crua",
              categoria="Verduras, hortaliças e derivados", preparo="cru",
              base="alface", qualificadores="crespa"),
        {("arroz", "tipo 1")}) is None


@pytest.mark.parametrize("codigo", [472, 474])
def test_bebida_alcoolica_sai(codigo):
    """Aguardente e cerveja. O sistema sera usado por voluntarios de varias
    idades e nao pode sugerir alcool em um plano alimentar."""
    assert imp.motivo_de_exclusao(linha(numero=codigo), set()) == \
        "bebida alcoolica"


def test_exclusao_de_alcool_nao_derruba_o_grupo_de_bebidas():
    """Cafe, chas, agua de coco e sucos continuam na base: a exclusao e por
    codigo, e nao pelo grupo inteiro."""
    cafe = linha(numero=471, descricao="Café, infusão 10%",
                 categoria="Bebidas (alcoólicas e não alcoólicas)")
    assert imp.motivo_de_exclusao(cafe, set()) is None


def test_selecionar_devolve_um_motivo_para_cada_excluido():
    """Nenhum alimento pode sumir em silencio: o que nao entra precisa estar
    contado em algum motivo."""
    linhas = [
        linha(numero=1),                                     # entra
        linha(numero=2, energia=""),                         # sem energia
        linha(numero=472),                                   # alcool
        linha(numero=4, categoria="Carnes e derivados", preparo="cru"),
    ]
    alimentos, motivos = imp.selecionar(linhas)
    assert len(alimentos) == 1
    assert sum(motivos.values()) == 3


# ==========================================================================
# CONTRA O CSV REAL DA TACO
# ==========================================================================

@pytest.fixture
def relatorio_real():
    if not os.path.exists(imp.CAMINHO_CSV):
        pytest.skip("CSV da TACO ausente")
    return imp.importar(gravar=False)


def test_a_taco_tem_os_597_alimentos_publicados(relatorio_real):
    """Numero da 4a edicao. Se o CSV for trocado por outro e este teste
    falhar, a fonte citada no trabalho deixou de bater com a fonte usada."""
    assert relatorio_real["lidos"] == 597


def test_o_recorte_entrega_475_alimentos(relatorio_real):
    """Numero citado no Capitulo 3. Preso em teste para que ninguem mexa
    numa regra e descubra a mudanca so na defesa."""
    assert relatorio_real["importados"] == 475


def test_nada_se_perde_entre_o_publicado_e_o_importado(relatorio_real):
    assert (relatorio_real["importados"]
            + sum(relatorio_real["excluidos"].values())
            == relatorio_real["lidos"])


def test_as_frutas_sobrevivem_ao_filtro_de_crus(relatorio_real):
    """Regressao da regra mais perigosa do arquivo. Excluir "cru" sem olhar
    o grupo levaria as 96 frutas junto - e um sistema de nutricao sem frutas
    nao monta cardapio nenhum."""
    assert relatorio_real["grupos"]["Frutas e derivados"] == 96


def test_todo_alimento_importado_tem_energia(relatorio_real):
    alimentos, _ = imp.selecionar(imp.ler_csv())
    assert all(a["kcal"] > 0 for a in alimentos)


def test_nenhum_macronutriente_fica_negativo():
    alimentos, _ = imp.selecionar(imp.ler_csv())
    for a in alimentos:
        for campo in ("proteina_g", "gordura_g", "carboidrato_g", "fibra_g"):
            assert a[campo] >= 0, f"{a['nome']} tem {campo} negativo"


# ==========================================================================
# INTEGRACAO COM O BANCO
#
# O filtro de restricoes e a fronteira de seguranca do sistema: o que ele
# nao devolve nunca chega a IA. Testa-lo contra linhas inventadas prova
# pouco - o que importa e se ele segura contra os nomes reais da TACO.
# ==========================================================================

@pytest.fixture
def base_carregada():
    if not os.path.exists(imp.CAMINHO_CSV):
        pytest.skip("CSV da TACO ausente")
    caminho = tempfile.mktemp(suffix=".db")
    original = banco.CAMINHO_BANCO
    banco.CAMINHO_BANCO = caminho
    imp.importar(caminho_banco=caminho)
    yield caminho
    banco.CAMINHO_BANCO = original
    if os.path.exists(caminho):
        os.remove(caminho)


def test_a_base_carrega_os_475(base_carregada):
    assert banco.contar_alimentos(caminho=base_carregada) == 475


def test_importar_duas_vezes_nao_duplica(base_carregada):
    """O importador usa INSERT OR REPLACE sobre o codigo da TACO. Rodar de
    novo atualiza os valores em vez de criar uma segunda base inteira."""
    imp.importar(caminho_banco=base_carregada)
    assert banco.contar_alimentos(caminho=base_carregada) == 475


def test_intolerancia_a_lactose_remove_os_laticinios(base_carregada):
    """Com a restricao declarada, nenhum leite ou queijo pode atravessar."""
    catalogo = banco.buscar_catalogo(restricoes=["lactose"],
                                     caminho=base_carregada)
    nomes = " | ".join(a["nome"].lower() for a in catalogo)
    for proibido in ("leite", "queijo", "iogurte", "requeijão"):
        assert proibido not in nomes, f"{proibido} passou pelo filtro"


def test_o_filtro_nao_esvazia_o_cardapio(base_carregada):
    """Restricao pesada ainda precisa deixar comida suficiente para montar
    um dia. Se sobrasse quase nada, o sistema falharia justamente para quem
    mais precisa dele."""
    catalogo = banco.buscar_catalogo(
        restricoes=["lactose", "glúten", "frutos do mar"],
        caminho=base_carregada)
    assert len(catalogo) > 300


def test_alimentos_excluidos_sao_listaveis_para_o_usuario(base_carregada):
    """A tela precisa conseguir dizer o que saiu, e nao apenas omitir."""
    excluidos = banco.listar_excluidos(["lactose"], caminho=base_carregada)
    assert len(excluidos) > 0
    assert any("leite" in e["nome"].lower() for e in excluidos)
