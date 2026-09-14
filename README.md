# Sistema Web para Gestão Nutricional e Sugestão de Planos Alimentares

Trabalho de Curso II — Ciência da Computação
Universidade Paulista (UNIP) — Polo Jacareí

**Autor:** Gabriel Luque de Sousa
**Orientador:** Prof. Me. Antônio Palmeira

---

## O que o sistema faz

Calcula as necessidades nutricionais individuais de uma pessoa e gera um
cardápio diário compatível com essas metas, usando a Tabela Brasileira de
Composição de Alimentos (TACO) como base de dados.

O usuário informa peso, altura, idade, sexo e nível de atividade física. O
sistema calcula a Taxa Metabólica Basal e o Gasto Energético Total, distribui
as calorias entre proteína, gordura e carboidrato, e produz um plano alimentar
que pode ser ajustado em linguagem natural — *"não como aveia de manhã,
prefiro pão com ovo"*. O resultado é exportado em PDF.

---

## Como rodar

### Opção A — GitHub Codespaces (sem instalar nada)

Botão **Code → Codespaces → Create codespace on main**. O ambiente já vem
com Python e todas as dependências instaladas. Depois é só:

```bash
pytest -v
```

### Opção B — Máquina local

Requer Python 3.10 ou superior.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Credenciais:

```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```

Preencha o `.env` com a chave da API do Gemini, obtida em
[aistudio.google.com/apikey](https://aistudio.google.com/apikey). Para gerar a
chave de sessão do Flask:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Banco de dados e execução:

```bash
python criar_banco.py
python importar_taco.py
python app.py
```

Acesse `http://localhost:5000`.

---

## Testes

```bash
pytest -v
```

Toda a regra de negócio é testada sem subir o servidor web.

---

## Estrutura

```
tcc-nutricao/
│
├── .env                  credenciais (nunca versionado)
├── .env.example          modelo, sem valores
├── .gitignore
├── requirements.txt
├── README.md
│
├── app.py                roteamento Flask — apenas isso
├── calculadora.py        funções matemáticas puras
├── banco.py              todo o acesso a dados
├── integracao_ia.py      cliente da API Gemini
├── gerar_pdf.py          exportação do plano
├── criar_banco.py        cria as tabelas
├── importar_taco.py      carrega a Tabela TACO
│
├── static/style.css
├── templates/            base.html e as telas
├── tests/                testes automatizados
└── docs/                 diagramas e material do trabalho
```

---

## Decisões de arquitetura

Registradas aqui porque são o assunto do Capítulo 3 do trabalho.

**O Python é dono de todo número.** A inteligência artificial nunca escreve um
valor numérico exibido ao usuário. Cálculos de TMB, GET e macronutrientes são
executados exclusivamente em `calculadora.py`; a IA recebe os resultados
prontos e produz apenas o texto ao redor. Isso elimina o risco de divergência
entre o que foi calculado e o que a pessoa lê.

**A IA escolhe apenas de um catálogo fechado.** O prompt recebe a lista de
alimentos presentes na base TACO local. O modelo compõe refeições selecionando
dessa lista e não pode propor itens fora dela.

**Restrição alimentar é filtro de banco, não instrução de texto.** Quando o
usuário declara uma intolerância, os alimentos correspondentes são removidos
do catálogo *antes* de qualquer coisa ser enviada à IA — o modelo nunca vê o
alimento proibido. Confiar na IA para "lembrar" de uma restrição alimentar
seria transferir uma questão de segurança para um componente probabilístico.

**Nenhuma matemática em JavaScript.** A interface de página única é obtida por
recarga do formulário, não por cálculo no navegador. Duplicar as fórmulas no
front-end criaria duas fontes de verdade para o mesmo número.

**Sem IMC.** O Índice de Massa Corporal não distingue tecido muscular de
adiposo e, por ter magnitude parecida com a do percentual de gordura, induzia
usuários a confundir as duas grandezas. Quando o percentual de gordura é
desconhecido, o sistema usa a equação de Mifflin-St Jeor, que não depende de
composição corporal.

**Padrão e escolhido gravados lado a lado.** Cada cálculo registra tanto o
valor recomendado pelo sistema quanto o efetivamente escolhido pelo usuário.
Comparar as duas colunas permite medir, com dados, se as pessoas usam a
liberdade de ajuste que a hipótese do trabalho pressupõe.

---

## Equações implementadas

| Equação | Quando é usada | Fonte |
|---|---|---|
| Mifflin-St Jeor | Padrão, quando o percentual de gordura é desconhecido | MIFFLIN et al. (1990) |
| Katch-McArdle | Quando o usuário informa o percentual de gordura | KATCH; McARDLE |
| Harris-Benedict | Apenas para comparação no Capítulo 4 | HARRIS; BENEDICT (1919) |

---

## Proteção de dados

O sistema coleta dados biométricos e preferências alimentares, o que exige
base legal sob a Lei 13.709/2018 (LGPD).

- Senhas armazenadas apenas como hash (`werkzeug.security`), nunca em texto
  plano
- Consentimento explícito no cadastro, registrado com data e hora
- Finalidade acadêmica declarada ao usuário
- Exclusão de conta remove, em cascata, todos os dados derivados
  (direito de eliminação, art. 18)
