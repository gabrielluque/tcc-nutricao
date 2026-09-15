"""
banco.py - Camada de acesso a dados.

Todo o SQL do sistema vive neste arquivo. Nenhuma outra parte da aplicacao
abre conexao, escreve query ou conhece o nome de uma tabela. O app.py chama
funcoes com nomes de negocio - autenticar, buscar_catalogo, salvar_registro -
e nao sabe que existe um SQLite por baixo.

--------------------------------------------------------------------------
DECISOES DE PROJETO
--------------------------------------------------------------------------

1. ACESSO POR NOME, NUNCA POR POSICAO

   Todas as consultas usam sqlite3.Row, permitindo ler linha["peso"] em vez
   de linha[3]. Nao e estilo: e a correcao de uma classe inteira de erro. O
   prototipo anterior exibia todo o historico errado porque uma coluna foi
   inserida no meio da tabela e os indices numericos deslocaram uma posicao -
   a tela mostrava a data no lugar do peso sem gerar erro algum.

2. SENHAS NUNCA EM TEXTO PLANO

   Apenas o hash gerado por werkzeug.security e gravado. Nem o administrador
   do banco consegue ler a senha de um usuario.

3. RESTRICOES ALIMENTARES SAO FILTRO DE BANCO, NAO INSTRUCAO DE TEXTO

   Alimentos incompativeis com a restricao declarada sao removidos do
   catalogo ANTES de qualquer coisa ser enviada a IA. O modelo nunca ve o
   alimento proibido e portanto nao tem como sugeri-lo. Confiar na IA para
   "lembrar" de uma intolerancia seria transferir uma questao de seguranca
   alimentar para um componente probabilistico.

4. PADRAO E ESCOLHIDO GRAVADOS LADO A LADO

   Cada registro guarda, para todo parametro ajustavel, tanto o valor
   recomendado pelo sistema quanto o valor que o usuario efetivamente
   escolheu. Comparar as duas colunas responde com dados a pergunta central
   da hipotese do trabalho: as pessoas realmente usam a liberdade de ajuste
   que o sistema oferece?

5. LGPD - FINALIDADE, CONSENTIMENTO E ELIMINACAO

   O sistema coleta dados biometricos e preferencias alimentares, o que
   exige base legal. O consentimento e registrado no cadastro, com data.
   A funcao excluir_conta apaga o usuario e tudo que dele derive, atendendo
   ao direito de eliminacao previsto na Lei 13.709/2018.

6. TODA QUERY E PARAMETRIZADA

   Nenhum valor entra em SQL por concatenacao. Os placeholders "?" impedem
   injecao de SQL.
"""

import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

# Caminho do banco.
#
# E ABSOLUTO de proposito, ancorado na pasta deste arquivo. Com o caminho
# relativo "saude.db", o banco usado passa a depender de onde o comando foi
# digitado: rodar a partir da pasta de cima criava um segundo banco, vazio,
# e o sintoma era "meu usuario sumiu". No servidor isso seria pior - o
# processo do site nao inicia na pasta do projeto, e o site subiria com um
# banco novo em branco enquanto o verdadeiro continuava intacto ao lado.
#
# A variavel de ambiente CAMINHO_BANCO tem prioridade, para que o servidor
# possa guardar o arquivo fora da pasta do codigo.
CAMINHO_BANCO = os.environ.get(
    "CAMINHO_BANCO",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "saude.db"),
)


# ==========================================================================
# 1. ESQUEMA
#
# Definido em um unico lugar. O prototipo anterior tinha dois scripts
# criando a mesma tabela com colunas diferentes, e a divergencia entre eles
# foi a origem do bug do historico.
# ==========================================================================

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    nome               TEXT    NOT NULL,
    email              TEXT    NOT NULL UNIQUE,
    senha_hash         TEXT    NOT NULL,

    -- Perfil. Preenchido no primeiro uso e reaproveitado nas visitas
    -- seguintes: sao os dados que nao mudam de uma semana para a outra.
    -- Guardamos a data de nascimento, e nao a idade, porque idade
    -- armazenada envelhece silenciosamente e passa a alimentar o calculo
    -- metabolico com um valor errado.
    sexo               TEXT,
    altura_cm          REAL,
    data_nascimento    TEXT,

    consentiu_lgpd     INTEGER NOT NULL DEFAULT 0,
    consentimento_em   TEXT,
    criado_em          TEXT    NOT NULL
);

