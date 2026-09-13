import os
import time
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import config
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Ativa WAL Mode e Timeout para concorrência sem travamentos
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        active_template_id INTEGER,
        current_state TEXT DEFAULT 'idle',
        logo_path TEXT,
        color_theme TEXT DEFAULT 'navy',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Migração segura para colunas logo_path e color_theme caso a tabela já exista
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN logo_path TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN color_theme TEXT DEFAULT 'navy'")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        style_instructions TEXT NOT NULL,
        sample_text TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        template_id INTEGER,
        title TEXT,
        raw_input TEXT,
        generated_content TEXT,
        docx_path TEXT,
        pdf_path TEXT,
        txt_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )
    """)

    conn.commit()
    conn.close()

def get_or_create_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, current_state)
            VALUES (?, ?, ?, 'idle')
        """, (user_id, username, first_name))
        conn.commit()

        # Cria um modelo padrão inicial para o usuário
        default_style = (
            "Estrutura padrão de relatório corporativo moderno:\n"
            "- Título claro e chamativo\n"
            "- Metadados: Data, Autor/Responsável\n"
            "- Resumo Executivo (visão geral concisa)\n"
            "- Destaques Principais (tópicos com bullet points)\n"
            "- Análise Detalhada / Métricas (com tabelas se houver dados numéricos)\n"
            "- Desafios & Riscos\n"
            "- Conclusão e Próximos Passos (ações com responsáveis ou prazos)\n"
            "Tom: Profissional, analítico e objetivo."
        )
        cursor.execute("""
            INSERT INTO templates (user_id, name, style_instructions, sample_text)
            VALUES (?, 'Modelo Corporativo Padrão', ?, '')
        """, (user_id, default_style))
        template_id = cursor.lastrowid

        cursor.execute("UPDATE users SET active_template_id = ? WHERE user_id = ?", (template_id, user_id))
        conn.commit()

        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

    user = dict(row)
    conn.close()
    return user

def set_user_state(user_id: int, state: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET current_state = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (state, user_id))
    conn.commit()
    conn.close()

def get_user_state(user_id: int) -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_state FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row["current_state"] if row else "idle"

def save_template(user_id: int, name: str, style_instructions: str, sample_text: str = "") -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO templates (user_id, name, style_instructions, sample_text)
        VALUES (?, ?, ?, ?)
    """, (user_id, name, style_instructions, sample_text))
    template_id = cursor.lastrowid
    # Define como ativo
    cursor.execute("UPDATE users SET active_template_id = ? WHERE user_id = ?", (template_id, user_id))
    conn.commit()
    conn.close()
    return template_id

def set_active_template(user_id: int, template_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET active_template_id = ? WHERE user_id = ?", (template_id, user_id))
    conn.commit()
    conn.close()

def get_active_template(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.* FROM templates t
        JOIN users u ON u.active_template_id = t.id
        WHERE u.user_id = ?
    """, (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_templates(user_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM templates WHERE user_id = ? ORDER BY id DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_template_by_id(template_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM templates WHERE id = ?", (template_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_report(user_id: int, template_id: Optional[int], title: str, raw_input: str,
                generated_content: str, docx_path: str = "", pdf_path: str = "", txt_path: str = "") -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reports (user_id, template_id, title, raw_input, generated_content, docx_path, pdf_path, txt_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, template_id, title, raw_input, generated_content, docx_path, pdf_path, txt_path))
    report_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return report_id

def get_latest_report(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reports WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_latest_report(report_id: int, generated_content: str, docx_path: str = "", pdf_path: str = "", txt_path: str = ""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reports 
        SET generated_content = ?, docx_path = ?, pdf_path = ?, txt_path = ?
        WHERE id = ?
    """, (generated_content, docx_path, pdf_path, txt_path, report_id))
    conn.commit()
    conn.close()

def update_user_logo(user_id: int, logo_path: Optional[str]):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET logo_path = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (logo_path, user_id))
    conn.commit()
    conn.close()

def update_user_color_theme(user_id: int, color_theme: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET color_theme = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", (color_theme, user_id))
    conn.commit()
    conn.close()

def get_user_settings(user_id: int) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT logo_path, color_theme FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"logo_path": row["logo_path"], "color_theme": row["color_theme"] or "navy"}
    return {"logo_path": None, "color_theme": "navy"}

def clear_user_files(user_id: int) -> Dict[str, int]:
    """Exclui os arquivos físicos gerados (DOCX, PDF, TXT) do usuário, liberando espaço no disco"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, docx_path, pdf_path, txt_path FROM reports WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    
    deleted_files = 0
    freed_bytes = 0

    for r in rows:
        for key in ["docx_path", "pdf_path", "txt_path"]:
            p_str = r[key]
            if p_str:
                p = Path(p_str)
                if p.exists():
                    try:
                        freed_bytes += p.stat().st_size
                        p.unlink()
                        deleted_files += 1
                    except Exception:
                        pass
        cursor.execute("UPDATE reports SET docx_path = '', pdf_path = '', txt_path = '' WHERE id = ?", (r["id"],))

    # Limpa uploads temporários do usuário se houver prefixo do id
    if config.UPLOADS_DIR.exists():
        for f in config.UPLOADS_DIR.glob(f"*{user_id}*"):
            if f.is_file():
                try:
                    freed_bytes += f.stat().st_size
                    f.unlink()
                    deleted_files += 1
                except Exception:
                    pass

    conn.commit()
    conn.close()
    return {"deleted_files": deleted_files, "freed_bytes": freed_bytes}

def clean_expired_files(max_age_hours: int = 24) -> Dict[str, int]:
    """Limpa arquivos de uploads e outputs mais antigos que max_age_hours (preserva logos)"""
    now = time.time()
    max_age_sec = max_age_hours * 3600
    deleted_files = 0
    freed_bytes = 0

    for folder in [config.UPLOADS_DIR, config.OUTPUTS_DIR]:
        if not folder.exists():
            continue
        for item in folder.glob("*"):
            if item.is_file():
                if item.name.startswith("."):
                    continue
                try:
                    age = now - item.stat().st_mtime
                    if age > max_age_sec:
                        freed_bytes += item.stat().st_size
                        item.unlink()
                        deleted_files += 1
                except Exception:
                    pass

    return {"deleted_files": deleted_files, "freed_bytes": freed_bytes}

def get_storage_summary() -> Dict[str, int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM users")
    total_users = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM templates")
    total_templates = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM reports")
    total_reports = cursor.fetchone()["count"]
    conn.close()
    return {
        "total_users": total_users,
        "total_templates": total_templates,
        "total_reports": total_reports
    }
