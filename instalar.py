"""
instalar.py - Deixa o sistema pronto para uso, em um comando.

    python instalar.py

Faz tres coisas, nesta ordem: confere a configuracao, cria as tabelas e
carrega a Tabela TACO. Seguro repetir quantas vezes quiser - o esquema usa
CREATE TABLE IF NOT EXISTS e o importador atualiza os alimentos pelo codigo
da TACO em vez de duplica-los. Nenhuma conta de usuario e apagada.

Existe porque a sequencia de instalacao era um passo manual esquecivel, e
esquecer um deles produz sintomas que nao se parecem com a causa: sem o
esquema, o erro fala em "no such table"; sem a TACO, a base de alimentos
fica vazia e o cardapio sai sem comida. No dia da publicacao, com
voluntarios tentando acessar, esse nao e o momento de descobrir qual dos
passos ficou para tras.
"""

import os
import secrets
import sys

import banco
import importar_taco


def conferir_configuracao():
    """
    Avisa sobre o que impede o sistema de funcionar direito.

    Nao interrompe a instalacao: o banco pode ser preparado antes de a
    chave existir. Mas avisa alto, porque uma chave de sessao ausente em
    producao e uma falha de seguranca, e nao um detalhe de configuracao.
    """
    avisos = []

    if not os.path.exists(".env"):
        avisos.append(
            "Arquivo .env nao encontrado.\n"
            "      Copie o modelo:  cp .env.example .env\n"
            "      (no Windows:     copy .env.example .env)"
        )

    if not os.environ.get("FLASK_SECRET_KEY"):
        avisos.append(
            "FLASK_SECRET_KEY nao definida.\n"
            "      Use esta, que acabei de gerar:\n"
            f"      FLASK_SECRET_KEY={secrets.token_hex(32)}"
        )

    if not os.environ.get("GEMINI_API_KEY"):
        avisos.append(
            "GEMINI_API_KEY nao definida.\n"
            "      O site funciona sem ela ate a etapa do cardapio.\n"
            "      Obtenha em https://aistudio.google.com/apikey"
        )

    return avisos


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("Dependencias ausentes. Rode antes:")
        print("    pip install -r requirements.txt")
        return 1

    print()
    print("  Preparando o sistema")
    print("  " + "-" * 56)

    banco.criar_esquema()
    print(f"  banco:     {banco.CAMINHO_BANCO}")

    if not os.path.exists(importar_taco.CAMINHO_CSV):
        print(f"  ERRO: CSV da TACO ausente em {importar_taco.CAMINHO_CSV}")
        return 1

    relatorio = importar_taco.importar()
    fora = sum(relatorio["excluidos"].values())
    print(f"  alimentos: {relatorio['importados']} carregados "
          f"({fora} fora do recorte, de {relatorio['lidos']} publicados)")

    avisos = conferir_configuracao()
    if avisos:
        print()
        print("  Falta configurar")
        print("  " + "-" * 56)
        for aviso in avisos:
            print(f"  [ ] {aviso}")

    print()
    print("  Pronto. Para subir o site:  python app.py")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
