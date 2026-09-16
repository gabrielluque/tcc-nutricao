"""
test_app.py - Testes das rotas web.

Usam o cliente de teste do Flask: as requisicoes sao feitas em memoria, sem
subir servidor nem abrir navegador. Cada teste roda contra um banco
temporario proprio.

O que se verifica aqui nao e a aparencia das telas, e sim o comportamento
que precisa valer sempre: quem nao esta logado nao entra, entrada invalida
nao derruba o servidor, e ninguem ve o dado de outra pessoa.

Execucao:
    pytest -v
"""

import os
import tempfile

import pytest

import app as aplicacao
import banco


@pytest.fixture
def cliente():
    """Aplicacao apontada para um banco temporario, com um usuario pronto."""
    caminho = tempfile.mktemp(suffix=".db")
    original = banco.CAMINHO_BANCO
    banco.CAMINHO_BANCO = caminho
    banco.criar_esquema(caminho)
    banco.criar_usuario("Gabriel", "gabriel@teste.com", "senha123",
                        consentiu_lgpd=True, caminho=caminho)

    aplicacao.app.config["TESTING"] = True
    aplicacao.app.secret_key = "chave-de-teste"

    with aplicacao.app.test_client() as c:
        yield c

    banco.CAMINHO_BANCO = original
    if os.path.exists(caminho):
        os.remove(caminho)


def entrar(cliente):
    return cliente.post("/login", data={"email": "gabriel@teste.com",
                                        "senha": "senha123"})


DADOS_VALIDOS = {
    "sexo": "M",
    "data_nascimento": "1996-03-15",
    "altura_cm": "175",
    "peso": "80",
    "bf": "30",
    "nivel_atividade": "moderado",
    "objetivo": "perder",
    "refeicoes_por_dia": "4",
    "restricoes": "",
    "preferencias": "",
    "etapa": "calcular",
}


# ==========================================================================
# CONTROLE DE ACESSO
# ==========================================================================

@pytest.mark.parametrize("rota", ["/", "/historico", "/conta"])
def test_rotas_protegidas_redirecionam_para_login(cliente, rota):
    """O decorador exige_login precisa valer em TODAS as rotas internas."""
    resposta = cliente.get(rota)
    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_login_valido_entra(cliente):
    resposta = entrar(cliente)
    assert resposta.status_code == 302
    assert cliente.get("/").status_code == 200


def test_login_invalido_nao_entra(cliente):
    resposta = cliente.post("/login", data={"email": "gabriel@teste.com",
                                            "senha": "errada"})
    assert resposta.status_code == 200          # volta para a tela
    assert cliente.get("/").status_code == 302  # segue bloqueado


def test_mensagem_de_erro_nao_revela_se_o_email_existe(cliente):
    """Senha errada e e-mail inexistente precisam produzir a MESMA mensagem.

    Se a tela dissesse "este e-mail nao existe", qualquer pessoa poderia
    descobrir quem tem conta no sistema testando enderecos um a um.

    A comparacao e da mensagem, e nao da pagina inteira: o campo de e-mail
    e repreenchido com o que o proprio usuario digitou, e essa diferenca e
    esperada.
    """
    mensagem = "E-mail ou senha incorretos.".encode()
    a = cliente.post("/login", data={"email": "gabriel@teste.com", "senha": "x"})
    b = cliente.post("/login", data={"email": "ninguem@teste.com", "senha": "x"})

    assert mensagem in a.data
    assert mensagem in b.data
    assert a.status_code == b.status_code
    # Nenhuma das duas pode insinuar qual dos dois campos estava errado.
    for resposta in (a, b):
        assert "não existe".encode() not in resposta.data
        assert "não cadastrado".encode() not in resposta.data


def test_logout_encerra_a_sessao(cliente):
    entrar(cliente)
    cliente.get("/logout")
    assert cliente.get("/").status_code == 302


# ==========================================================================
# CADASTRO
# ==========================================================================

def test_cadastro_sem_consentimento_e_recusado(cliente):
    """A LGPD exige aceite explicito: sem a caixa marcada, nao cria conta."""
    cliente.post("/cadastro", data={"nome": "Maria", "email": "maria@t.com",
                                    "senha": "senha123"})
    assert banco.autenticar("maria@t.com", "senha123") is None


def test_cadastro_com_senha_curta_e_recusado(cliente):
    cliente.post("/cadastro", data={"nome": "Maria", "email": "maria@t.com",
                                    "senha": "123", "consentimento": "sim"})
    assert banco.autenticar("maria@t.com", "123") is None


