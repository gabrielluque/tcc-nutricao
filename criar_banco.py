"""
criar_banco.py - Cria as tabelas do sistema.

Execute uma vez, antes do primeiro uso:

    python criar_banco.py

Seguro repetir: as tabelas usam CREATE TABLE IF NOT EXISTS e nenhum dado
existente e apagado.

O esquema em si nao mora aqui - ele esta em banco.py, na constante ESQUEMA.
Este script apenas o executa. A separacao existe porque o prototipo anterior
tinha DOIS scripts criando a mesma tabela com colunas diferentes, e a
divergencia entre eles produziu um bug silencioso que exibia todo o
historico com os valores trocados de coluna. Com uma unica definicao, essa
classe de erro deixa de ser possivel.
"""

import banco


def main():
    banco.criar_esquema()
    print(f"Banco criado em '{banco.CAMINHO_BANCO}'.")
    print(f"Alimentos cadastrados: {banco.contar_alimentos()}")
    print()
    print("Proximo passo: python importar_taco.py")


if __name__ == "__main__":
    main()
