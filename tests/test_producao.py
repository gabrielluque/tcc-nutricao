"""
test_producao.py - Testes da configuracao de producao.

Estes testes existem porque a diferenca entre o sistema seguro e o sistema
inseguro nao aparece na tela. Um site publicado com a chave de sessao
padrao funciona perfeitamente: as paginas abrem, o login entra, o calculo
sai. So que qualquer pessoa que conheca a chave - e ela esta no codigo
publico - consegue forjar o cookie de qualquer usuario e ler os dados de
saude alheios.

Como o defeito e invisivel, ele precisa de teste.

A tecnica e sempre a mesma: mexer nas variaveis de ambiente e reimportar o
app.py, porque e no momento da importacao que ele le a configuracao. Cada
teste devolve o ambiente ao estado anterior.

Execucao:
    pytest -v
"""

import importlib
import os
import tempfile

import pytest

import banco


def recarregar_app(**variaveis):
    """
    Reimporta o app.py com as variaveis de ambiente indicadas.

    Passar None remove a variavel. O banco e desviado para um arquivo
    temporario porque a importacao do app.py cria o esquema, e um teste
    nao deve tocar no banco de verdade.
    """
    antes = {nome: os.environ.get(nome) for nome in variaveis}
    caminho_original = banco.CAMINHO_BANCO
    banco.CAMINHO_BANCO = tempfile.mktemp(suffix=".db")

    for nome, valor in variaveis.items():
        if valor is None:
            os.environ.pop(nome, None)
        else:
            os.environ[nome] = valor

    try:
        import app
        return importlib.reload(app)
    finally:
        for nome, valor in antes.items():
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor
        if os.path.exists(banco.CAMINHO_BANCO):
            os.remove(banco.CAMINHO_BANCO)
        banco.CAMINHO_BANCO = caminho_original


def test_producao_sem_chave_recusa_subir():
    """
    O erro mais caro deste projeto seria publicar com a chave padrao.

    A aplicacao para na subida, de proposito. Um site que nao sobe e um
    problema de dez minutos; um site que sobe inseguro pode nunca ser
    percebido - e ele guarda peso, restricoes alimentares e historico de
    pessoas reais.
    """
    with pytest.raises(RuntimeError):
        recarregar_app(PRODUCAO="1", FLASK_SECRET_KEY=None)


def test_producao_com_chave_sobe():
    app = recarregar_app(PRODUCAO="1", FLASK_SECRET_KEY="chave-longa-de-teste")
    assert app.app.secret_key == "chave-longa-de-teste"


def test_desenvolvimento_sobe_sem_configuracao():
    """Clonar e rodar precisa continuar funcionando sem nenhum passo extra:
    e assim que a banca vai executar o projeto."""
    app = recarregar_app(PRODUCAO=None, FLASK_SECRET_KEY=None)
    assert app.app.secret_key == "desenvolvimento-apenas"


def test_cookie_so_viaja_por_https_em_producao():
    """Sem esta marca, o cookie de sessao atravessa a rede em texto claro no
    primeiro acesso por HTTP - o cenario do wi-fi compartilhado."""
    producao = recarregar_app(PRODUCAO="1", FLASK_SECRET_KEY="x" * 32)
    assert producao.app.config["SESSION_COOKIE_SECURE"] is True

    local = recarregar_app(PRODUCAO=None, FLASK_SECRET_KEY=None)
    assert local.app.config["SESSION_COOKIE_SECURE"] is False


def test_cookie_nao_e_visivel_para_javascript():
    app = recarregar_app(PRODUCAO=None, FLASK_SECRET_KEY=None)
    assert app.app.config["SESSION_COOKIE_HTTPONLY"] is True


def test_cookie_nao_acompanha_requisicao_de_outro_site():
    app = recarregar_app(PRODUCAO=None, FLASK_SECRET_KEY=None)
    assert app.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_envio_gigante_e_recusado():
    app = recarregar_app(PRODUCAO=None, FLASK_SECRET_KEY=None)
    assert app.app.config["MAX_CONTENT_LENGTH"] == 1024 * 1024


def test_o_caminho_do_banco_nao_depende_de_onde_o_comando_foi_digitado():
    """
    Regressao de um erro que so apareceria no servidor.

    Com o caminho relativo, o banco usado dependia da pasta atual: o
    processo do site nao inicia na pasta do projeto, e o site subiria com um
    banco novo e vazio enquanto o banco verdadeiro continuava ao lado, com
    todos os usuarios dentro.
    """
    assert os.path.isabs(banco.CAMINHO_BANCO)
