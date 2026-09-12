#!/usr/bin/env bash
set -e

echo "=========================================="
echo "🤖 Instalador do Bot de Relatórios no Alwaysdata"
echo "=========================================="

APP_DIR="$HOME/bot-relatorio"

if [ -d "$APP_DIR" ]; then
    echo "📂 Pasta já existe, atualizando código..."
    cd "$APP_DIR"
    git pull origin main
else
    echo "📥 Clonando repositório..."
    git clone https://github.com/lucassann/bot-relatorio.git "$APP_DIR"
    cd "$APP_DIR"
fi

echo "📦 Criando ambiente virtual isolado..."
python3 -m venv venv

echo "📦 Instalando dependências (otimizado sem cache para economizar disco)..."
./venv/bin/pip install --no-cache-dir --upgrade pip
./venv/bin/pip install --no-cache-dir -r requirements.txt

# Limpa resíduos temporários de cache
rm -rf ~/.cache/pip

if [ ! -f .env ]; then
    echo "⚙️ Criando arquivo .env padrão..."
    cp .env.example .env
fi

echo ""
echo "=========================================="
echo "✅ Instalação dos arquivos e dependências concluída!"
echo "=========================================="
echo "📌 Pasta do Bot: $APP_DIR"
echo ""
echo "👉 PRÓXIMO PASSO: Editar o arquivo .env com suas chaves:"
echo "   Digite: nano ~/bot-relatorio/.env"
echo "   (Cole seu TELEGRAM_BOT_TOKEN e sua GEMINI_API_KEY, depois Ctrl+O e Enter para salvar, Ctrl+X para sair)"
echo ""
echo "👉 PARA DEIXAR RODANDO 24H NO PAINEL DO ALWAYSDATA:"
echo "1. No menu esquerdo, vá em 'Environment' -> 'User programs'"
echo "2. Clique em 'Add a user program'"
echo "3. Preencha os campos:"
echo "   - Name: Bot Telegram"
echo "   - Command: $APP_DIR/venv/bin/python -u bot.py"
echo "   - Working directory: $APP_DIR"
echo "   - Enabled: Sim (Yes)"
echo "4. Clique em 'Submit' e pronto! O bot rodará 24 horas por dia!"
echo "=========================================="