def test_cadastro_valido_cria_conta(cliente):
    resposta = cliente.post("/cadastro", data={
        "nome": "Maria", "email": "maria@t.com",
        "senha": "senha123", "consentimento": "sim"})
    assert resposta.status_code == 302
    assert banco.autenticar("maria@t.com", "senha123") is not None


# ==========================================================================
# VALIDACAO DE ENTRADA
#
# O prototipo anterior devolvia erro 500 quando alguem digitava texto no
# campo de peso. Nenhum destes casos pode derrubar o servidor.
# ==========================================================================

@pytest.mark.parametrize("campo, valor", [
    ("peso", "abc"),        # texto onde se espera numero
    ("peso", ""),           # vazio
    ("peso", "999"),        # fora da faixa fisiologica
    ("altura_cm", "1.75"),  # metros onde se espera centimetros
    ("bf", "150"),          # percentual impossivel
    ("sexo", "X"),          # opcao inexistente
    ("nivel_atividade", "hacker"),
    ("objetivo", "voar"),
])
def test_entrada_invalida_nao_derruba_o_servidor(cliente, campo, valor):
    entrar(cliente)
    dados = dict(DADOS_VALIDOS)
    dados[campo] = valor
    resposta = cliente.post("/", data=dados)
    assert resposta.status_code == 200, f"{campo}={valor!r} quebrou a pagina"


def test_peso_com_virgula_e_aceito(cliente):
    """O usuario brasileiro digita 80,5 - e isso precisa funcionar."""
    entrar(cliente)
    dados = dict(DADOS_VALIDOS, peso="80,5")
    resposta = cliente.post("/", data=dados)
    assert b"Gasto em repouso" in resposta.data


# ==========================================================================
# FLUXO DE CALCULO EM DUAS PARTES
# ==========================================================================

def test_parte_b_aparece_apos_calcular(cliente):
    entrar(cliente)
    resposta = cliente.post("/", data=DADOS_VALIDOS)
    assert resposta.status_code == 200
    assert b"Ajuste fino" in resposta.data
    assert b"Gerar meu card" in resposta.data


def test_sem_bf_usa_mifflin(cliente):
    entrar(cliente)
    dados = dict(DADOS_VALIDOS, bf="")
    resposta = cliente.post("/", data=dados)
    assert "Mifflin-St Jeor".encode() in resposta.data


def test_com_bf_usa_katch(cliente):
    entrar(cliente)
    resposta = cliente.post("/", data=DADOS_VALIDOS)
    assert b"Katch-McArdle" in resposta.data


def test_gerar_salva_registro_e_redireciona(cliente):
    entrar(cliente)
    dados = dict(DADOS_VALIDOS, etapa="gerar",
                 intensidade_calorica="20", fator_proteina="2.2",
                 fator_gordura="0.8", fator_agua="40", fator_fibras="14")
    resposta = cliente.post("/", data=dados)
    assert resposta.status_code == 302
    assert "/resultado/" in resposta.headers["Location"]

    perfil = banco.autenticar("gabriel@teste.com", "senha123")
    assert len(banco.listar_registros(perfil["id"])) == 1


def test_ajuste_do_usuario_e_gravado_como_escolhido(cliente):
    """O par padrao/escolhido e o que sustenta a analise do Capitulo 4."""
    entrar(cliente)
    dados = dict(DADOS_VALIDOS, etapa="gerar",
                 intensidade_calorica="15", fator_proteina="2.4",
                 fator_gordura="0.8", fator_agua="40", fator_fibras="14")
    cliente.post("/", data=dados)

    perfil = banco.autenticar("gabriel@teste.com", "senha123")
    registro = banco.listar_registros(perfil["id"])[0]
    assert registro["fator_proteina_padrao"] == 2.2
    assert registro["fator_proteina_usado"] == 2.4


def test_perfil_fixo_e_salvo_para_a_proxima_visita(cliente):
    entrar(cliente)
    cliente.post("/", data=DADOS_VALIDOS)
    perfil = banco.autenticar("gabriel@teste.com", "senha123")
    assert perfil["altura_cm"] == 175
    assert perfil["sexo"] == "M"


# ==========================================================================
# ISOLAMENTO ENTRE USUARIOS
# ==========================================================================

def test_usuario_nao_abre_resultado_de_outro(cliente):
    """Trocar o numero na barra de enderecos nao pode revelar o dado alheio."""
    outro = banco.criar_usuario("Outro", "outro@t.com", "senha123")
    plano = __import__("calculadora").montar_plano(
        peso=70, altura_cm=170, idade=25, sexo="F",
        nivel_atividade="leve", objetivo="manter")
    alheio = banco.salvar_registro(outro, 70, None, "leve", "manter", 3, plano)

    entrar(cliente)
    resposta = cliente.get(f"/resultado/{alheio}")
    assert resposta.status_code == 302     # redirecionado, nao exibido


