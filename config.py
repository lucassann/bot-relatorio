import os
from pathlib import Path
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
OUTPUTS_DIR = DATA_DIR / "outputs"
LOGOS_DIR = DATA_DIR / "logos"
DB_PATH = DATA_DIR / "bot.db"

# Garante a existência das pastas necessárias
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
LOGOS_DIR.mkdir(parents=True, exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()

# Usuários autorizados (opcional - lista separada por vírgula no .env)
# Se estiver vazio, o bot é aberto a todos os usuários
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "").strip()
ALLOWED_USERS = [int(u.strip()) for u in ALLOWED_USERS_RAW.split(",") if u.strip().isdigit()]

# Horas para expirar arquivos temporários
AUTO_CLEAN_HOURS = int(os.getenv("AUTO_CLEAN_HOURS", "24"))

def is_user_allowed(user_id: int) -> bool:
    """Verifica se o usuário tem permissão para usar o bot"""
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

def check_config():
    missing = []
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "seu_token_aqui":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "sua_api_key_aqui":
        missing.append("GEMINI_API_KEY")
    return missing
