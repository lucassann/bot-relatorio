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

## 🌐 Como Rodar Online 24/7 Gratuitamente

Para que o bot funcione 24 horas por dia sem precisar deixar o seu computador ligado:

### Opção Recomendada: Render.com (Gratuito) + UptimeRobot (Keep-Alive)

O plano gratuito do Render desliga ("hiberna") serviços que ficam 15 minutos sem receber acessos web. Como o Telegram se comunica internamente, o robô precisa de um ping periódico para se manter acordado:

1. **Suba as alterações para o seu repositório GitHub**:
   ```bash
   git add .
   git commit -m "fix: suporte completo a deploy online 24h"
   git push origin main
   ```
2. **Crie o Web Service no Render**:
   - Acesse [Render.com](https://render.com) e conecte sua conta do GitHub.
   - Clique em **"New +"** -> **"Web Service"**.
   - Selecione o repositório `bot-relatorio`.
   - Em **Runtime**, escolha **Python**.
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
   - Em **Instance Type**, selecione **Free**.
3. **Adicione as Variáveis de Ambiente no Render** (Aba *Environment*):
   - `TELEGRAM_BOT_TOKEN`: o token do seu bot gerado pelo @BotFather.
   - `GEMINI_API_KEY`: sua chave de API obtida no Google AI Studio.
   - `GEMINI_MODEL`: `gemini-3.5-flash-lite` (ou `gemini-3.6-flash`).
4. **Mantenha o Bot 24/7 Ativo com UptimeRobot (100% Grátis)**:
   - Copie a URL pública gerada pelo Render (ex: `https://bot-relatorio-xyz.onrender.com`).
   - Crie uma conta gratuita em [UptimeRobot.com](https://uptimerobot.com).
   - Clique em **"Add New Monitor"**:
     - **Monitor Type**: `HTTP(s)`
     - **Friendly Name**: `Bot Telegram 24h`
     - **URL (or IP)**: Cole a URL do seu Render (ex: `https://bot-relatorio-xyz.onrender.com/health`)
     - **Monitoring Interval**: `5 minutes`
   - Salve o monitor! A cada 5 minutos o UptimeRobot enviará uma requisição, impedindo que o Render coloque seu bot para dormir.

> [!WARNING]
> **ATENÇÃO AO CONFLITO DE INSTÂNCIAS:**
> O Telegram só permite **uma instância ativa por token**. Quando colocar o bot para rodar online, lembre-se de parar o bot no seu computador local (`./stop.sh`), caso contrário uma instância derrubará a outra com erro de conflito (`409 Conflict`).

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
