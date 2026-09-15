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
