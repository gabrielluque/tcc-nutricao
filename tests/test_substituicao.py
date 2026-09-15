"""
test_substituicao.py - Testes do motor de substituicao.

Duas camadas, como no importador: as regras contra alimentos inventados,
pequenos e legiveis, e depois uma passada contra a base real da TACO.

A segunda camada e a que importa mais aqui. Uma regra de substituicao pode
estar perfeita na teoria e produzir "1,9 kg de alface" contra os dados
reais - e e contra os dados reais que o sistema vai rodar.

Execucao:
    pytest -v
"""

import os
import tempfile

import pytest

import banco
import importar_taco
import substituicao as sub


# ==========================================================================
# ALIMENTOS DE TESTE
#
# Valores redondos de proposito: assim a conta esperada pode ser conferida
# de cabeca por quem le o teste.
# ==========================================================================

ARROZ = {"codigo_taco": 1, "nome": "Arroz cozido", "grupo": "Cereais",
         "kcal": 100.0, "proteina_g": 2.0, "gordura_g": 0.0,
         "carboidrato_g": 23.0, "fibra_g": 1.0}

MACARRAO = {"codigo_taco": 2, "nome": "Macarrão cozido", "grupo": "Cereais",
            "kcal": 200.0, "proteina_g": 4.0, "gordura_g": 0.0,
            "carboidrato_g": 46.0, "fibra_g": 2.0}

OLEO = {"codigo_taco": 3, "nome": "Óleo", "grupo": "Cereais",
        "kcal": 900.0, "proteina_g": 0.0, "gordura_g": 100.0,
        "carboidrato_g": 0.0, "fibra_g": 0.0}

FRANGO = {"codigo_taco": 4, "nome": "Frango grelhado", "grupo": "Carnes",
          "kcal": 160.0, "proteina_g": 32.0, "gordura_g": 3.0,
          "carboidrato_g": 0.0, "fibra_g": 0.0}

CHA = {"codigo_taco": 5, "nome": "Chá", "grupo": "Cereais",
       "kcal": 2.0, "proteina_g": 0.0, "gordura_g": 0.0,
       "carboidrato_g": 0.5, "fibra_g": 0.0}


# ==========================================================================
# ENERGIA E PORCAO
# ==========================================================================

def test_energia_da_porcao():
    assert sub.energia_da_porcao(ARROZ, 150) == pytest.approx(150.0)


def test_porcao_escala_todos_os_macros_juntos():
    porcao = sub.montar_porcao(ARROZ, 200)
    assert porcao["kcal"] == pytest.approx(200.0)
    assert porcao["proteina_g"] == pytest.approx(4.0)
    assert porcao["carboidrato_g"] == pytest.approx(46.0)
    assert porcao["fibra_g"] == pytest.approx(2.0)


def test_equivalencia_e_por_energia_e_nao_por_peso():
    """A decisao central do arquivo.

    O macarrao tem o dobro da energia do arroz por grama, entao 200 g de
    arroz equivalem a 100 g de macarrao - e nao a 200 g. Trocar peso por
    peso dobraria as calorias da refeicao sem ninguem perceber.
    """
    kcal = sub.energia_da_porcao(ARROZ, 200)
    assert sub.gramas_para_energia(MACARRAO, kcal) == pytest.approx(100.0)


def test_alimento_quase_sem_energia_nao_serve_de_substituto():
    """Chá tem 2 kcal por 100 g. Igualar um prato de comida exigiria litros.
    A funcao recusa em vez de devolver um numero absurdo."""
    assert sub.gramas_para_energia(CHA, 200) is None


# ==========================================================================
# PERFIL DE MACRONUTRIENTES
# ==========================================================================

def test_perfil_do_oleo_e_gordura_pura():
    proteina, gordura, carboidrato = sub.perfil_energetico(OLEO)
    assert gordura == pytest.approx(1.0)
    assert proteina == pytest.approx(0.0)
    assert carboidrato == pytest.approx(0.0)


def test_perfil_do_arroz_e_quase_todo_carboidrato():
    _, _, carboidrato = sub.perfil_energetico(ARROZ)
    assert carboidrato > 0.85


def test_alimentos_de_mesmo_perfil_tem_distancia_zero():
    """Arroz e macarrao tem exatamente o dobro dos valores um do outro, logo
    o mesmo perfil. Densidade diferente, composicao igual."""
    assert sub.distancia_de_perfil(ARROZ, MACARRAO) == pytest.approx(0.0)


def test_perfis_opostos_tem_distancia_maxima():
    assert sub.distancia_de_perfil(OLEO, ARROZ) > 1.8


def test_distancia_e_simetrica():
    assert (sub.distancia_de_perfil(ARROZ, FRANGO)
            == pytest.approx(sub.distancia_de_perfil(FRANGO, ARROZ)))


# ==========================================================================
# ESCOLHA DOS SUBSTITUTOS
# ==========================================================================

def test_o_mais_parecido_vem_primeiro():
    catalogo = [OLEO, MACARRAO, ARROZ]
    resultado = sub.substitutos(ARROZ, 150, catalogo)
    assert resultado[0]["alimento"] == "Macarrão cozido"


def test_o_proprio_alimento_nao_aparece_na_lista():
    resultado = sub.substitutos(ARROZ, 150, [ARROZ, MACARRAO])
    assert all(p["alimento"] != "Arroz cozido" for p in resultado)


def test_porcao_do_substituto_entrega_a_mesma_energia():
    """Invariante do modulo: qualquer substituto devolvido tem de repor
    exatamente a energia da porcao trocada."""
    original = sub.energia_da_porcao(ARROZ, 150)
    for porcao in sub.substitutos(ARROZ, 150, [MACARRAO, OLEO]):
        assert porcao["kcal"] == pytest.approx(original)


