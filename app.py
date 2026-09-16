"""
app.py - Roteamento da aplicacao web.

Este arquivo faz UMA coisa: recebe requisicoes HTTP, chama as funcoes certas
e devolve paginas. Nao contem nenhuma formula nutricional e nenhum SQL.

    calculadora.py  ->  toda a matematica
    banco.py        ->  todo o acesso a dados
    app.py          ->  apenas o caminho entre o navegador e os dois acima

Essa divisao e o que permite testar a regra de negocio sem subir servidor
(ver tests/), e e o que a secao 3.3 do trabalho descreve.

--------------------------------------------------------------------------
A PAGINA PRINCIPAL TEM DUAS PARTES
--------------------------------------------------------------------------
A tela de calculo e uma pagina so, revelada em duas etapas:

    Parte A   perfil, objetivo, rotina, restricoes    -> [Calcular]
    Parte B   TMB e GET ja calculados + controles     -> [Gerar dieta]
              deslizantes de ajuste fino

A Parte B aparece apos um POST comum, sem JavaScript. Calcular no navegador
exigiria reescrever as formulas em JS, criando duas fontes de verdade para o
mesmo numero - exatamente o que a secao 3.5 do trabalho diz que o sistema
nao faz.

Os valores da Parte A viajam para a Parte B como campos ocultos. Assim o
servidor nao precisa guardar estado entre requisicoes.
"""

import os
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for)

import banco
import calculadora
import integracao_ia
import substituicao

load_dotenv()

app = Flask(__name__)

# --------------------------------------------------------------------------
# CONFIGURACAO: DESENVOLVIMENTO x PRODUCAO
#
# O sistema roda em duas situacoes muito diferentes. Na maquina do
# desenvolvedor ele precisa subir logo apos o clone, sem configuracao
# nenhuma. No servidor, com voluntarios reais criando conta e informando
# peso e restricoes alimentares, as mesmas facilidades viram falhas de
# seguranca.
#
# PRODUCAO=1 e o que separa os dois mundos. Ele e definido no servidor, no
# arquivo wsgi.py.
# --------------------------------------------------------------------------

EM_PRODUCAO = os.environ.get("PRODUCAO") == "1"

chave = os.environ.get("FLASK_SECRET_KEY")

if not chave:
    if EM_PRODUCAO:
        # Falhar aqui, na subida, e deliberado. A chave assina os cookies de
        # sessao: com um valor publico e conhecido, qualquer pessoa forja o
        # cookie de qualquer usuario e le os dados de saude alheios. Um site
        # que sobe quebrado e visivel na hora; um site que sobe inseguro so
        # aparece depois, e talvez nunca.
        raise RuntimeError(
            "FLASK_SECRET_KEY nao definida. Em producao ela e obrigatoria. "
            "Gere uma com: python -c \"import secrets; "
            "print(secrets.token_hex(32))\""
        )
    chave = "desenvolvimento-apenas"

app.secret_key = chave

app.config.update(
    # O cookie de sessao nunca e lido por JavaScript. Fecha a porta para que
    # um script injetado numa pagina roube a sessao de quem esta logado.
    SESSION_COOKIE_HTTPONLY=True,

    # Em producao o cookie so viaja por HTTPS. Sem isso ele atravessaria a
    # rede em texto claro no primeiro acesso por HTTP - e o wi-fi da
    # faculdade e exatamente o cenario em que isso acontece.
    SESSION_COOKIE_SECURE=EM_PRODUCAO,

    # O cookie nao acompanha requisicoes vindas de outros sites, o que
    # neutraliza o ataque em que uma pagina qualquer envia um formulario
    # para a nossa aplicacao usando a sessao de quem esta logado.
    SESSION_COOKIE_SAMESITE="Lax",

    # Tamanho maximo do corpo de uma requisicao: 1 MB. Os formularios do
    # sistema sao pequenos; o limite evita que alguem prenda o servidor
    # enviando um envio gigante.
    MAX_CONTENT_LENGTH=1024 * 1024,
)

