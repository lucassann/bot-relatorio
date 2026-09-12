FROM python:3.12-slim

WORKDIR /app

# Instala dependências do sistema necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia dependências e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código da aplicação
COPY . .

# Porta padrão para plataformas em nuvem (Render, Koyeb, Fly.io, etc)
ENV PORT=10000
EXPOSE 10000

# Comando de inicialização
CMD ["python", "bot.py"]