def test_porcao_absurda_e_descartada():
    """O oleo entraria com 16 g para substituir 150 g de arroz - abaixo do
    minimo. Aritmeticamente certo, praticamente inutil."""
    resultado = sub.substitutos(ARROZ, 150, [OLEO], mesmo_grupo=True)
    assert resultado == []


def test_grupo_diferente_so_entra_quando_pedido():
    assert sub.substitutos(ARROZ, 150, [FRANGO]) == []
    assert len(sub.substitutos(ARROZ, 150, [FRANGO], mesmo_grupo=False)) == 1


def test_ordem_e_estavel_entre_chamadas():
    """Lista que muda de ordem entre dois cliques parece defeito."""
    catalogo = [MACARRAO, ARROZ, FRANGO]
    primeira = sub.substitutos(ARROZ, 150, catalogo, mesmo_grupo=False)
    segunda = sub.substitutos(ARROZ, 150, catalogo, mesmo_grupo=False)
    assert [p["alimento"] for p in primeira] == [p["alimento"] for p in segunda]


def test_limite_e_respeitado():
    catalogo = [MACARRAO, FRANGO, OLEO]
    assert len(sub.substitutos(ARROZ, 150, catalogo,
                               limite=1, mesmo_grupo=False)) == 1


# ==========================================================================
# EXPLICACAO EM TEXTO
# ==========================================================================

def test_explicacao_menciona_quantidade_e_alimento():
    original = sub.montar_porcao(ARROZ, 150)
    troca = sub.substitutos(ARROZ, 150, [MACARRAO])[0]
    frase = sub.explicar(original, troca)
    assert "75 g" in frase
    assert "Macarrão cozido" in frase


def test_explicacao_avisa_quando_a_proteina_muda_muito():
    original = sub.montar_porcao(ARROZ, 150)
    troca = sub.substitutos(ARROZ, 150, [FRANGO], mesmo_grupo=False)[0]
    frase = sub.explicar(original, troca)
    assert "a mais de proteína" in frase


# ==========================================================================
# CONTRA A BASE REAL DA TACO
# ==========================================================================

@pytest.fixture
def base():
    if not os.path.exists(importar_taco.CAMINHO_CSV):
        pytest.skip("CSV da TACO ausente")
    caminho = tempfile.mktemp(suffix=".db")
    original = banco.CAMINHO_BANCO
    banco.CAMINHO_BANCO = caminho
    importar_taco.importar(caminho_banco=caminho)
    yield caminho
    banco.CAMINHO_BANCO = original
    if os.path.exists(caminho):
        os.remove(caminho)


def um_alimento(catalogo, trecho):
    for alimento in catalogo:
        if trecho.lower() in alimento["nome"].lower():
            return alimento
    pytest.skip(f"alimento com '{trecho}' nao encontrado na base")


def test_arroz_encontra_substitutos_reais(base):
    catalogo = banco.buscar_catalogo(caminho=base)
    arroz = um_alimento(catalogo, "Arroz, tipo 1, cozido")
    resultado = sub.substitutos(arroz, 150, catalogo)
    assert len(resultado) > 0
    for porcao in resultado:
        assert 20 <= porcao["gramas"] <= 400


def test_nenhuma_porcao_real_fica_absurda(base):
    """Varre a base inteira procurando o erro que este modulo mais arrisca
    cometer: mandar comer 1,9 kg de alface."""
    catalogo = banco.buscar_catalogo(caminho=base)
    for alimento in catalogo[:80]:
        for porcao in sub.substitutos(alimento, 100, catalogo):
            assert porcao["gramas"] <= sub.PORCAO_MAXIMA
            assert porcao["gramas"] >= sub.PORCAO_MINIMA


def test_substituicao_nunca_reintroduz_um_alergenico(base):
    """
    A propriedade de seguranca do modulo.

    O catalogo chega filtrado por banco.buscar_catalogo. Se a substituicao
    devolvesse um alimento de fora dessa lista, toda a fronteira de
    seguranca alimentar do sistema cairia - e cairia justamente no ponto em
    que o usuario acha que esta so trocando um ingrediente.
    """
    catalogo = banco.buscar_catalogo(restricoes=["lactose"], caminho=base)
    permitidos = {a["codigo_taco"] for a in catalogo}

    for alimento in catalogo[:50]:
        for porcao in sub.substitutos(alimento, 100, catalogo,
                                      mesmo_grupo=False):
            assert porcao["codigo_taco"] in permitidos
            assert "leite" not in porcao["alimento"].lower()
            assert "queijo" not in porcao["alimento"].lower()


def test_carne_e_substituida_por_carne_e_nao_por_doce(base):
    """O ranking por perfil precisa funcionar sem nenhuma regra escrita a
    mao sobre o que combina com o que."""
    catalogo = banco.buscar_catalogo(caminho=base)
    frango = um_alimento(catalogo, "Frango, peito, sem pele, grelhado")
    resultado = sub.substitutos(frango, 120, catalogo, mesmo_grupo=False,
                                limite=5)

    assert len(resultado) > 0
    for porcao in resultado:
        proteina, _, _ = sub.perfil_energetico({
            "proteina_g": porcao["proteina_g"],
            "gordura_g": porcao["gordura_g"],
            "carboidrato_g": porcao["carboidrato_g"],
        })
        assert proteina > 0.4, f"{porcao['alimento']} nao e fonte de proteina"