# Quantos cardapios uma pessoa pode gerar por dia.
#
# O limite protege a cota gratuita da API do Gemini, que e compartilhada por
# todos os voluntarios: sem ele, uma unica pessoa clicando em "gerar" vinte
# vezes derruba o teste para os outros vinte e quatro.
#
# Note onde ele NAO esta: o calculo das metas nao tem limite nenhum, porque
# nao custa nada - e aritmetica local. So a chamada a IA e contada.
LIMITE_DIETAS_POR_DIA = int(os.environ.get("LIMITE_DIETAS_POR_DIA", 10))

# Quantas alternativas mostrar ao trocar um alimento. Cinco cabem na tela sem
# rolagem e ja cobrem as opcoes plausiveis; mais do que isso vira catalogo.
LIMITE_SUBSTITUTOS = 5

# Garante que as tabelas existam antes de a primeira requisicao chegar.
#
# Sem isto, a aplicacao sobe normalmente e so quebra quando alguem tenta
# fazer login: o sqlite3.connect() CRIA o arquivo do banco caso ele nao
# exista, mas cria vazio, sem tabela alguma. O sintoma e enganoso - o
# arquivo saude.db aparece na pasta, e mesmo assim o erro diz
# "no such table: usuarios".
#
# A chamada usa CREATE TABLE IF NOT EXISTS, entao e segura a cada reinicio
# e nunca apaga dado existente. O efeito pratico e que a aplicacao passa a
# se instalar sozinha: clonar e rodar basta, sem passo manual esquecivel -
# o que importa especialmente no dia da publicacao, com voluntarios
# tentando acessar.
banco.criar_esquema()


# ==========================================================================
# 1. AUTENTICACAO
# ==========================================================================

