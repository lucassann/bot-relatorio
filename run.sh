#!/usr/bin/env bash

# Direciona para a pasta do bot
cd "$(dirname "$0")"

# Verifica se o ambiente virtual existe
if [ ! -d "venv" ]; then
    echo "📦 Criando ambiente virtual..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
fi

# Inicia o bot com o python do venv
echo "🤖 Iniciando Bot de Relatórios..."
./venv/bin/python bot.py
