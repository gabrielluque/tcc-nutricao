"""
wsgi.py - Ponto de entrada do site no servidor.

No computador de desenvolvimento a aplicacao sobe com "python app.py", que
usa o servidor embutido do Flask. Esse servidor atende uma requisicao por
vez, nao lida bem com falhas e a propria documentacao do Flask diz para nao
usa-lo em producao.

No servidor quem atende as requisicoes e um servidor WSGI de verdade, e ele
nao executa "python app.py": ele procura, neste arquivo, um objeto chamado
"application". A ultima linha deste arquivo e o que entrega esse objeto.

--------------------------------------------------------------------------
A ORDEM DAS LINHAS IMPORTA
--------------------------------------------------------------------------
O app.py le as variaveis de ambiente no momento em que e importado. Se este
arquivo importasse a aplicacao antes de carregar o .env e antes de marcar
PRODUCAO, o site subiria com a chave de desenvolvimento e sem os cookies
seguros - exatamente o contrario do pretendido, e sem nenhum sinal visivel
de que algo esta errado.

Por isso a sequencia e: caminho, .env, PRODUCAO, e so entao a aplicacao.

--------------------------------------------------------------------------
INSTALACAO NO PYTHONANYWHERE
--------------------------------------------------------------------------
Este arquivo NAO e usado automaticamente. No painel do PythonAnywhere, em
Web > Code > WSGI configuration file, apague o conteudo que vem pronto e
cole o conteudo deste arquivo, trocando SEU_USUARIO pelo seu nome de
usuario.
"""

import os
import sys

# Pasta do projeto no servidor. Trocar SEU_USUARIO.
CAMINHO_PROJETO = "/home/SEU_USUARIO/tcc-nutricao"

if CAMINHO_PROJETO not in sys.path:
    sys.path.insert(0, CAMINHO_PROJETO)

# 1. Credenciais. O .env fica no servidor e nunca no GitHub.
from dotenv import load_dotenv                       # noqa: E402

load_dotenv(os.path.join(CAMINHO_PROJETO, ".env"))

# 2. Marca de producao, lida pelo app.py: exige a chave de sessao e liga os
#    cookies seguros.
os.environ["PRODUCAO"] = "1"

# 3. Agora sim a aplicacao. O nome "application" e o que o servidor procura.
from app import app as application                   # noqa: E402,F401