def exige_login(rota):
    """
    Bloqueia o acesso de quem nao esta autenticado.

    Aplicado como decorador, garante que a verificacao nunca seja esquecida
    em uma rota nova - diferente de repetir um "if" no inicio de cada
    funcao, que e facil de omitir por descuido.
    """
    @wraps(rota)
    def verificar(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return rota(*args, **kwargs)
    return verificar


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip()
        senha = request.form.get("senha", "")
        consentiu = request.form.get("consentimento") == "sim"

        erros = []
        if len(nome) < 2:
            erros.append("Informe seu nome.")
        if "@" not in email:
            erros.append("Informe um e-mail válido.")
        if len(senha) < 6:
            erros.append("A senha precisa ter pelo menos 6 caracteres.")
        if not consentiu:
            erros.append("É necessário aceitar o uso dos dados para prosseguir.")

        if not erros:
            try:
                banco.criar_usuario(nome, email, senha, consentiu_lgpd=True)
                flash("Conta criada. Faça login para continuar.", "sucesso")
                return redirect(url_for("login"))
            except banco.EmailJaCadastrado:
                erros.append("Este e-mail já possui cadastro.")

        return render_template("cadastro.html", erros=erros,
                               nome=nome, email=email)

    return render_template("cadastro.html", erros=[])


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "")
        senha = request.form.get("senha", "")
        usuario = banco.autenticar(email, senha)

        if usuario is None:
            # Mensagem unica de proposito: dizer "este e-mail nao existe"
            # transformaria a tela de login em uma ferramenta para descobrir
            # quem tem conta no sistema.
            return render_template("login.html",
                                   erro="E-mail ou senha incorretos.",
                                   email=email)

        session["usuario_id"] = usuario["id"]
        session["usuario_nome"] = usuario["nome"]
        session.permanent = request.form.get("lembrar") == "sim"
        banco.registrar_evento(usuario["id"], "login")
        return redirect(url_for("calcular"))

    return render_template("login.html", erro=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ==========================================================================
# 2. VALIDACAO DE ENTRADA
#
# O prototipo anterior derrubava o servidor com erro 500 quando alguem
# digitava texto no campo de peso: float("abc") levanta ValueError e nada
# tratava isso. Aqui a conversao acontece em um unico lugar, que acumula
# mensagens legiveis em vez de interromper a execucao.
# ==========================================================================

def ler_numero(campo, rotulo, minimo, maximo, erros, obrigatorio=True):
    """
    Le um campo numerico do formulario, validando faixa e formato.

    Aceita virgula como separador decimal, porque e assim que o usuario
    brasileiro digita. Devolve None quando o campo e opcional e vazio.
    """
    bruto = request.form.get(campo, "").strip().replace(",", ".")

    if not bruto:
        if obrigatorio:
            erros.append(f"Informe {rotulo}.")
        return None

    try:
        valor = float(bruto)
    except ValueError:
        erros.append(f"{rotulo.capitalize()} precisa ser um número.")
        return None

    if not (minimo <= valor <= maximo):
        erros.append(f"{rotulo.capitalize()} deve estar entre {minimo:g} e {maximo:g}.")
        return None

    return valor


def ler_opcao(campo, rotulo, validas, erros):
    """Le um campo de escolha, recusando valores fora da lista permitida."""
    valor = request.form.get(campo, "")
    if valor not in validas:
        erros.append(f"Escolha {rotulo}.")
        return None
    return valor


def ler_lista(campo):
    """
    Converte texto livre separado por virgulas em lista de termos.

    Usado nas restricoes alimentares. Termos vazios sao descartados.
    """
    bruto = request.form.get(campo, "")
    return [t.strip() for t in bruto.split(",") if t.strip()]


# ==========================================================================
# 3. TELA PRINCIPAL DE CALCULO
# ==========================================================================

@app.route("/", methods=["GET", "POST"])
@exige_login
def calcular():
    perfil = banco.buscar_perfil(session["usuario_id"])

    if request.method == "GET":
        return render_template("index.html", perfil=perfil,
                               atividades=calculadora.FATORES_ATIVIDADE,
                               objetivos=calculadora.OBJETIVOS,
                               plano=None, erros=[])

    erros = []

    # --- Parte A: perfil e objetivo -------------------------------------
    sexo = ler_opcao("sexo", "o sexo", {"M", "F"}, erros)
    data_nascimento = request.form.get("data_nascimento", "").strip()
    idade = banco.calcular_idade(data_nascimento) if data_nascimento else None
    if idade is None or not (14 <= idade <= 100):
        erros.append("Informe uma data de nascimento válida.")

    altura_cm = ler_numero("altura_cm", "a altura em centímetros", 120, 230, erros)
    peso = ler_numero("peso", "o peso em quilos", 30, 300, erros)
    bf = ler_numero("bf", "o percentual de gordura", 3, 70, erros, obrigatorio=False)

    nivel = ler_opcao("nivel_atividade", "o nível de atividade",
                      set(calculadora.FATORES_ATIVIDADE), erros)
    objetivo = ler_opcao("objetivo", "o objetivo",
                         set(calculadora.OBJETIVOS), erros)
    # A faixa vai de 1 a 6 porque e isso que a tela oferece. O prototipo
    # aceitava ate 8, mas exigia no minimo 2 - quem faz uma refeicao unica
    # por dia (jejum intermitente, turno da noite) via um erro sem motivo.
    refeicoes = ler_numero("refeicoes_por_dia", "o número de refeições", 1, 6, erros)

    restricoes = ler_lista("restricoes")
    preferencias = request.form.get("preferencias", "").strip()

    if erros:
        return render_template("index.html", perfil=perfil,
                               atividades=calculadora.FATORES_ATIVIDADE,
                               objetivos=calculadora.OBJETIVOS,
                               plano=None, erros=erros, form=request.form)

    # O perfil fixo e gravado para que a proxima visita ja venha preenchido.
    banco.atualizar_perfil(session["usuario_id"], sexo=sexo,
                           altura_cm=altura_cm, data_nascimento=data_nascimento)

    # --- Parte B: ajustes finos -----------------------------------------
    # Ausentes no primeiro POST (o usuario acabou de clicar em "Calcular"),
    # presentes a partir do segundo, quando os controles ja foram exibidos.
    # A condicao olha para a presenca do campo, e nao para a etapa: o botao
    # "Recalcular com os ajustes" tambem envia etapa=calcular, e precisa
    # respeitar o que o usuario acabou de arrastar.
    etapa = request.form.get("etapa", "calcular")
    ajustes = {}
    if "intensidade_calorica" in request.form:
        for campo, rotulo, minimo, maximo in [
            ("fator_proteina", "o fator de proteína", 1.6, 2.4),
            ("fator_gordura", "o fator de gordura", 0.5, 1.5),
            ("fator_agua", "o fator de hidratação", 25, 65),
            ("fator_fibras", "o fator de fibras", 10, 20),
        ]:
            ajustes[campo] = ler_numero(campo, rotulo, minimo, maximo, erros,
                                        obrigatorio=False)

        # O controle calorico chega SEMPRE positivo, porque um deslizante que
        # vai de -25 a -10 colocaria o deficit mais agressivo na esquerda e
        # inverteria a intuicao de "arrastar para a direita intensifica".
        # A calculadora devolve o sinal conforme o objetivo escolhido.
        intensidade = ler_numero("intensidade_calorica", "a intensidade",
                                 0, 25, erros, obrigatorio=False)
        if intensidade is not None:
            ajustes["ajuste_calorico"] = calculadora.ajuste_assinado(
                objetivo, intensidade)

    plano = calculadora.montar_plano(
        peso=peso, altura_cm=altura_cm, idade=idade, sexo=sexo,
        nivel_atividade=nivel, objetivo=objetivo, bf=bf, **ajustes)

    # --- Gravacao --------------------------------------------------------
    #
    # O calculo em si nao tem limite de uso: e aritmetica local, nao custa
    # cota nenhuma. O limite diario vive na rota que chama a IA.
    if etapa == "gerar" and not erros:
        registro_id = banco.salvar_registro(
            session["usuario_id"], peso, bf, nivel, objetivo,
            int(refeicoes), plano,
            restricoes=", ".join(restricoes), preferencias=preferencias)
        banco.registrar_evento(session["usuario_id"], "calculo", objetivo)
        return redirect(url_for("resultado", registro_id=registro_id))

    return render_template("index.html", perfil=perfil,
                           atividades=calculadora.FATORES_ATIVIDADE,
                           objetivos=calculadora.OBJETIVOS,
                           plano=plano, erros=erros, form=request.form,
                           restricoes_texto=", ".join(restricoes),
                           preferencias=preferencias)


@app.route("/resultado/<int:registro_id>")
@exige_login
def resultado(registro_id):
    """
    Exibe um calculo gravado.

    A busca passa o usuario_id, de modo que trocar o numero na barra de
    enderecos nao revela o resultado de outra pessoa.
    """
    registro = banco.buscar_registro(registro_id, usuario_id=session["usuario_id"])
    if registro is None:
        return redirect(url_for("calcular"))

    cardapio = banco.buscar_cardapio(registro_id)

    # "trocar=2-0" quer dizer: mostre as alternativas para o primeiro item da
    # terceira refeicao. Vem pela URL, e nao por JavaScript, para que a lista
    # de trocas seja montada pelo servidor - e para que o sistema continue
    # funcionando com o JavaScript desligado, como o resto das telas.
    troca, alternativas, item_trocado = request.args.get("trocar"), [], None
    if cardapio and troca:
        item_trocado, alternativas = _alternativas_para(registro, cardapio, troca)

    return render_template("resultado.html", registro=registro,
                           cardapio=cardapio,
                           alimentos_liberados=_catalogo_do(registro, contar=True),
                           troca=troca, item_trocado=item_trocado,
                           alternativas=alternativas)


# ==========================================================================
# 4. CARDAPIO
#
# Aqui esta a unica parte do sistema que fala com a IA, e ela e deliberadamente
# uma rota separada do calculo. Tres motivos:
#
#   1. O calculo das metas e instantaneo e nunca falha; a chamada a IA demora
#      alguns segundos e pode falhar (rede, cota, modelo fora do ar). Separar
#      significa que uma coisa quebrada nao leva a outra junto: quem nao
#      conseguiu o cardapio ainda ve suas metas na tela.
#   2. O cardapio fica GRAVADO. Voltar na pagina mostra o mesmo cardapio, e
#      nao um novo a cada F5 - um plano alimentar que muda sozinho nao e um
#      plano, e cada F5 gastaria a cota compartilhada.
#   3. O limite diario fica em um lugar so, na porta da API.
# ==========================================================================

def _restricoes_do(registro):
    """As restricoes do registro, como lista de termos."""
    return [t.strip() for t in (registro["restricoes"] or "").split(",")
            if t.strip()]


def _catalogo_do(registro, contar=False):
    """
    Os alimentos liberados para este registro.

    FRONTEIRA DE SEGURANCA: tudo que a IA ve e tudo que a substituicao oferece
    sai daqui. Uma unica funcao, chamada por todas as rotas, para que nao
    exista caminho no sistema que monte a lista de outro jeito.
    """
    catalogo = banco.buscar_catalogo(restricoes=_restricoes_do(registro))
    return len(catalogo) if contar else catalogo


def _alternativas_para(registro, cardapio, troca):
    """
    Opcoes de troca para um item, no formato "refeicao-item".

    Devolve (item_original, lista_de_alternativas). Qualquer indice invalido
    devolve lista vazia em vez de erro: o parametro vem da URL, e a URL e do
    usuario.
    """
    try:
        indice_refeicao, indice_item = (int(n) for n in troca.split("-", 1))
    except (ValueError, AttributeError):
        return None, []

    item = _item_do_cardapio(cardapio, indice_refeicao, indice_item)
    if item is None:
        return None, []

    catalogo = _catalogo_do(registro)
    base = next((a for a in catalogo
                 if a["codigo_taco"] == item.get("codigo_taco")), None)
    if base is None:
        return item, []

    # O motor recebe o alimento POR 100 g (a linha da TACO) e a quantidade da
    # porcao. Passar o item do cardapio direto daria numeros errados: nele os
    # valores ja estao multiplicados pela porcao.
    alternativas = substituicao.substitutos(
        base, item["gramas"], catalogo,
        limite=LIMITE_SUBSTITUTOS, mesmo_grupo=False)

    for alternativa in alternativas:
        alternativa["explicacao"] = substituicao.explicar(item, alternativa)
    return item, alternativas


def _item_do_cardapio(cardapio, indice_refeicao, indice_item):
    """Um item pelo par de indices, ou None se qualquer um estiver fora."""
    refeicoes = cardapio.get("refeicoes", [])
    if not (0 <= indice_refeicao < len(refeicoes)):
        return None
    itens = refeicoes[indice_refeicao].get("itens", [])
    if not (0 <= indice_item < len(itens)):
        return None
    return itens[indice_item]


@app.route("/cardapio/<int:registro_id>", methods=["POST"])
@exige_login
def gerar_cardapio(registro_id):
    """Monta o cardapio do dia com a IA e grava o resultado."""
    registro = banco.buscar_registro(registro_id, usuario_id=session["usuario_id"])
    if registro is None:
        return redirect(url_for("calcular"))

    usados_hoje = banco.contar_eventos_hoje(session["usuario_id"], "dieta_gerada")
    if usados_hoje >= LIMITE_DIETAS_POR_DIA:
        flash(f"Você já gerou {LIMITE_DIETAS_POR_DIA} cardápios hoje. "
              "O limite existe para que a cota da ferramenta dure para todos "
              "os participantes. Tente de novo amanhã.", "erro")
        return redirect(url_for("resultado", registro_id=registro_id))

    catalogo = _catalogo_do(registro)
    if not catalogo:
        flash("Suas restrições não deixaram nenhum alimento disponível. "
              "Refaça o cálculo declarando menos restrições.", "erro")
        return redirect(url_for("resultado", registro_id=registro_id))

    try:
        cardapio = integracao_ia.gerar_cardapio(
            registro, int(registro["refeicoes_por_dia"]), catalogo,
            preferencias=registro["preferencias"] or "")
    except Exception:
        # A captura e ampla de proposito: rede, cota, formato de resposta e
        # indisponibilidade do modelo chegam aqui como excecoes diferentes, e
        # a resposta ao usuario e a mesma em todos os casos. O erro vai
        # inteiro para o log do servidor - engolir em silencio seria o
        # problema; engolir registrando, nao.
        app.logger.exception("falha ao gerar cardápio do registro %s", registro_id)
        flash("Não consegui montar seu cardápio agora. Suas metas continuam "
              "salvas — tente gerar de novo em alguns instantes.", "erro")
        return redirect(url_for("resultado", registro_id=registro_id))

    banco.salvar_cardapio(registro_id, cardapio)
    banco.registrar_evento(session["usuario_id"], "dieta_gerada")
    return redirect(url_for("resultado", registro_id=registro_id))


@app.route("/substituir/<int:registro_id>", methods=["POST"])
@exige_login
def substituir(registro_id):
    """
    Troca um item do cardapio por um equivalente e regrava o cardapio.

    O codigo escolhido e conferido contra a lista que o motor acabou de
    oferecer, e nao aceito porque veio no formulario. Sem essa conferencia,
    bastaria alterar o valor enviado para reintroduzir no prato um alimento
    que a restricao havia excluido - a tela seria uma porta de entrada para
    burlar a propria barreira de seguranca do sistema.
    """
    registro = banco.buscar_registro(registro_id, usuario_id=session["usuario_id"])
    cardapio = banco.buscar_cardapio(registro_id)
    if registro is None or cardapio is None:
        return redirect(url_for("calcular"))

    troca = request.form.get("trocar", "")
    item, alternativas = _alternativas_para(registro, cardapio, troca)

    escolhido = None
    if item is not None:
        codigo = request.form.get("codigo", "")
        escolhido = next((a for a in alternativas
                          if str(a["codigo_taco"]) == codigo), None)

    if escolhido is None:
        flash("Essa troca não está mais disponível.", "erro")
        return redirect(url_for("resultado", registro_id=registro_id))

    indice_refeicao, indice_item = (int(n) for n in troca.split("-", 1))
    refeicao = cardapio["refeicoes"][indice_refeicao]
    refeicao["itens"][indice_item] = {
        chave: valor for chave, valor in escolhido.items()
        if chave not in ("distancia", "explicacao")
    }

    # Os totais sao refeitos, nunca corrigidos por diferenca: somar de novo a
    # partir dos itens e o que garante que a tela nunca mostre um total que
    # nao corresponde ao que esta listado abaixo dele.
    refeicao["totais"] = integracao_ia.somar(refeicao["itens"])
    cardapio["totais"] = integracao_ia.somar(
        [i for r in cardapio["refeicoes"] for i in r["itens"]])
    cardapio["comparacao"] = integracao_ia.comparar_com_as_metas(
        cardapio["totais"], registro)

    banco.registrar_substituicao(registro_id, cardapio)
    banco.registrar_evento(session["usuario_id"], "ajuste_pedido", "substituicao")
    flash(f"Trocado por {escolhido['alimento']}.", "sucesso")
    return redirect(url_for("resultado", registro_id=registro_id))


# ==========================================================================
# 5. HISTORICO E CONTA
# ==========================================================================

@app.route("/historico")
@exige_login
def historico():
    registros = banco.listar_registros(session["usuario_id"])
    return render_template("historico.html", registros=registros)


@app.route("/conta", methods=["GET", "POST"])
@exige_login
def conta():
    """
    Pagina da conta, com a exclusao definitiva dos dados.

    Implementa o direito de eliminacao previsto no art. 18 da LGPD. A
    confirmacao por digitacao existe para que a acao nunca seja acionada
    por um clique acidental.
    """
    if request.method == "POST":
        if request.form.get("confirmacao", "").strip().upper() == "EXCLUIR":
            banco.excluir_conta(session["usuario_id"])
            session.clear()
            flash("Sua conta e todos os seus dados foram excluídos.", "sucesso")
            return redirect(url_for("login"))
        flash('Digite EXCLUIR para confirmar.', "erro")

    return render_template("conta.html",
                           perfil=banco.buscar_perfil(session["usuario_id"]))


if __name__ == "__main__":
    # debug=True NUNCA em producao: a pagina de erro do Flask expõe o
    # codigo-fonte e permite execucao de comandos no servidor.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5000)