def test_historico_mostra_apenas_os_proprios_calculos(cliente):
    entrar(cliente)
    cliente.post("/", data=dict(DADOS_VALIDOS, etapa="gerar",
                                intensidade_calorica="20", fator_proteina="2.2",
                                fator_gordura="0.8", fator_agua="40",
                                fator_fibras="14"))
    resposta = cliente.get("/historico")
    assert resposta.status_code == 200
    assert b"Perder gordura" in resposta.data


# ==========================================================================
# LGPD - EXCLUSAO DE CONTA
# ==========================================================================

def test_exclusao_exige_confirmacao_digitada(cliente):
    entrar(cliente)
    cliente.post("/conta", data={"confirmacao": "sim"})
    assert banco.autenticar("gabriel@teste.com", "senha123") is not None


def test_exclusao_confirmada_apaga_a_conta(cliente):
    entrar(cliente)
    resposta = cliente.post("/conta", data={"confirmacao": "EXCLUIR"})
    assert resposta.status_code == 302
    assert banco.autenticar("gabriel@teste.com", "senha123") is None


# ==========================================================================
# CARDAPIO
#
# Nenhum teste deste bloco chama a API. A IA e injetada por
# integracao_ia.gerar_cardapio(..., chamar=...), e aqui a rota e testada com
# o modulo substituido por um duble - o mesmo principio de
# test_integracao_ia.py: nao se testa o que o modelo responde, testa-se o que
# o sistema faz com a resposta.
# ==========================================================================

import calculadora
import importar_taco
import integracao_ia


@pytest.fixture
def cliente_com_taco(cliente):
    """Cliente logado, com a base real da TACO e um calculo ja gravado."""
    if not os.path.exists(importar_taco.CAMINHO_CSV):
        pytest.skip("CSV da TACO ausente")
    importar_taco.importar(caminho_banco=banco.CAMINHO_BANCO)
    entrar(cliente)
    return cliente


def gravar_calculo(restricoes="", preferencias=""):
    """Um registro pronto, sem passar pelo formulario."""
    usuario = banco.autenticar("gabriel@teste.com", "senha123")
    plano = calculadora.montar_plano(
        peso=80, altura_cm=175, idade=30, sexo="M",
        nivel_atividade="moderado", objetivo="perder", bf=20)
    return banco.salvar_registro(usuario["id"], 80, 20, "moderado", "perder",
                                 3, plano, restricoes=restricoes,
                                 preferencias=preferencias)


def ia_que_devolve(catalogo, quantidade=3, gramas=120):
    """Duble de IA: escolhe os primeiros alimentos do catalogo recebido."""
    codigos = [a["codigo_taco"] for a in catalogo[:quantidade]]
    resposta = {"refeicoes": [
        {"nome": "Almoço",
         "itens": [{"codigo_taco": c, "gramas": gramas} for c in codigos]},
    ]}
    return lambda prompt: resposta


def instalar_ia(monkeypatch, chamar):
    """Troca a chamada de rede pelo duble, sem tocar no resto do modulo."""
    real = integracao_ia.gerar_cardapio
    monkeypatch.setattr(
        aplicacao.integracao_ia, "gerar_cardapio",
        lambda *args, **kwargs: real(*args, **dict(kwargs, chamar=chamar)))


def test_restricoes_declaradas_sao_gravadas_com_o_calculo(cliente):
    """Sem isto a restricao se perderia entre a tela do calculo e a do
    cardapio, que sao requisicoes diferentes."""
    entrar(cliente)
    cliente.post("/", data=dict(DADOS_VALIDOS, etapa="gerar",
                                restricoes="lactose, camarão",
                                preferencias="frango grelhado",
                                intensidade_calorica="20", fator_proteina="2.2",
                                fator_gordura="0.8", fator_agua="40",
                                fator_fibras="14"))
    usuario = banco.autenticar("gabriel@teste.com", "senha123")
    registro = banco.listar_registros(usuario["id"])[0]
    assert registro["restricoes"] == "lactose, camarão"
    assert registro["preferencias"] == "frango grelhado"


def test_cardapio_so_e_gerado_por_quem_esta_logado(cliente):
    resposta = cliente.post("/cardapio/1")
    assert resposta.status_code == 302
    assert "/login" in resposta.headers["Location"]