-- Composicao nutricional por 100 g, conforme a Tabela Brasileira de
-- Composicao de Alimentos (TACO).
CREATE TABLE IF NOT EXISTS alimentos (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_taco        INTEGER UNIQUE,
    nome               TEXT    NOT NULL,
    nome_normalizado   TEXT    NOT NULL,
    grupo              TEXT    NOT NULL,
    kcal               REAL    NOT NULL,
    proteina_g         REAL    NOT NULL,
    gordura_g          REAL    NOT NULL,
    carboidrato_g      REAL    NOT NULL,
    fibra_g            REAL    NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_alimentos_nome  ON alimentos (nome_normalizado);
CREATE INDEX IF NOT EXISTS idx_alimentos_grupo ON alimentos (grupo);

-- Historico: uma linha por calculo realizado.
--
-- As colunas terminadas em _padrao guardam o que o sistema recomendou; as
-- terminadas em _usado guardam o que o usuario escolheu. Sao gravadas em
-- par justamente para permitir medir o grau de personalizacao.
CREATE TABLE IF NOT EXISTS registros (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id                INTEGER NOT NULL,
    criado_em                 TEXT    NOT NULL,

    -- Entradas do usuario
    peso                      REAL    NOT NULL,
    bf                        REAL,
    nivel_atividade           TEXT    NOT NULL,
    objetivo                  TEXT    NOT NULL,
    refeicoes_por_dia         INTEGER NOT NULL,

    -- Parametros ajustaveis: recomendado x escolhido
    ajuste_calorico_padrao    REAL    NOT NULL,
    ajuste_calorico_usado     REAL    NOT NULL,
    fator_proteina_padrao     REAL    NOT NULL,
    fator_proteina_usado      REAL    NOT NULL,
    fator_gordura_padrao      REAL    NOT NULL,
    fator_gordura_usado       REAL    NOT NULL,
    fator_agua_padrao         REAL    NOT NULL,
    fator_agua_usado          REAL    NOT NULL,
    fator_fibras_padrao       REAL    NOT NULL,
    fator_fibras_usado        REAL    NOT NULL,

    -- Resultados calculados
    tmb                       REAL    NOT NULL,
    equacao_utilizada         TEXT    NOT NULL,
    get                       REAL    NOT NULL,
    meta_calorica             REAL    NOT NULL,
    proteina_g                REAL    NOT NULL,
    gordura_g                 REAL    NOT NULL,
    carboidrato_g             REAL    NOT NULL,
    agua_ml                   REAL    NOT NULL,
    fibras_g                  REAL    NOT NULL,

    FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_registros_usuario ON registros (usuario_id, criado_em);

-- Pedidos de alteracao do cardapio, em linguagem natural.
-- Material qualitativo do Capitulo 4: revela o que as pessoas mais querem
-- trocar e por que.
CREATE TABLE IF NOT EXISTS pedidos_ajuste (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    registro_id        INTEGER NOT NULL,
    ordem              INTEGER NOT NULL,
    texto              TEXT    NOT NULL,
    criado_em          TEXT    NOT NULL,
    FOREIGN KEY (registro_id) REFERENCES registros (id) ON DELETE CASCADE
);

-- Contadores de acao. Base do limite de uso da API de IA.
CREATE TABLE IF NOT EXISTS eventos (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id         INTEGER NOT NULL,
    tipo               TEXT    NOT NULL,
    detalhe            TEXT,
    criado_em          TEXT    NOT NULL,
    FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_eventos_usuario ON eventos (usuario_id, criado_em);
"""

# Lista fechada para evitar que rotulos livres poluam a analise.
EVENTOS_VALIDOS = {
    "cadastro", "login", "calculo", "dieta_gerada",
    "ajuste_pedido", "pdf_baixado",
}


# ==========================================================================
# 2. CONEXAO E UTILITARIOS
# ==========================================================================

@contextmanager
def conectar(caminho=None):
    """
    Abre conexao com commit em caso de sucesso, rollback em caso de erro e
    fechamento em qualquer situacao.

    O caminho e resolvido AQUI, e nao como valor padrao dos parametros. Em
    Python, o valor padrao de um argumento e avaliado uma unica vez, quando
    a funcao e definida: escrever "caminho=CAMINHO_BANCO" na assinatura
    congelaria o nome do arquivo no momento do import, e trocar
    banco.CAMINHO_BANCO depois nao teria efeito algum. Isso impediria os
    testes de apontar o modulo para um banco temporario - e impediria,
    igualmente, configurar o caminho por variavel de ambiente em producao.

    PRAGMA foreign_keys = ON e obrigatorio: o SQLite ignora chaves
    estrangeiras por padrao, e sem ele o ON DELETE CASCADE que sustenta a
    exclusao de conta simplesmente nao funcionaria.
    """
    conexao = sqlite3.connect(caminho or CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    try:
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()


def criar_esquema(caminho=None):
    """Cria todas as tabelas. Seguro executar mais de uma vez."""
    with conectar(caminho) as conexao:
        conexao.executescript(ESQUEMA)


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalizar(texto):
    """
    Remove acentos e coloca em minusculas.

    Faz com que "feijao" encontre "Feijão carioca" independentemente de como
    o usuario digitou. A versao normalizada e gravada junto do nome
    original: o original e exibido, o normalizado e pesquisado.
    """
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower().strip()


def calcular_idade(data_nascimento, hoje=None):
    """
    Idade em anos completos a partir da data de nascimento (ISO: AAAA-MM-DD).

    Derivar a idade em vez de armazena-la evita que o calculo metabolico
    passe a usar um valor desatualizado com o tempo.
    """
    if not data_nascimento:
        return None
    nascimento = date.fromisoformat(data_nascimento)
    hoje = hoje or date.today()
    return hoje.year - nascimento.year - (
        (hoje.month, hoje.day) < (nascimento.month, nascimento.day))


# ==========================================================================
# 3. USUARIOS, PERFIL E AUTENTICACAO
# ==========================================================================

class EmailJaCadastrado(Exception):
    """Tentativa de cadastro com e-mail que ja existe."""


def criar_usuario(nome, email, senha, consentiu_lgpd=False, caminho=None):
    """
    Cadastra um usuario e devolve o seu id.

    A senha vira hash antes de tocar o banco. O consentimento e gravado com
    data e hora, para que o registro tenha valor probatorio.
    """
    email = email.strip().lower()
    try:
        with conectar(caminho) as conexao:
            cursor = conexao.execute(
                """INSERT INTO usuarios
                   (nome, email, senha_hash, consentiu_lgpd, consentimento_em, criado_em)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (nome.strip(), email, generate_password_hash(senha),
                 1 if consentiu_lgpd else 0,
                 _agora() if consentiu_lgpd else None, _agora()),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError as erro:
        raise EmailJaCadastrado(f"O e-mail {email} já possui cadastro.") from erro


def autenticar(email, senha, caminho=None):
    """
    Verifica credenciais e devolve os dados do usuario, ou None.

    A comparacao usa check_password_hash, que confere a senha contra o hash
    sem nunca reverte-lo. Nao existe consulta "WHERE email = ? AND senha = ?" -
    essa forma exigiria a senha em texto plano no banco.

    E-mail inexistente e senha errada devolvem a MESMA resposta, para nao
    revelar quais e-mails possuem conta.
    """
    with conectar(caminho) as conexao:
        linha = conexao.execute(
            "SELECT * FROM usuarios WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()

    if linha is None or not check_password_hash(linha["senha_hash"], senha):
        return None
    return _montar_perfil(linha)


def _montar_perfil(linha):
    """Converte a linha de usuario em dicionario, sem expor o hash."""
    return {
        "id": linha["id"],
        "nome": linha["nome"],
        "email": linha["email"],
        "sexo": linha["sexo"],
        "altura_cm": linha["altura_cm"],
        "data_nascimento": linha["data_nascimento"],
        "idade": calcular_idade(linha["data_nascimento"]),
        "consentiu_lgpd": bool(linha["consentiu_lgpd"]),
    }


def buscar_perfil(usuario_id, caminho=None):
    with conectar(caminho) as conexao:
        linha = conexao.execute(
            "SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return _montar_perfil(linha) if linha else None


def atualizar_perfil(usuario_id, sexo=None, altura_cm=None,
                     data_nascimento=None, caminho=None):
    """
    Grava os dados que nao mudam entre visitas.

    Na segunda visita o usuario confirma apenas o peso; sexo, altura e data
    de nascimento ja vem preenchidos. Reduz o atrito de reuso, que e o que
    torna o historico util na pratica.
    """
    with conectar(caminho) as conexao:
        conexao.execute(
            """UPDATE usuarios SET
                   sexo            = COALESCE(?, sexo),
                   altura_cm       = COALESCE(?, altura_cm),
                   data_nascimento = COALESCE(?, data_nascimento)
               WHERE id = ?""",
            (sexo, altura_cm, data_nascimento, usuario_id),
        )


def excluir_conta(usuario_id, caminho=None):
    """
    Apaga o usuario e, em cascata, todos os seus registros, pedidos de
    ajuste e eventos.

    Implementa o direito de eliminacao do titular (Lei 13.709/2018, art. 18).
    A remocao e definitiva: nao ha copia nem marcacao de "inativo".
    """
    with conectar(caminho) as conexao:
        conexao.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))


# ==========================================================================
# 4. CATALOGO DE ALIMENTOS (TACO)
# ==========================================================================

# Mapeamento de restricoes declaradas para os termos procurados no nome dos
# alimentos.
#
# LIMITACAO CONHECIDA, a registrar no Capitulo 4: o filtro opera sobre o
# NOME do alimento, nao sobre uma classificacao formal de ingredientes. A
# TACO nao traz marcacao de alergenos, e construir essa taxonomia esta fora
# do escopo deste trabalho. O mapeamento cobre os casos mais comuns.
# Preparacoes compostas sao tratadas a parte, logo abaixo. Por isso a
# interface mostra ao usuario quais alimentos foram excluidos, permitindo
# conferencia.
RESTRICOES_CONHECIDAS = {
    "lactose": ["leite", "queijo", "iogurte", "requeijao", "manteiga",
                "creme de leite", "doce de leite", "coalhada", "ricota"],
    "gluten": ["trigo", "pao", "macarrao", "biscoito", "bolo", "cevada",
               "centeio", "farinha de rosca", "torrada"],
    "ovo": ["ovo", "omelete", "maionese"],
    "carne vermelha": ["boi", "bovina", "carne", "porco", "suina", "linguica"],
    "frutos do mar": ["camarao", "peixe", "atum", "sardinha", "lula", "marisco"],
    "vegetariano": ["boi", "bovina", "carne", "porco", "suina", "frango",
                    "peixe", "camarao", "linguica", "presunto"],
    "vegano": ["boi", "bovina", "carne", "porco", "suina", "frango", "peixe",
               "camarao", "linguica", "presunto", "leite", "queijo", "ovo",
               "iogurte", "manteiga", "mel"],
}


# Grupo da propria TACO que reune os pratos de varios ingredientes:
# estrogonofe, feijoada, vatapa, salpicao, yakisoba. Sao 32 itens, e a
# composicao deles nao esta em lugar nenhum da tabela. O motivo de existir
# esta constante esta explicado em buscar_catalogo.
GRUPO_PREPARADO = "Alimentos preparados"


def _restricao_declarada(restricoes):
    """Ha alguma restricao alimentar valida declarada?"""
    return bool(expandir_restricoes(restricoes))


def expandir_restricoes(restricoes):
    """
    Converte o que o usuario declarou em termos de busca.

    Restricao reconhecida ("lactose") vira a lista associada. Restricao
    desconhecida ("quiabo") e usada literalmente, o que permite excluir
    qualquer alimento pelo nome sem depender do dicionario.
    """
    termos = []
    for restricao in restricoes or []:
        chave = _normalizar(restricao)
        if not chave:
            continue
        termos.extend(RESTRICOES_CONHECIDAS.get(chave, [chave]))
    return [_normalizar(t) for t in termos]


def buscar_catalogo(restricoes=None, grupos=None, caminho=None):
    """
    Devolve os alimentos disponiveis para montar o cardapio.

    FRONTEIRA DE SEGURANCA DO SISTEMA. O que esta funcao nao devolve nunca
    chega a IA, e portanto nao pode aparecer na dieta do usuario. A restricao
    alimentar e aplicada aqui, em SQL, e nao como pedido em linguagem
    natural dentro do prompt.

    ----------------------------------------------------------------------
    POR QUE OS PRATOS PREPARADOS SAEM QUANDO HA QUALQUER RESTRICAO
    ----------------------------------------------------------------------
    O filtro por nome so enxerga o que o nome diz, e o nome de um prato nao
    diz seus ingredientes. Um teste real com a restricao "lactose" devolveu
    250 g de "Estrogonofe de carne" - que leva creme de leite. O filtro nao
    falhou: ele leu o nome, e no nome nao ha laticinio nenhum.

    A correcao nao pode ser acrescentar "estrogonofe" a lista de termos,
    porque a proxima preparacao que ninguem lembrou escaparia igual. A regra
    e outra, e vale para qualquer restricao:

        O SISTEMA NAO LIBERA O QUE NAO CONSEGUE VERIFICAR.

    Havendo qualquer restricao declarada, o grupo "Alimentos preparados" da
    TACO inteiro sai do catalogo. Sao 32 pratos de varios ingredientes -
    feijoada, vatapa, lasanha, salpicao -, e a composicao deles nao esta em
    lugar nenhum da tabela.

    Quem define o que e "preparacao composta" e a propria TACO, pela
    classificacao dela. Isso importa: o criterio e verificavel na fonte, e
    nao um julgamento meu sobre quais pratos parecem suspeitos.

    O preco e excluir junto alguns pratos inocentes, como a salada de
    legumes cozida no vapor. Numa restricao alimentar, errar para o lado de
    oferecer menos e a unica direcao aceitavel de erro. Quem nao declarou
    restricao nenhuma continua vendo a base inteira.
    """
    sql = "SELECT * FROM alimentos"
    condicoes, parametros = [], []

    for termo in expandir_restricoes(restricoes):
        condicoes.append("nome_normalizado NOT LIKE ?")
        parametros.append(f"%{termo}%")

    if _restricao_declarada(restricoes):
        condicoes.append("grupo <> ?")
        parametros.append(GRUPO_PREPARADO)

    if grupos:
        marcadores = ",".join("?" for _ in grupos)
        condicoes.append(f"grupo IN ({marcadores})")
        parametros.extend(grupos)

    if condicoes:
        sql += " WHERE " + " AND ".join(condicoes)
    sql += " ORDER BY grupo, nome"

    with conectar(caminho) as conexao:
        return [dict(linha) for linha in conexao.execute(sql, parametros)]


def listar_excluidos(restricoes, caminho=None):
    """
    Devolve os alimentos retirados do catalogo.

    Existe para transparencia: a interface mostra o que a restricao removeu,
    permitindo que o usuario perceba um filtro amplo demais - declarar
    "carne vermelha" tambem remove "carne de frango moida" - e corrija.

    Os pratos preparados entram nesta lista pelo mesmo motivo. Eles saem do
    catalogo por precaucao, nao por conterem o alergenio comprovadamente
    (ver buscar_catalogo), e o usuario tem direito de saber que a feijoada
    sumiu porque o sistema nao conhece a composicao dela - e nao porque ela
    tem lactose.
    """
    termos = expandir_restricoes(restricoes)
    if not termos:
        return []

    condicoes = [f"({' OR '.join('nome_normalizado LIKE ?' for _ in termos)})"]
    parametros = [f"%{t}%" for t in termos]

    condicoes.append("grupo = ?")
    parametros.append(GRUPO_PREPARADO)

    with conectar(caminho) as conexao:
        return [dict(linha) for linha in conexao.execute(
            f"SELECT * FROM alimentos WHERE {' OR '.join(condicoes)} "
            "ORDER BY nome", parametros)]


def inserir_alimento(codigo_taco, nome, grupo, kcal, proteina_g, gordura_g,
                     carboidrato_g, fibra_g=0.0, caminho=None):
    """Insere ou atualiza um alimento. Usado pelo importador da TACO."""
    with conectar(caminho) as conexao:
        cursor = conexao.execute(
            """INSERT OR REPLACE INTO alimentos
               (codigo_taco, nome, nome_normalizado, grupo,
                kcal, proteina_g, gordura_g, carboidrato_g, fibra_g)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (codigo_taco, nome, _normalizar(nome), grupo,
             kcal, proteina_g, gordura_g, carboidrato_g, fibra_g),
        )
        return cursor.lastrowid


def contar_alimentos(caminho=None):
    with conectar(caminho) as conexao:
        return conexao.execute("SELECT COUNT(*) AS n FROM alimentos").fetchone()["n"]


# ==========================================================================
# 5. HISTORICO DE CALCULOS
# ==========================================================================

def salvar_registro(usuario_id, peso, bf, nivel_atividade, objetivo,
                    refeicoes_por_dia, plano, caminho=None):
    """
    Grava um calculo completo e devolve o id do registro.

    Recebe o dicionario produzido por calculadora.montar_plano e extrai dele
    tanto os resultados quanto o par padrao/escolhido de cada parametro
    ajustavel. Essa duplicidade e intencional: sem o valor padrao gravado
    junto, seria impossivel saber depois se o usuario aceitou a recomendacao
    ou a alterou.
    """
    padroes = plano["padroes"]
    with conectar(caminho) as conexao:
        cursor = conexao.execute(
            """INSERT INTO registros (
                   usuario_id, criado_em,
                   peso, bf, nivel_atividade, objetivo, refeicoes_por_dia,
                   ajuste_calorico_padrao, ajuste_calorico_usado,
                   fator_proteina_padrao,  fator_proteina_usado,
                   fator_gordura_padrao,   fator_gordura_usado,
                   fator_agua_padrao,      fator_agua_usado,
                   fator_fibras_padrao,    fator_fibras_usado,
                   tmb, equacao_utilizada, get, meta_calorica,
                   proteina_g, gordura_g, carboidrato_g, agua_ml, fibras_g
               ) VALUES (?,?, ?,?,?,?,?, ?,?, ?,?, ?,?, ?,?, ?,?, ?,?,?,?, ?,?,?,?,?)""",
            (usuario_id, _agora(),
             peso, bf, nivel_atividade, objetivo, refeicoes_por_dia,
             padroes["ajuste_calorico"]["padrao"], plano["ajuste_calorico"],
             padroes["proteina"]["padrao"],        plano["fator_proteina"],
             padroes["gordura"]["padrao"],         plano["fator_gordura"],
             padroes["agua"]["padrao"],            plano["fator_agua"],
             padroes["fibras"]["padrao"],          plano["fator_fibras"],
             plano["tmb"], plano["equacao_utilizada"], plano["get"],
             plano["meta_calorica"], plano["proteina_g"], plano["gordura_g"],
             plano["carboidrato_g"], plano["agua_ml"], plano["fibras_g"]),
        )
        return cursor.lastrowid


def listar_registros(usuario_id, limite=50, caminho=None):
    """Historico do usuario, do mais recente para o mais antigo."""
    with conectar(caminho) as conexao:
        return [dict(linha) for linha in conexao.execute(
            """SELECT * FROM registros WHERE usuario_id = ?
               ORDER BY criado_em DESC, id DESC LIMIT ?""",
            (usuario_id, limite))]


def buscar_registro(registro_id, usuario_id=None, caminho=None):
    """
    Busca um registro especifico.

    Quando usuario_id e informado, a consulta so devolve o registro se ele
    pertencer aquele usuario. Isso impede que alguem veja o historico de
    outra pessoa trocando o numero na barra de enderecos.
    """
    sql = "SELECT * FROM registros WHERE id = ?"
    parametros = [registro_id]
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        parametros.append(usuario_id)

    with conectar(caminho) as conexao:
        linha = conexao.execute(sql, parametros).fetchone()
    return dict(linha) if linha else None


def evolucao_de_peso(usuario_id, caminho=None):
    """Serie temporal de peso, da mais antiga para a mais recente."""
    with conectar(caminho) as conexao:
        return [dict(linha) for linha in conexao.execute(
            """SELECT criado_em, peso, bf, meta_calorica FROM registros
               WHERE usuario_id = ? ORDER BY criado_em ASC""", (usuario_id,))]


# ==========================================================================
# 6. PEDIDOS DE AJUSTE DO CARDAPIO
# ==========================================================================

def salvar_pedido_ajuste(registro_id, texto, caminho=None):
    """
    Guarda um pedido de alteracao em linguagem natural.

    A ordem e atribuida automaticamente, preservando a sequencia da conversa.
    """
    with conectar(caminho) as conexao:
        proxima = conexao.execute(
            "SELECT COALESCE(MAX(ordem), 0) + 1 AS n FROM pedidos_ajuste WHERE registro_id = ?",
            (registro_id,)).fetchone()["n"]
        cursor = conexao.execute(
            "INSERT INTO pedidos_ajuste (registro_id, ordem, texto, criado_em) VALUES (?, ?, ?, ?)",
            (registro_id, proxima, texto.strip(), _agora()))
        return cursor.lastrowid


def listar_pedidos(registro_id, caminho=None):
    with conectar(caminho) as conexao:
        return [dict(linha) for linha in conexao.execute(
            "SELECT * FROM pedidos_ajuste WHERE registro_id = ? ORDER BY ordem",
            (registro_id,))]


# ==========================================================================
# 7. EVENTOS E LIMITE DE USO
# ==========================================================================

def registrar_evento(usuario_id, tipo, detalhe=None, caminho=None):
    """Registra uma acao. 'detalhe' aceita apenas rotulos curtos."""
    if tipo not in EVENTOS_VALIDOS:
        raise ValueError(
            f"Evento desconhecido: {tipo}. Válidos: {sorted(EVENTOS_VALIDOS)}")
    with conectar(caminho) as conexao:
        conexao.execute(
            "INSERT INTO eventos (usuario_id, tipo, detalhe, criado_em) VALUES (?, ?, ?, ?)",
            (usuario_id, tipo, detalhe, _agora()))


def contar_eventos_hoje(usuario_id, tipo, caminho=None):
    """
    Quantas vezes o usuario disparou este evento hoje (UTC).

    Base do limite de uso da API de IA: um site publico em cota gratuita
    esgota o limite diario se um unico usuario gerar dietas sem restricao,
    derrubando o sistema para os demais participantes do teste.
    """
    with conectar(caminho) as conexao:
        return conexao.execute(
            """SELECT COUNT(*) AS n FROM eventos
               WHERE usuario_id = ? AND tipo = ? AND date(criado_em) = date('now')""",
            (usuario_id, tipo)).fetchone()["n"]


# ==========================================================================
# 8. ANALISE PARA O CAPITULO 4
# ==========================================================================

def resumo_de_uso(caminho=None):
    """Totais agregados de uso do sistema."""
    with conectar(caminho) as conexao:
        por_tipo = {l["tipo"]: l["n"] for l in conexao.execute(
            "SELECT tipo, COUNT(*) AS n FROM eventos GROUP BY tipo")}
        participantes = conexao.execute(
            "SELECT COUNT(DISTINCT usuario_id) AS n FROM registros").fetchone()["n"]
        objetivos = {l["objetivo"]: l["n"] for l in conexao.execute(
            "SELECT objetivo, COUNT(*) AS n FROM registros GROUP BY objetivo")}
        total_registros = conexao.execute(
            "SELECT COUNT(*) AS n FROM registros").fetchone()["n"]
        refeicoes = {l["refeicoes_por_dia"]: l["n"] for l in conexao.execute(
            "SELECT refeicoes_por_dia, COUNT(*) AS n FROM registros GROUP BY refeicoes_por_dia")}

    return {
        "eventos_por_tipo": por_tipo,
        "participantes": participantes,
        "total_de_calculos": total_registros,
        "objetivos_escolhidos": objetivos,
        "refeicoes_por_dia": refeicoes,
    }


# Parametros ajustaveis e o par de colunas que os representa.
PARAMETROS_AJUSTAVEIS = {
    "ajuste_calorico": ("ajuste_calorico_padrao", "ajuste_calorico_usado"),
    "proteina":        ("fator_proteina_padrao",  "fator_proteina_usado"),
    "gordura":         ("fator_gordura_padrao",   "fator_gordura_usado"),
    "agua":            ("fator_agua_padrao",      "fator_agua_usado"),
    "fibras":          ("fator_fibras_padrao",    "fator_fibras_usado"),
}


def analise_de_personalizacao(caminho=None):
    """
    Mede quanto os usuarios alteram as recomendacoes do sistema.

    Este e o teste empirico da hipotese do trabalho. A hipotese afirma que
    permitir ajuste dinamico das metas confere maior autonomia ao usuario;
    se ninguem alterar nada, a afirmacao nao se sustenta - e isso tambem e
    um resultado legitimo a ser relatado.

    Devolve, para cada parametro:
        alteracoes      quantos registros divergem do padrao
        total           registros avaliados
        percentual      proporcao de registros alterados
        desvio_medio    media das diferencas, apenas entre os alterados
    """
    resultado = {}
    with conectar(caminho) as conexao:
        total = conexao.execute("SELECT COUNT(*) AS n FROM registros").fetchone()["n"]

        for nome, (col_padrao, col_usado) in PARAMETROS_AJUSTAVEIS.items():
            linha = conexao.execute(
                f"""SELECT COUNT(*) AS alteracoes,
                           AVG({col_usado} - {col_padrao}) AS desvio
                    FROM registros
                    WHERE ABS({col_usado} - {col_padrao}) > 1e-9"""
            ).fetchone()
            resultado[nome] = {
                "alteracoes": linha["alteracoes"],
                "total": total,
                "percentual": round(100 * linha["alteracoes"] / total, 1) if total else 0.0,
                "desvio_medio": round(linha["desvio"], 3) if linha["desvio"] is not None else None,
            }

        usuarios_que_ajustaram = conexao.execute(
            f"""SELECT COUNT(DISTINCT usuario_id) AS n FROM registros WHERE
                {' OR '.join(f'ABS({u} - {p}) > 1e-9' for p, u in PARAMETROS_AJUSTAVEIS.values())}"""
        ).fetchone()["n"]

        participantes = conexao.execute(
            "SELECT COUNT(DISTINCT usuario_id) AS n FROM registros").fetchone()["n"]

    return {
        "por_parametro": resultado,
        "usuarios_que_ajustaram": usuarios_que_ajustaram,
        "participantes": participantes,
        "percentual_de_usuarios": (
            round(100 * usuarios_que_ajustaram / participantes, 1) if participantes else 0.0),
    }


def pedidos_mais_comuns(limite=20, caminho=None):
    """
    Pedidos de ajuste de cardapio, para analise qualitativa no Capitulo 4.

    Sao devolvidos sem vinculo com o usuario: interessa o que foi pedido,
    nao quem pediu.
    """
    with conectar(caminho) as conexao:
        return [linha["texto"] for linha in conexao.execute(
            "SELECT texto FROM pedidos_ajuste ORDER BY criado_em DESC LIMIT ?",
            (limite,))]
