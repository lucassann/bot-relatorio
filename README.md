# 🤖 Bot de Relatórios Personalizados com IA (Telegram + Gemini)

Bot inteligente para o Telegram que gera relatórios profissionais e executivos no **layout e estilo exatos que você desejar**, utilizando a **I.A do Google Gemini**.

Você pode fornecer o seu modelo ou estilo desejado enviando um arquivo (**PDF**, **Word .docx**, **TXT**) ou digitando as instruções de formato. Depois, basta enviar seus dados ou anotações brutas e o bot gera o relatório final pronto em **Microsoft Word (.docx)**, **PDF** e **TXT**.

---

## 🚀 Principais Recursos

- 🎨 **Aprendizado de Estilo & Layout por Exemplo**: Envie um relatório que você já usa (em PDF, Word ou TXT) ou dite a estrutura desejada. O Gemini extrai automaticamente as seções, hierarquia, tabelas e tom de voz.
- 📁 **Múltiplos Modelos**: Salve diferentes estilos (ex: *Relatório Semanal*, *Ata de Reunião*, *Relatório Técnico*, *Resumo Comercial*) e alterne entre eles a qualquer momento pelo menu do Telegram.
- 📊 **Entrada Flexível**: Envie textos digitados, anotações rápidas ou arquivos de dados (.pdf, .docx, .txt, .csv).
- 📄 **Exportação Multiformato Profissional**:
  - **Word (.docx)**: com cabeçalhos estilizados, cores corporativas, tabelas zebradas e formatação impecável.
  - **PDF**: diagramado com margens adequadas, numeração de páginas e tipografia limpa via ReportLab.
  - **TXT / Markdown**: para cópia rápida.
- ✏️ **Ajustes & Refinamento em Tempo Real**: Clique em "Ajustar / Refinar" e peça correções na hora (ex: *"resuma a introdução"*, *"adicione uma coluna na tabela com os responsáveis"*, *"deixe o tom mais formal"*).

---

## 🛠️ Passo a Passo para Configuração

### 1. Obter o Token do Bot no Telegram
1. Abra o Telegram e pesquise por **`@BotFather`**.
2. Envie o comando `/newbot`.
3. Escolha um nome e um nome de usuário (terminado em `bot`, ex: `meu_relatorio_ia_bot`).
4. O BotFather fornecerá um token no formato: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`.

### 2. Obter a Chave da API do Google Gemini
1. Acesse o **[Google AI Studio](https://aistudio.google.com/)**.
2. Faça login com sua conta Google.
3. Clique em **"Get API key"** e depois em **"Create API key"**.
4. Copie a chave gerada.

### 3. Configurar as Chaves no Arquivo `.env`
Abra o arquivo `.env` nesta pasta e preencha suas credenciais:

```env
TELEGRAM_BOT_TOKEN=seu_token_aqui_do_botfather
GEMINI_API_KEY=sua_chave_aqui_do_google_ai_studio
GEMINI_MODEL=gemini-2.5-flash
```

---

## 🏃 Como Executar o Bot

No terminal, dentro da pasta do projeto, execute:

```bash
./run.sh
```

Ou se preferir executar diretamente via Python:

```bash
./venv/bin/python bot.py
```

Assim que iniciado, o terminal mostrará:
```text
🚀 Bot iniciado com sucesso! Pressione Ctrl+C para encerrar.
```

---

## 📱 Como Usar no Telegram

1. Inicie uma conversa com seu bot no Telegram e envie `/start`.
2. **Definir seu Estilo de Relatório**:
   - Clique em **`🎨 Definir Novo Estilo`** (ou envie `/modelo`).
   - Envie um arquivo (.docx, .pdf ou .txt) com um modelo pronto que você gosta, OU digite:
     > *"Quero um relatório executivo com as seções: Resumo, Principais Indicadores em tabela, Desafios Encontrados e Próximos Passos com responsáveis. Tom profissional e direto."*
3. **Gerar Relatórios**:
   - Basta enviar suas anotações, rascunhos ou colar seus dados no chat.
   - O bot processará com o Gemini e responderá com os arquivos **Word (.docx)** e **PDF** prontos para download!
4. **Refinar o Documento**:
   - Clique no botão **`✏️ Ajustar / Refinar`** abaixo do relatório gerado e diga o que deseja alterar.

---

## 📂 Estrutura do Projeto

```
bot-relatorio/
├── bot.py              # Aplicação do Telegram e controle dos fluxos
├── gemini_service.py   # Integração com o Google Gemini (SDK google-genai)
├── doc_generator.py    # Gerador de documentos Word (.docx) e PDF profissional
├── parsers.py          # Extrator de textos de PDF, DOCX, TXT, CSV
├── database.py         # Persistência de usuários, modelos e relatórios em SQLite
├── config.py           # Carregamento de variáveis de ambiente e caminhos
├── requirements.txt    # Dependências do projeto
├── run.sh              # Script de inicialização rápida
└── data/               # Banco de dados e armazenamento de arquivos
```