def test_ninguem_gera_cardapio_no_registro_de_outro(cliente):
    outro = banco.criar_usuario("Outro", "outro@t.com", "senha123")
    plano = calculadora.montar_plano(peso=70, altura_cm=170, idade=25,
                                     sexo="F", nivel_atividade="leve",
                                     objetivo="manter")
    alheio = banco.salvar_registro(outro, 70, None, "leve", "manter", 3, plano)

    entrar(cliente)
    cliente.post(f"/cardapio/{alheio}")
    assert banco.buscar_cardapio(alheio) is None


def test_cardapio_e_gravado_e_aparece_na_tela(cliente_com_taco, monkeypatch):
    registro_id = gravar_calculo()
    instalar_ia(monkeypatch, ia_que_devolve(banco.buscar_catalogo()))

    resposta = cliente_com_taco.post(f"/cardapio/{registro_id}")
    assert resposta.status_code == 302

    cardapio = banco.buscar_cardapio(registro_id)
    assert cardapio is not None
    assert cardapio["refeicoes"][0]["nome"] == "Almoço"

    tela = cliente_com_taco.get(f"/resultado/{registro_id}")
    assert "Cardápio do dia" in tela.data.decode()


def test_cardapio_gravado_nao_e_regerado_ao_recarregar(cliente_com_taco, monkeypatch):
    """Um plano alimentar que muda sozinho a cada F5 nao e um plano - e cada
    F5 gastaria a cota compartilhada da API."""
    registro_id = gravar_calculo()
    chamadas = []

    def espiao(prompt):
        chamadas.append(prompt)
        return ia_que_devolve(banco.buscar_catalogo())(prompt)

    instalar_ia(monkeypatch, espiao)
    cliente_com_taco.post(f"/cardapio/{registro_id}")
    cliente_com_taco.get(f"/resultado/{registro_id}")
    cliente_com_taco.get(f"/resultado/{registro_id}")

    assert len(chamadas) == 1


def test_cardapio_respeita_a_restricao_declarada(cliente_com_taco, monkeypatch):
    """A propriedade de seguranca da rota: o catalogo enviado a IA e montado
    a partir do que ficou GRAVADO no registro, e nao do formulario."""
    registro_id = gravar_calculo(restricoes="lactose")
    permitidos = {a["codigo_taco"]
                  for a in banco.buscar_catalogo(restricoes=["lactose"])}

    instalar_ia(monkeypatch,
                ia_que_devolve(banco.buscar_catalogo(restricoes=["lactose"])))
    cliente_com_taco.post(f"/cardapio/{registro_id}")

    cardapio = banco.buscar_cardapio(registro_id)
    for refeicao in cardapio["refeicoes"]:
        for item in refeicao["itens"]:
            assert item["codigo_taco"] in permitidos


def test_falha_da_ia_nao_derruba_a_pagina(cliente_com_taco, monkeypatch):
    """Rede fora, cota estourada, modelo indisponivel: a pessoa continua
    vendo as metas dela, com um aviso."""
    registro_id = gravar_calculo()

    def explode(prompt):
        raise RuntimeError("API fora do ar")

    instalar_ia(monkeypatch, explode)
    resposta = cliente_com_taco.post(f"/cardapio/{registro_id}", follow_redirects=True)

    assert resposta.status_code == 200
    assert banco.buscar_cardapio(registro_id) is None
    assert "Suas metas diárias" in resposta.data.decode()


def test_limite_diario_protege_a_cota_da_api(cliente_com_taco, monkeypatch):
    registro_id = gravar_calculo()
    instalar_ia(monkeypatch, ia_que_devolve(banco.buscar_catalogo()))
    monkeypatch.setattr(aplicacao, "LIMITE_DIETAS_POR_DIA", 2)

    for _ in range(3):
        cliente_com_taco.post(f"/cardapio/{registro_id}")

    usuario = banco.autenticar("gabriel@teste.com", "senha123")
    assert banco.contar_eventos_hoje(usuario["id"], "dieta_gerada") == 2


def test_calcular_as_metas_nao_gasta_o_limite(cliente):
    """O calculo e aritmetica local: nao custa cota e nao pode ser limitado
    junto com a chamada a IA."""
    entrar(cliente)
    for _ in range(5):
        cliente.post("/", data=dict(DADOS_VALIDOS, etapa="gerar",
                                    intensidade_calorica="20",
                                    fator_proteina="2.2", fator_gordura="0.8",
                                    fator_agua="40", fator_fibras="14"))
    usuario = banco.autenticar("gabriel@teste.com", "senha123")
    assert banco.contar_eventos_hoje(usuario["id"], "dieta_gerada") == 0
    assert len(banco.listar_registros(usuario["id"])) == 5


# ==========================================================================
# SUBSTITUICAO PELA TELA
# ==========================================================================

def preparar_cardapio(cliente, monkeypatch, restricoes=""):
    """Gera um cardapio de teste e devolve o id do registro."""
    registro_id = gravar_calculo(restricoes=restricoes)
    termos = [t.strip() for t in restricoes.split(",") if t.strip()]
    instalar_ia(monkeypatch, ia_que_devolve(banco.buscar_catalogo(restricoes=termos)))
    cliente.post(f"/cardapio/{registro_id}")
    return registro_id


def test_troca_substitui_o_item_e_refaz_os_totais(cliente_com_taco, monkeypatch):
    registro_id = preparar_cardapio(cliente_com_taco, monkeypatch)
    antes = banco.buscar_cardapio(registro_id)

    tela = cliente_com_taco.get(f"/resultado/{registro_id}?trocar=0-0")
    assert "painel-troca" in tela.data.decode()

    item = antes["refeicoes"][0]["itens"][0]
    catalogo = banco.buscar_catalogo()
    base = next(a for a in catalogo if a["codigo_taco"] == item["codigo_taco"])
    import substituicao
    opcoes = substituicao.substitutos(base, item["gramas"], catalogo,
                                      limite=5, mesmo_grupo=False)
    if not opcoes:
        pytest.skip("sem alternativa para este alimento")

    cliente_com_taco.post(f"/substituir/{registro_id}",
                          data={"trocar": "0-0",
                                "codigo": str(opcoes[0]["codigo_taco"])})

    depois = banco.buscar_cardapio(registro_id)
    novo = depois["refeicoes"][0]["itens"][0]
    assert novo["codigo_taco"] == opcoes[0]["codigo_taco"]

    # O total da refeicao e refeito a partir dos itens, nunca corrigido por
    # diferenca: a tela nao pode mostrar um total que nao bate com a lista.
    soma = sum(i["kcal"] for i in depois["refeicoes"][0]["itens"])
    assert depois["refeicoes"][0]["totais"]["kcal"] == pytest.approx(soma)
    assert depois["substituicoes"] == 1


def test_troca_nao_reintroduz_alimento_proibido(cliente_com_taco, monkeypatch):
    """
    A propriedade de seguranca da tela de troca.

    O codigo chega pelo formulario, e formulario se altera. Se a rota
    aceitasse qualquer codigo enviado, a tela de substituicao viraria a porta
    para burlar a restricao alimentar declarada - justo no ponto em que a
    pessoa acha que so esta trocando um ingrediente.
    """
    registro_id = preparar_cardapio(cliente_com_taco, monkeypatch, restricoes="lactose")
    permitidos = {a["codigo_taco"]
                  for a in banco.buscar_catalogo(restricoes=["lactose"])}
    proibido = next(a["codigo_taco"] for a in banco.buscar_catalogo()
                    if a["codigo_taco"] not in permitidos)

    antes = banco.buscar_cardapio(registro_id)
    cliente_com_taco.post(f"/substituir/{registro_id}",
                          data={"trocar": "0-0", "codigo": str(proibido)})
    depois = banco.buscar_cardapio(registro_id)

    assert depois["refeicoes"][0]["itens"][0]["codigo_taco"] != proibido
    assert depois["refeicoes"][0] == antes["refeicoes"][0]
    assert depois["substituicoes"] == 0


def test_troca_com_indice_invalido_nao_quebra(cliente_com_taco, monkeypatch):
    registro_id = preparar_cardapio(cliente_com_taco, monkeypatch)
    for dados in ({"trocar": "9-9", "codigo": "1"},
                  {"trocar": "abacaxi", "codigo": "1"},
                  {"trocar": "0-0", "codigo": "nao-e-numero"},
                  {}):
        resposta = cliente_com_taco.post(f"/substituir/{registro_id}", data=dados)
        assert resposta.status_code == 302
    assert banco.buscar_cardapio(registro_id)["substituicoes"] == 0


def test_ninguem_troca_item_no_cardapio_de_outro(cliente_com_taco, monkeypatch):
    registro_id = preparar_cardapio(cliente_com_taco, monkeypatch)
    antes = banco.buscar_cardapio(registro_id)

    banco.criar_usuario("Outro", "outro@t.com", "senha123")
    cliente_com_taco.get("/logout")
    cliente_com_taco.post("/login", data={"email": "outro@t.com",
                                          "senha": "senha123"})
    cliente_com_taco.post(f"/substituir/{registro_id}",
                          data={"trocar": "0-0", "codigo": "1"})

    assert banco.buscar_cardapio(registro_id)["refeicoes"] == antes["refeicoes"]
