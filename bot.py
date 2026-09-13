import os
import re
import html
import json
import time
import shutil
import asyncio
import logging
import threading
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import config
import database
import parsers
import gemini_service
import doc_generator

# Configuração de Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Estados do usuário
STATE_IDLE = "idle"
STATE_WAITING_TEMPLATE = "waiting_template"
STATE_WAITING_REPORT_INPUT = "waiting_report_input"
STATE_WAITING_ADJUSTMENT = "waiting_adjustment"
STATE_WAITING_LOGO = "waiting_logo"

def get_system_metrics() -> Dict[str, Any]:
    """Calcula métricas de disco, memória RAM e arquivos do bot em tempo real"""
    # Disco do sistema
    disk = shutil.disk_usage(str(config.BASE_DIR))
    disk_total_gb = disk.total / (1024**3)
    disk_used_gb = disk.used / (1024**3)
    disk_free_gb = disk.free / (1024**3)
    disk_pct = (disk.used / disk.total) * 100 if disk.total > 0 else 0

    # Memória RAM do sistema (Linux /proc/meminfo)
    total_ram_mb = 0
    used_ram_mb = 0
    free_ram_mb = 0
    ram_pct = 0
    if os.path.exists("/proc/meminfo"):
        try:
            mem = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        mem[parts[0].strip()] = int(parts[1].strip().split()[0])
            total_ram_mb = mem.get("MemTotal", 0) / 1024
            free_ram_mb = mem.get("MemAvailable", mem.get("MemFree", 0)) / 1024
            used_ram_mb = max(0, total_ram_mb - free_ram_mb)
            if total_ram_mb > 0:
                ram_pct = (used_ram_mb / total_ram_mb) * 100
        except Exception:
            pass

    # Arquivos armazenados pelo bot
    def get_dir_info(path: Path) -> Tuple[float, int]:
        total_b = 0
        count = 0
        if path.exists():
            for p in path.glob("*"):
                if p.is_file() and not p.name.startswith("."):
                    try:
                        total_b += p.stat().st_size
                        count += 1
                    except Exception:
                        pass
        return total_b / (1024 * 1024), count

    uploads_mb, uploads_count = get_dir_info(config.UPLOADS_DIR)
    outputs_mb, outputs_count = get_dir_info(config.OUTPUTS_DIR)
    db_mb = (config.DB_PATH.stat().st_size / (1024 * 1024)) if config.DB_PATH.exists() else 0
    db_stats = database.get_storage_summary()

    return {
        "disk_total_gb": disk_total_gb,
        "disk_used_gb": disk_used_gb,
        "disk_free_gb": disk_free_gb,
        "disk_pct": disk_pct,
        "total_ram_mb": total_ram_mb,
        "used_ram_mb": used_ram_mb,
        "free_ram_mb": free_ram_mb,
        "ram_pct": ram_pct,
        "uploads_mb": uploads_mb,
        "uploads_count": uploads_count,
        "outputs_mb": outputs_mb,
        "outputs_count": outputs_count,
        "db_mb": db_mb,
        "bot_total_mb": uploads_mb + outputs_mb + db_mb,
        "total_reports": db_stats["total_reports"],
        "total_templates": db_stats["total_templates"],
        "total_users": db_stats["total_users"],
    }

def format_progress_bar(pct: float, length: int = 10) -> str:
    filled = int(round((pct / 100.0) * length))
    filled = max(0, min(length, filled))
    return "█" * filled + "░" * (length - filled)

def format_storage_message(metrics: Dict[str, Any]) -> str:
    disk_bar = format_progress_bar(metrics["disk_pct"])
    ram_bar = format_progress_bar(metrics["ram_pct"]) if metrics["total_ram_mb"] > 0 else "N/A"

    ram_section = ""
    if metrics["total_ram_mb"] > 0:
        ram_section = (
            f"🧠 <b>Memória RAM do Servidor:</b>\n"
            f"<code>[{ram_bar}] {metrics['ram_pct']:.1f}%</code>\n"
            f"• Usada: <b>{metrics['used_ram_mb']:.0f} MB</b> de <b>{metrics['total_ram_mb']:.0f} MB</b>\n"
            f"• Disponível: <b>{metrics['free_ram_mb']:.0f} MB</b> livres\n\n"
        )

    text = (
        "💾 <b>Monitor de Armazenamento & Memória em Tempo Real</b>\n\n"
        f"💽 <b>Espaço em Disco:</b>\n"
        f"<code>[{disk_bar}] {metrics['disk_pct']:.1f}%</code>\n"
        f"• Usado: <b>{metrics['disk_used_gb']:.1f} GB</b> de <b>{metrics['disk_total_gb']:.1f} GB</b>\n"
        f"• Livre: <b>{metrics['disk_free_gb']:.1f} GB</b> disponíveis\n\n"
        f"{ram_section}"
        "📁 <b>Arquivos Armazenados pelo Bot:</b>\n"
        f"• Documentos Gerados (Word/PDF): <b>{metrics['outputs_count']}</b> arquivos (<b>{metrics['outputs_mb']:.2f} MB</b>)\n"
        f"• Anexos / Uploads recebidos: <b>{metrics['uploads_count']}</b> arquivos (<b>{metrics['uploads_mb']:.2f} MB</b>)\n"
        f"• Banco de Dados SQLite: <b>{metrics['db_mb']:.2f} MB</b> ({metrics['total_reports']} relatórios salvos)\n"
        f"• <b>Total Ocupado pelo Bot:</b> <b>{metrics['bot_total_mb']:.2f} MB</b>\n\n"
        "<i>💡 Clique em 'Esvaziar Arquivos Salvos' abaixo para apagar os arquivos físicos e liberar espaço na hora!</i>"
    )
    return text

def get_main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🚀 Novo Relatório", callback_data="btn_new_report"),
            InlineKeyboardButton("📋 Estilo Ativo", callback_data="btn_view_template")
        ],
        [
            InlineKeyboardButton("🎨 Definir Novo Estilo", callback_data="btn_set_template"),
            InlineKeyboardButton("📁 Meus Modelos", callback_data="btn_my_templates")
        ],
        [
            InlineKeyboardButton("💾 Armazenamento & Disco", callback_data="btn_storage_status"),
            InlineKeyboardButton("🏢 Marca & Cores", callback_data="btn_brand_settings")
        ],
        [
            InlineKeyboardButton("❓ Ajuda / Como Usar", callback_data="btn_help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_storage_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🗑️ Esvaziar Arquivos Salvos", callback_data="btn_confirm_clear_files"),
            InlineKeyboardButton("🔄 Atualizar Status", callback_data="btn_refresh_storage")
        ],
        [
            InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_brand_keyboard(has_logo: bool = False):
    keyboard = [
        [
            InlineKeyboardButton("🖼️ Enviar Logo da Empresa", callback_data="btn_set_logo"),
            InlineKeyboardButton("🎨 Mudar Cores do Documento", callback_data="btn_choose_color")
        ]
    ]
    if has_logo:
        keyboard.append([InlineKeyboardButton("❌ Remover Logo Atual", callback_data="btn_remove_logo")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_color_themes_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🔵 Azul Executivo", callback_data="theme_navy"),
            InlineKeyboardButton("🟢 Verde Corporativo", callback_data="theme_green")
        ],
        [
            InlineKeyboardButton("⚪ Cinza Minimalista", callback_data="theme_slate"),
            InlineKeyboardButton("🟣 Bordô Elegante", callback_data="theme_burgundy")
        ],
        [
            InlineKeyboardButton("⚫ Preto & Grafite", callback_data="theme_dark")
        ],
        [
            InlineKeyboardButton("🔙 Voltar", callback_data="btn_brand_settings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_report_actions_keyboard(has_report: bool = True):
    keyboard = [
        [
            InlineKeyboardButton("📄 Baixar Word (.docx)", callback_data="btn_dl_docx"),
            InlineKeyboardButton("📑 Baixar PDF (.pdf)", callback_data="btn_dl_pdf")
        ],
        [
            InlineKeyboardButton("📝 Baixar TXT (.txt)", callback_data="btn_dl_txt"),
            InlineKeyboardButton("✏️ Ajustar / Refinar", callback_data="btn_adjust")
        ],
        [
            InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_main_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def safe_reply(target, text: str, reply_markup=None, parse_mode="HTML"):
    """
    Envia resposta com segurança usando HTML ou fallback para texto simples
    caso ocorra erro de formatação (entidades inválidas).
    """
    dest = getattr(target, "message", target)
    try:
        if hasattr(dest, "reply_text"):
            return await dest.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.warning(f"Falha ao enviar com parse_mode={parse_mode}: {e}. Enviando sem formatação...")
        clean_text = re.sub(r'<[^>]+>', '', text)
        clean_text = clean_text.replace('*', '').replace('`', '').replace('_', '')
        if hasattr(dest, "reply_text"):
            return await dest.reply_text(clean_text, reply_markup=reply_markup)

async def send_chunked_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, reply_markup=None):
    """Envia mensagens longas divididas em blocos de até 4000 caracteres"""
    max_len = 4000
    if len(text) <= max_len:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        return

    chunks = []
    current_chunk = ""
    for line in text.split("\n"):
        if len(current_chunk) + len(line) + 1 > max_len:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        # Apenas coloca o teclado no último bloco
        markup = reply_markup if i == len(chunks) - 1 else None
        await context.bot.send_message(chat_id=chat_id, text=chunk, reply_markup=markup)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start"""
    user = update.effective_user
    if not config.is_user_allowed(user.id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return

    database.get_or_create_user(user.id, user.username, user.first_name)
    database.set_user_state(user.id, STATE_IDLE)

    active_tpl = database.get_active_template(user.id)
    tpl_name = active_tpl["name"] if active_tpl else "Nenhum selecionado"

    user_name = html.escape(user.first_name or "Usuário")
    tpl_escaped = html.escape(tpl_name)

    text = (
        f"👋 Olá, <b>{user_name}</b>! Bem-vindo ao seu <b>Gerador Inteligente de Relatórios</b>.\n\n"
        f"🎯 <b>Estilo/Modelo Ativo</b>: <code>{tpl_escaped}</code>\n\n"
        "Com este bot, você pode:\n"
        "1. <b>Definir seu Estilo/Layout</b>: Envie um PDF, Word (.docx), TXT, foto ou áudio ditando como deseja a estrutura.\n"
        "2. <b>Gerar Relatórios por Fotos, Áudio, Arquivo ou Texto</b>:\n"
        "   • 📸 <b>Fotos / Recibos / Notas</b>: OCR Gemini extrai tabelas e dados automaticamente;\n"
        "   • 🎙️ <b>Áudios / Mensagens de Voz</b>: grave sua voz e a I.A transcreve e estrutura o relatório;\n"
        "   • 📄 <b>Documentos / Rascunhos</b>: gere Word (.docx), PDF e TXT na hora.\n"
        "3. <b>Marca & Cores Personalizadas</b>: insira o logo da sua empresa e troque a paleta de cores.\n"
        "4. <b>Monitor em Tempo Real</b>: veja o uso de memória RAM, disco e esvazie arquivos com 1 clique.\n\n"
        "O que deseja fazer agora?"
    )

    await safe_reply(update.message, text, reply_markup=get_main_keyboard())

async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ajuda"""
    user = update.effective_user
    if user and not config.is_user_allowed(user.id):
        return

    text = (
        "📖 <b>Guia Rápido de Uso</b>:\n\n"
        "🔹 <b>Como definir o estilo desejado?</b>\n"
        "Clique em <i>'🎨 Definir Novo Estilo'</i> ou envie /modelo.\n"
        "Envie um arquivo (Word, PDF, TXT), uma foto ou um áudio explicando a estrutura.\n\n"
        "🔹 <b>Como gerar um relatório?</b>\n"
        "Clique em <i>'🚀 Novo Relatório'</i> ou envie diretamente no chat:\n"
        "• 📸 <b>Fotos/Imagens</b>: fotos de notas fiscais, recibos, quadros, tabelas ou anotações (a IA extrai todos os dados com visão computacional!)\n"
        "• 🎙️ <b>Áudios / Mensagens de Voz</b>: envie um áudio e a IA transcreve e gera o documento automaticamente.\n"
        "• ✍️ <b>Texto</b>: rascunhos, dados ou anotações coladas no chat.\n"
        "• 📄 <b>Documentos</b>: arquivos Word, PDF, CSV ou TXT.\n\n"
        "🔹 <b>Como pedir ajustes?</b>\n"
        "Após a geração do relatório, clique em <i>'✏️ Ajustar / Refinar'</i> ou use /ajustar e diga o que mudar.\n\n"
        "🔹 <b>Comandos Rápidos</b>:\n"
        "• /start - Menu Principal\n"
        "• /modelo - Configurar novo modelo de layout\n"
        "• /meus_modelos - Listar e trocar de modelo\n"
        "• /armazenamento - Ver memória RAM e disco em tempo real\n"
        "• /limpar - Esvaziar arquivos temporários e liberar espaço\n"
        "• /marca - Personalizar logo da empresa e cores do documento\n"
        "• /ajustar - Ajustar o último relatório\n"
        "• /cancelar - Cancelar operação atual"
    )
    msg = update.effective_message
    if msg:
        await safe_reply(msg, text, reply_markup=get_main_keyboard())

async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /cancelar"""
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        database.set_user_state(user_id, STATE_IDLE)
    context.user_data.clear()
    msg = update.effective_message
    if msg:
        await safe_reply(
            msg,
            "❌ <b>Operação cancelada.</b> Você está no menu principal.",
            reply_markup=get_main_keyboard()
        )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerencia cliques nos botões inline com tratamento completo de erros"""
    query = update.callback_query
    data = query.data
    user = query.from_user
    user_id = user.id

    if not config.is_user_allowed(user_id):
        await query.answer("Acesso não autorizado.", show_alert=True)
        return

    logger.info(f"Botão clicado: '{data}' pelo usuário {user.first_name} (ID: {user_id})")
    database.get_or_create_user(user_id, user.username, user.first_name)

    try:
        # Responde o callback imediatamente para cessar o loading visual do botão
        await query.answer()

        if data == "btn_main_menu":
            database.set_user_state(user_id, STATE_IDLE)
            active_tpl = database.get_active_template(user_id)
            tpl_name = active_tpl["name"] if active_tpl else "Nenhum"
            text = (
                f"🏠 <b>Menu Principal</b>\n\n"
                f"📌 <b>Estilo/Layout Ativo</b>: <code>{html.escape(tpl_name)}</code>\n\n"
                "Escolha uma opção abaixo:"
            )
            await safe_reply(query, text, reply_markup=get_main_keyboard())

        elif data == "btn_help":
            await cmd_ajuda(update, context)

        elif data == "btn_view_template":
            active_tpl = database.get_active_template(user_id)
            if not active_tpl:
                await safe_reply(query, "⚠️ Você ainda não possui nenhum estilo configurado.", reply_markup=get_main_keyboard())
                return

            tpl_name = html.escape(active_tpl['name'])
            guide_snippet = html.escape(active_tpl['style_instructions'][:2500])
            text = (
                f"📋 <b>Estilo Ativo Atual</b>: <b>{tpl_name}</b>\n\n"
                f"<b>Regras e Diretrizes do Layout:</b>\n"
                f"<code>{guide_snippet}</code>"
            )
            keyboard = [
                [InlineKeyboardButton("🎨 Criar Novo Modelo", callback_data="btn_set_template")],
                [InlineKeyboardButton("📁 Escolher Outro Modelo", callback_data="btn_my_templates")],
                [InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_main_menu")]
            ]
            await safe_reply(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "btn_set_template":
            database.set_user_state(user_id, STATE_WAITING_TEMPLATE)
            text = (
                "🎨 <b>Configuração de Estilo / Layout</b>\n\n"
                "Envie agora:\n"
                "1. Uma <b>foto ou imagem</b> de um modelo de relatório que você gosta;\n"
                "2. Um <b>arquivo</b> (.pdf, .docx, .txt) com um exemplo de layout; OU\n"
                "3. Uma <b>mensagem de texto</b> explicando como você deseja seu relatório (ex: <i>'Quero seções: Resumo, Destaques, Tabela de Indicadores, Ações. Tom executivo formal'</i>).\n\n"
                "🤖 A I.A analisará o layout e salvará como seu padrão!"
            )
            keyboard = [
                [InlineKeyboardButton("❌ Cancelar / Menu Principal", callback_data="btn_main_menu")]
            ]
            await safe_reply(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "btn_my_templates":
            templates = database.get_user_templates(user_id)
            if not templates:
                await safe_reply(query, "Nenhum modelo cadastrado ainda.", reply_markup=get_main_keyboard())
                return

            active_tpl = database.get_active_template(user_id)
            active_id = active_tpl["id"] if active_tpl else None

            keyboard = []
            for tpl in templates:
                prefix = "✅ " if tpl["id"] == active_id else "⚪ "
                keyboard.append([InlineKeyboardButton(f"{prefix}{tpl['name']}", callback_data=f"sel_tpl_{tpl['id']}")])
            
            keyboard.append([InlineKeyboardButton("➕ Adicionar Novo Estilo", callback_data="btn_set_template")])
            keyboard.append([InlineKeyboardButton("🏠 Voltar", callback_data="btn_main_menu")])

            text = "📁 <b>Seus Modelos de Relatório Salvos:</b>\nClique em um modelo para torná-lo ativo:"
            await safe_reply(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("sel_tpl_"):
            tpl_id = int(data.replace("sel_tpl_", ""))
            database.set_active_template(user_id, tpl_id)
            tpl = database.get_template_by_id(tpl_id)
            tpl_name = tpl["name"] if tpl else "Modelo"
            await query.answer(f"Modelo ativado: {tpl_name}!", show_alert=False)
            text = (
                f"✅ <b>Modelo Ativado</b>: <code>{html.escape(tpl_name)}</code>!\n\n"
                "Agora os seus próximos relatórios serão estruturados de acordo com este estilo."
            )
            await safe_reply(query, text, reply_markup=get_main_keyboard())

        elif data == "btn_new_report":
            database.set_user_state(user_id, STATE_WAITING_REPORT_INPUT)
            active_tpl = database.get_active_template(user_id)
            tpl_name = active_tpl["name"] if active_tpl else "Padrão"
            text = (
                f"🚀 <b>Criar Novo Relatório</b> (Modelo Ativo: <code>{html.escape(tpl_name)}</code>)\n\n"
                "Você pode enviar suas informações de várias formas:\n\n"
                "1. 📸 <b>Fotos / Imagens</b>: tire fotos de notas fiscais, recibos, quadros, tabelas ou anotações (a I.A extrai os dados e anexa as fotos no documento!);\n"
                "2. ✍️ <b>Digitar ou colar</b> seus dados, anotações ou rascunho aqui no chat;\n"
                "3. 📄 <b>Enviar um arquivo</b> (.pdf, .docx, .txt, .csv) com as informações;\n"
                "4. 🧪 <b>Testar agora</b> clicando no botão abaixo para gerar um relatório de demonstração em tempo real!\n\n"
                "<i>Aguardando seus dados ou fotos...</i>"
            )
            keyboard = [
                [InlineKeyboardButton("🧪 Gerar Exemplo de Demonstração", callback_data="btn_example_report")],
                [InlineKeyboardButton("❌ Cancelar / Menu Principal", callback_data="btn_main_menu")]
            ]
            await safe_reply(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "btn_example_report":
            await query.answer("Gerando relatório de exemplo...", show_alert=False)
            sample_data = (
                "Relatório de Desempenho Operacional e Comercial\n"
                "Período: Semana 36 - 2026\n"
                "Responsável: Coordenação Geral\n\n"
                "Resultados Principais:\n"
                "- Faturamento da semana: R$ 184.500,00 (Meta: R$ 170.000,00 - 108.5% atingido)\n"
                "- Novos clientes cadastrados: 43\n"
                "- Taxa de conversão de leads: 14.2%\n"
                "- Chamados de suporte atendidos: 128 (Tempo Médio de Resposta: 12 minutos)\n"
                "- Índice de Satisfação (CSAT): 98.4%\n\n"
                "Destaques da Operação:\n"
                "- Conclusão da homologação do novo gateway de pagamentos com redução de 0.8% nas taxas.\n"
                "- Treinamento da equipe de vendas no novo catálogo de produtos.\n\n"
                "Ações e Próximos Passos:\n"
                "- Implementar campanha de retenção para contas inativas até 15/09 (Responsável: Amanda).\n"
                "- Finalizar testes de carga da infraestrutura de servidores até 18/09 (Responsável: Rodrigo)."
            )
            await process_report_generation(query.message, context, user_id, raw_text=sample_data)

        elif data == "btn_adjust":
            report = database.get_latest_report(user_id)
            if not report:
                await query.answer("Nenhum relatório encontrado.", show_alert=True)
                await safe_reply(query, "⚠️ Nenhum relatório encontrado para ajustar. Crie um relatório primeiro!", reply_markup=get_main_keyboard())
                return
            database.set_user_state(user_id, STATE_WAITING_ADJUSTMENT)
            text = (
                "✏️ <b>Solicitar Ajustes no Relatório</b>\n\n"
                "Descreva o que deseja mudar. Exemplos:\n"
                "• <i>'Deixe o texto mais resumido e objetivo'</i>\n"
                "• <i>'Adicione uma coluna de Responsável na tabela'</i>\n"
                "• <i>'Mude o tom para executivo formal'</i>\n\n"
                "Envie sua mensagem com as correções:"
            )
            keyboard = [
                [InlineKeyboardButton("❌ Cancelar Ajuste", callback_data="btn_main_menu")]
            ]
            await safe_reply(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "btn_dl_docx":
            report = database.get_latest_report(user_id)
            if report and report["docx_path"] and Path(report["docx_path"]).exists():
                await query.answer("Enviando documento Word...")
                with open(report["docx_path"], "rb") as f:
                    await query.message.reply_document(f, filename=Path(report["docx_path"]).name, caption="📄 Relatório em Microsoft Word (.docx)")
            else:
                await query.answer("Arquivo DOCX não disponível.", show_alert=True)
                await safe_reply(query, "⚠️ Arquivo DOCX não disponível. Gere um relatório primeiro!", reply_markup=get_main_keyboard())

        elif data == "btn_dl_pdf":
            report = database.get_latest_report(user_id)
            if report and report["pdf_path"] and Path(report["pdf_path"]).exists():
                await query.answer("Enviando PDF...")
                with open(report["pdf_path"], "rb") as f:
                    await query.message.reply_document(f, filename=Path(report["pdf_path"]).name, caption="📑 Relatório em PDF")
            else:
                await query.answer("Arquivo PDF não disponível.", show_alert=True)
                await safe_reply(query, "⚠️ Arquivo PDF não disponível. Gere um relatório primeiro!", reply_markup=get_main_keyboard())

        elif data == "btn_dl_txt":
            report = database.get_latest_report(user_id)
            if report and report["txt_path"] and Path(report["txt_path"]).exists():
                await query.answer("Enviando arquivo TXT...")
                with open(report["txt_path"], "rb") as f:
                    await query.message.reply_document(f, filename=Path(report["txt_path"]).name, caption="📝 Relatório em Texto Puro (.txt)")
            else:
                await query.answer("Arquivo TXT não disponível.", show_alert=True)
                await safe_reply(query, "⚠️ Arquivo TXT não disponível. Gere um relatório primeiro!", reply_markup=get_main_keyboard())

        elif data.startswith("act_gen_"):
            file_id = data.replace("act_gen_", "")
            file_path = None
            file_path_str = context.user_data.get("last_uploaded_file") or context.bot_data.get(f"file_{file_id}")
            if file_path_str and Path(file_path_str).exists():
                file_path = Path(file_path_str)
            else:
                try:
                    status_rec = await query.message.reply_text("📥 Recuperando arquivo enviado...")
                    tg_file = await context.bot.get_file(file_id)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = f"{timestamp}_recuperado"
                    file_path = config.UPLOADS_DIR / safe_name
                    await tg_file.download_to_drive(str(file_path))
                    await status_rec.delete()
                except Exception as e:
                    logger.error(f"Erro ao recuperar arquivo: {e}")

            if not file_path or not file_path.exists():
                await query.answer("Arquivo não encontrado.", show_alert=True)
                await safe_reply(query, "⚠️ Arquivo não encontrado. Por favor, envie novamente o arquivo no chat.", reply_markup=get_main_keyboard())
                return

            await query.answer("Iniciando geração do relatório...")
            await process_report_generation(query.message, context, user_id, file_path=file_path)

        elif data.startswith("act_tpl_"):
            file_id = data.replace("act_tpl_", "")
            file_path = None
            file_path_str = context.user_data.get("last_uploaded_file") or context.bot_data.get(f"file_{file_id}")
            if file_path_str and Path(file_path_str).exists():
                file_path = Path(file_path_str)
            else:
                try:
                    status_rec = await query.message.reply_text("📥 Recuperando arquivo de modelo...")
                    tg_file = await context.bot.get_file(file_id)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = f"{timestamp}_modelo_recuperado"
                    file_path = config.UPLOADS_DIR / safe_name
                    await tg_file.download_to_drive(str(file_path))
                    await status_rec.delete()
                except Exception as e:
                    logger.error(f"Erro ao recuperar arquivo de modelo: {e}")

            if not file_path or not file_path.exists():
                await query.answer("Arquivo não encontrado.", show_alert=True)
                await safe_reply(query, "⚠️ Arquivo não encontrado. Por favor, envie novamente o arquivo no chat.", reply_markup=get_main_keyboard())
                return

            await query.answer("Analisando estilo do modelo...")
            await process_template_creation(query.message, context, user_id, file_path=file_path)

        elif data.startswith("act_pgen_"):
            file_id = data.replace("act_pgen_", "")
            photo_path = None
            photo_path_str = context.user_data.get("last_uploaded_photo") or context.bot_data.get(f"photo_{file_id}") or context.bot_data.get(f"file_{file_id}")
            if photo_path_str and Path(photo_path_str).exists():
                photo_path = Path(photo_path_str)
            else:
                try:
                    status_rec = await query.message.reply_text("📥 Recuperando foto enviada...")
                    tg_file = await context.bot.get_file(file_id)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = f"{timestamp}_photo_{file_id}.jpg"
                    photo_path = config.UPLOADS_DIR / safe_name
                    await tg_file.download_to_drive(str(photo_path))
                    await status_rec.delete()
                except Exception as e:
                    logger.error(f"Erro ao recuperar foto: {e}")

            if not photo_path or not photo_path.exists():
                await query.answer("Foto não encontrada.", show_alert=True)
                await safe_reply(query, "⚠️ Foto não encontrada. Por favor, envie novamente a foto no chat.", reply_markup=get_main_keyboard())
                return

            await query.answer("Iniciando extração de dados e relatório...")
            await process_report_generation(query.message, context, user_id, image_paths=[photo_path])

        elif data.startswith("act_ptpl_"):
            file_id = data.replace("act_ptpl_", "")
            photo_path = None
            photo_path_str = context.user_data.get("last_uploaded_photo") or context.bot_data.get(f"photo_{file_id}") or context.bot_data.get(f"file_{file_id}")
            if photo_path_str and Path(photo_path_str).exists():
                photo_path = Path(photo_path_str)
            else:
                try:
                    status_rec = await query.message.reply_text("📥 Recuperando foto enviada...")
                    tg_file = await context.bot.get_file(file_id)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = f"{timestamp}_photo_{file_id}.jpg"
                    photo_path = config.UPLOADS_DIR / safe_name
                    await tg_file.download_to_drive(str(photo_path))
                    await status_rec.delete()
                except Exception as e:
                    logger.error(f"Erro ao recuperar foto: {e}")

            if not photo_path or not photo_path.exists():
                await query.answer("Foto não encontrada.", show_alert=True)
                await safe_reply(query, "⚠️ Foto não encontrada. Por favor, envie novamente a foto no chat.", reply_markup=get_main_keyboard())
                return

            await query.answer("Analisando estilo da foto enviada...")
            await process_template_creation(query.message, context, user_id, image_paths=[photo_path])

        elif data == "btn_storage_status":
            metrics = get_system_metrics()
            text = format_storage_message(metrics)
            await safe_reply(query, text, reply_markup=get_storage_keyboard())

        elif data == "btn_refresh_storage":
            metrics = get_system_metrics()
            text = format_storage_message(metrics)
            await query.answer("Status atualizado em tempo real!")
            try:
                await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_storage_keyboard())
            except Exception:
                await safe_reply(query, text, reply_markup=get_storage_keyboard())

        elif data == "btn_confirm_clear_files":
            keyboard = [
                [InlineKeyboardButton("⚠️ Sim, Esvaziar Arquivos", callback_data="btn_do_clear_files")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="btn_storage_status")]
            ]
            text = (
                "🗑️ <b>Confirmação de Limpeza de Arquivos</b>\n\n"
                "Isso irá apagar permanentemente do servidor os arquivos físicos gerados (Word .docx, PDF, TXT) e anexos temporários.\n\n"
                "✅ <i>O histórico textual dos relatórios continuará salvo no seu banco de dados.</i>\n\n"
                "Deseja esvaziar agora?"
            )
            await safe_reply(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "btn_do_clear_files":
            res = database.clear_user_files(user_id)
            freed_mb = res["freed_bytes"] / (1024 * 1024)
            await query.answer(f"Limpeza concluída! {freed_mb:.2f} MB liberados.", show_alert=True)
            metrics = get_system_metrics()
            text = (
                f"✅ <b>Limpeza Realizada com Sucesso!</b>\n"
                f"• Arquivos físicos removidos: <b>{res['deleted_files']}</b>\n"
                f"• Espaço liberado no disco: <b>{freed_mb:.2f} MB</b>\n\n"
                + format_storage_message(metrics)
            )
            await safe_reply(query, text, reply_markup=get_storage_keyboard())

        elif data == "btn_brand_settings":
            settings = database.get_user_settings(user_id)
            has_logo = bool(settings["logo_path"] and Path(settings["logo_path"]).exists())
            theme_info = doc_generator.get_theme(settings["color_theme"])
            text = (
                "🏢 <b>Personalização de Marca & Cores</b>\n\n"
                f"🖼️ <b>Logo da Empresa:</b> {'✅ Ativa' if has_logo else '❌ Nenhuma logo cadastrada'}\n"
                f"🎨 <b>Paleta de Cores:</b> <b>{theme_info['name']}</b>\n\n"
                "Personalize a identidade visual dos relatórios gerados pelo bot:"
            )
            await safe_reply(query, text, reply_markup=get_brand_keyboard(has_logo))

        elif data == "btn_set_logo":
            database.set_user_state(user_id, STATE_WAITING_LOGO)
            text = (
                "🖼️ <b>Envio de Logo da Empresa</b>\n\n"
                "Envie agora a imagem do seu logo (PNG ou JPG) aqui no chat.\n"
                "💡 <i>Recomendado: imagem com fundo transparente ou branco.</i>\n\n"
                "O bot posicionará o logo automaticamente no topo de todos os seus novos relatórios Word (.docx) e PDF!"
            )
            keyboard = [[InlineKeyboardButton("❌ Cancelar", callback_data="btn_brand_settings")]]
            await safe_reply(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "btn_remove_logo":
            settings = database.get_user_settings(user_id)
            if settings["logo_path"] and Path(settings["logo_path"]).exists():
                try:
                    Path(settings["logo_path"]).unlink()
                except Exception:
                    pass
            database.update_user_logo(user_id, None)
            await query.answer("Logo removida com sucesso!", show_alert=True)
            settings = database.get_user_settings(user_id)
            theme_info = doc_generator.get_theme(settings["color_theme"])
            text = (
                "🏢 <b>Personalização de Marca & Cores</b>\n\n"
                "🖼️ <b>Logo da Empresa:</b> ❌ Nenhuma logo cadastrada\n"
                f"🎨 <b>Paleta de Cores:</b> <b>{theme_info['name']}</b>\n\n"
                "Personalize a aparência dos relatórios:"
            )
            await safe_reply(query, text, reply_markup=get_brand_keyboard(False))

        elif data == "btn_choose_color":
            text = (
                "🎨 <b>Escolha a Paleta de Cores do Documento</b>\n\n"
                "Os títulos, tabelas e detalhes visuais dos seus relatórios seguirão a paleta selecionada:"
            )
            await safe_reply(query, text, reply_markup=get_color_themes_keyboard())

        elif data.startswith("theme_"):
            theme_name = data.replace("theme_", "")
            database.update_user_color_theme(user_id, theme_name)
            theme_info = doc_generator.get_theme(theme_name)
            await query.answer(f"Tema alterado para: {theme_info['name']}!", show_alert=True)
            settings = database.get_user_settings(user_id)
            has_logo = bool(settings["logo_path"] and Path(settings["logo_path"]).exists())
            text = (
                "🏢 <b>Personalização de Marca & Cores</b>\n\n"
                f"🖼️ <b>Logo da Empresa:</b> {'✅ Ativa' if has_logo else '❌ Nenhuma logo cadastrada'}\n"
                f"🎨 <b>Paleta de Cores:</b> <b>{theme_info['name']}</b> (Ativa)\n\n"
                "Seus próximos relatórios serão gerados com este padrão de cores!"
            )
            await safe_reply(query, text, reply_markup=get_brand_keyboard(has_logo))

    except Exception as e:
        logger.error(f"Erro ao processar callback '{data}': {e}", exc_info=True)
        try:
            await query.answer("Ocorreu um erro ao processar esta ação.", show_alert=True)
            await safe_reply(query, f"❌ Ocorreu um erro ao processar a ação: {e}", reply_markup=get_main_keyboard())
        except Exception:
            pass

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto enviadas pelo usuário"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    text = update.message.text.strip()
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    current_state = database.get_user_state(user_id)

    if current_state == STATE_WAITING_LOGO:
        await safe_reply(
            update.message,
            "⚠️ Por favor, envie uma <b>imagem ou foto</b> (PNG ou JPG) com o logo da sua empresa.\n"
            "Ou envie /cancelar para voltar ao menu principal.",
            reply_markup=get_main_keyboard()
        )
        return

    if current_state == STATE_WAITING_TEMPLATE:
        await process_template_creation(update.message, context, user_id, raw_text=text)

    elif current_state == STATE_WAITING_ADJUSTMENT:
        await process_report_adjustment(update.message, context, user_id, feedback_text=text)

    else:
        # Por padrão no estado normal (ou WAITING_REPORT_INPUT), se o usuário enviar texto, geramos o relatório!
        await process_report_generation(update.message, context, user_id, raw_text=text)

async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa fotos enviadas pelo usuário (notas fiscais, recibos, fotos de relatórios, etc.)"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    current_state = database.get_user_state(user_id)
    
    # Foto de maior resolução
    photo = update.message.photo[-1]
    caption = (update.message.caption or "").strip()
    
    status_msg = await update.message.reply_text("📥 Recebendo imagem...")
    file = await context.bot.get_file(photo.file_id)
    
    # Se estiver aguardando envio de logo
    if current_state == STATE_WAITING_LOGO:
        logo_path = config.LOGOS_DIR / f"logo_{user_id}.png"
        await file.download_to_drive(str(logo_path))
        database.update_user_logo(user_id, str(logo_path))
        database.set_user_state(user_id, STATE_IDLE)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await safe_reply(
            update.message,
            "✅ <b>Logo da empresa cadastrado com sucesso!</b>\n\n"
            "A sua logomarca agora será inserida no topo de todos os seus novos relatórios em Word (.docx) e PDF.",
            reply_markup=get_brand_keyboard(has_logo=True)
        )
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_photo_{photo.file_unique_id}.jpg"
    local_path = config.UPLOADS_DIR / safe_name
    await file.download_to_drive(str(local_path))
    try:
        await status_msg.delete()
    except Exception:
        pass

    context.user_data["last_uploaded_photo"] = str(local_path)
    context.user_data["last_uploaded_file"] = str(local_path)
    context.bot_data[f"photo_{photo.file_id}"] = str(local_path)
    context.bot_data[f"file_{photo.file_id}"] = str(local_path)

    # Se estava esperando template explicitamente
    if current_state == STATE_WAITING_TEMPLATE:
        await process_template_creation(update.message, context, user_id, image_paths=[local_path], raw_text=caption)
        return

    # Se estava esperando entrada de relatório explicitamente
    if current_state == STATE_WAITING_REPORT_INPUT:
        await process_report_generation(update.message, context, user_id, image_paths=[local_path], raw_text=caption)
        return

    # Se estava esperando ajuste
    if current_state == STATE_WAITING_ADJUSTMENT:
        await process_report_adjustment(update.message, context, user_id, feedback_text=caption, image_paths=[local_path])
        return

    # Se enviou a foto diretamente sem comando prévio
    keyboard = [
        [
            InlineKeyboardButton("📊 Extrair Dados e Gerar Relatório", callback_data=f"act_pgen_{photo.file_id}")
        ],
        [
            InlineKeyboardButton("🎨 Usar como Modelo de Estilo", callback_data=f"act_ptpl_{photo.file_id}")
        ],
        [
            InlineKeyboardButton("❌ Cancelar", callback_data="btn_main_menu")
        ]
    ]
    caption_text = f"\nLegenda informada: <i>'{html.escape(caption)}'</i>\n" if caption else ""
    text = (
        f"📸 <b>Foto recebida com sucesso!</b>\n{caption_text}\n"
        "A I.A multimodal Gemini pode extrair notas fiscais, recibos, dados de tabelas e anotações diretamente desta foto.\n\n"
        "Como você deseja utilizá-la?"
    )
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa documentos enviados (.docx, .pdf, .txt, fotos como arquivo, etc.)"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    current_state = database.get_user_state(user_id)
    doc = update.message.document
    caption = (update.message.caption or "").strip()

    # Verifica se o documento é uma imagem (.png, .jpg, etc.)
    mime = getattr(doc, "mime_type", "") or ""
    file_name_lower = (doc.file_name or "").lower()
    is_image = mime.startswith("image/") or file_name_lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"))

    if current_state == STATE_WAITING_LOGO:
        if is_image:
            status_msg = await update.message.reply_text("📥 Salvando a logo da sua empresa...")
            file = await context.bot.get_file(doc.file_id)
            ext = Path(doc.file_name or "logo.png").suffix or ".png"
            logo_path = config.LOGOS_DIR / f"logo_{user_id}{ext}"
            await file.download_to_drive(str(logo_path))
            database.update_user_logo(user_id, str(logo_path))
            database.set_user_state(user_id, STATE_IDLE)
            try:
                await status_msg.delete()
            except Exception:
                pass
            await safe_reply(
                update.message,
                "✅ <b>Logo da empresa cadastrado com sucesso!</b>\n\n"
                "A sua logomarca agora será inserida no topo de todos os seus novos relatórios em Word (.docx) e PDF.",
                reply_markup=get_brand_keyboard(has_logo=True)
            )
            return
        else:
            await safe_reply(
                update.message,
                "⚠️ O arquivo enviado não é uma imagem válida. Por favor, envie uma imagem PNG ou JPG para sua logo.",
                reply_markup=get_brand_keyboard(False)
            )
            return

    # Faz o download do arquivo
    status_msg = await update.message.reply_text("📥 Recebendo arquivo...")
    file = await context.bot.get_file(doc.file_id)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{doc.file_name}"
    local_path = config.UPLOADS_DIR / safe_name
    await file.download_to_drive(str(local_path))
    try:
        await status_msg.delete()
    except Exception:
        pass

    context.user_data["last_uploaded_file"] = str(local_path)
    context.bot_data[f"file_{doc.file_id}"] = str(local_path)
    if is_image:
        context.user_data["last_uploaded_photo"] = str(local_path)
        context.bot_data[f"photo_{doc.file_id}"] = str(local_path)

    # Se estava esperando template explicitamente
    if current_state == STATE_WAITING_TEMPLATE:
        if is_image:
            await process_template_creation(update.message, context, user_id, image_paths=[local_path], raw_text=caption)
        else:
            await process_template_creation(update.message, context, user_id, file_path=local_path, raw_text=caption)
        return

    # Se estava esperando entrada de relatório explicitamente
    if current_state == STATE_WAITING_REPORT_INPUT:
        if is_image:
            await process_report_generation(update.message, context, user_id, image_paths=[local_path], raw_text=caption)
        else:
            await process_report_generation(update.message, context, user_id, file_path=local_path, raw_text=caption)
        return

    # Se estava esperando ajuste explicitamente
    if current_state == STATE_WAITING_ADJUSTMENT:
        if is_image:
            await process_report_adjustment(update.message, context, user_id, feedback_text=caption, image_paths=[local_path])
        return

    # Se enviou o arquivo diretamente sem comando prévio, pergunta como deseja usar:
    btn_report_text = "📊 Extrair Dados e Gerar Relatório" if is_image else "📊 Gerar Relatório com este arquivo"
    btn_action = f"act_pgen_{doc.file_id}" if is_image else f"act_gen_{doc.file_id}"
    btn_tpl_action = f"act_ptpl_{doc.file_id}" if is_image else f"act_tpl_{doc.file_id}"

    keyboard = [
        [
            InlineKeyboardButton(btn_report_text, callback_data=btn_action)
        ],
        [
            InlineKeyboardButton("🎨 Usar como Novo Modelo / Estilo", callback_data=btn_tpl_action)
        ],
        [
            InlineKeyboardButton("❌ Cancelar", callback_data="btn_main_menu")
        ]
    ]
    doc_escaped = html.escape(doc.file_name or "arquivo")
    emoji = "📸" if is_image else "📄"
    text = f"{emoji} Recebi o arquivo: <code>{doc_escaped}</code>\n\nComo você deseja utilizá-lo?"
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de voz e arquivos de áudio enviados pelo usuário via Gemini multimodal"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    current_state = database.get_user_state(user_id)

    audio_obj = update.message.voice or update.message.audio
    if not audio_obj:
        return

    caption = (update.message.caption or "").strip()
    status_msg = await update.message.reply_text("🎙️ Recebendo áudio...")
    file = await context.bot.get_file(audio_obj.file_id)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = ".ogg"
    if hasattr(audio_obj, "file_name") and audio_obj.file_name:
        ext = Path(audio_obj.file_name).suffix or ".ogg"
    safe_name = f"{timestamp}_audio_{audio_obj.file_unique_id}{ext}"
    local_path = config.UPLOADS_DIR / safe_name
    await file.download_to_drive(str(local_path))
    try:
        await status_msg.delete()
    except Exception:
        pass

    context.user_data["last_uploaded_audio"] = str(local_path)
    context.user_data["last_uploaded_file"] = str(local_path)

    if current_state == STATE_WAITING_TEMPLATE:
        await process_template_creation(update.message, context, user_id, audio_paths=[local_path], raw_text=caption)
        return

    if current_state == STATE_WAITING_ADJUSTMENT:
        await process_report_adjustment(update.message, context, user_id, feedback_text=caption, audio_paths=[local_path])
        return

    # Em WAITING_REPORT_INPUT ou envio direto de áudio no chat
    await process_report_generation(update.message, context, user_id, audio_paths=[local_path], raw_text=caption)

async def process_template_creation(message, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                    file_path: Optional[Path] = None,
                                    raw_text: Optional[str] = None,
                                    image_paths: Optional[List[Path]] = None,
                                    audio_paths: Optional[List[Path]] = None):
    """Cria e salva um novo modelo de estilo a partir de arquivo, foto, áudio ou texto"""
    status_msg = await message.reply_text("🤖 A I.A Gemini está analisando o layout e a estrutura do seu modelo...")
    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    try:
        sample_content = ""
        if file_path:
            sample_content = await asyncio.to_thread(parsers.extract_text_from_file, file_path)
        elif raw_text:
            sample_content = raw_text

        if not sample_content.strip() and not image_paths and not audio_paths:
            await status_msg.edit_text("⚠️ Não foi possível encontrar texto, imagem ou áudio para analisar.")
            return

        result = await asyncio.to_thread(
            gemini_service.analyze_and_extract_style,
            sample_text=sample_content,
            image_paths=image_paths,
            audio_paths=audio_paths,
            user_hints=raw_text or ""
        )
        tpl_name = result["name"]
        style_guide = result["style_instructions"]

        database.save_template(user_id, tpl_name, style_guide, (sample_content or "Modelo baseado em mídia")[:3000])
        database.set_user_state(user_id, STATE_IDLE)

        try:
            await status_msg.delete()
        except Exception:
            pass

        tpl_escaped = html.escape(tpl_name)
        guide_escaped = html.escape(style_guide[:1200])
        response_text = (
            f"✅ <b>Novo Modelo Salvo e Ativado com Sucesso!</b>\n\n"
            f"🏷️ <b>Nome</b>: <code>{tpl_escaped}</code>\n\n"
            f"📋 <b>Estrutura identificada pela I.A:</b>\n<code>{guide_escaped}</code>\n\n"
            "Agora qualquer dado, texto, foto ou áudio que você enviar será formatado neste padrão!"
        )
        await safe_reply(message, response_text, reply_markup=get_main_keyboard())

    except Exception as e:
        logger.error(f"Erro ao processar modelo: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ Ocorreu um erro ao processar o modelo: {e}\n\nVerifique se sua chave GEMINI_API_KEY está configurada no .env.",
            reply_markup=get_main_keyboard()
        )

async def process_report_generation(message, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                    file_path: Optional[Path] = None,
                                    raw_text: Optional[str] = None,
                                    image_paths: Optional[List[Path]] = None,
                                    audio_paths: Optional[List[Path]] = None):
    """Gera o relatório com Gemini e cria os arquivos DOCX, PDF e TXT, incorporando fotos/anexos e personalizações"""
    status_msg = await message.reply_text("🧠 <b>Processando dados com a I.A Gemini...</b>\nAguarde alguns instantes.", parse_mode="HTML")
    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    try:
        content_to_process = ""
        if file_path:
            content_to_process = await asyncio.to_thread(parsers.extract_text_from_file, file_path)
        elif raw_text:
            content_to_process = raw_text

        if not content_to_process.strip() and not image_paths and not audio_paths:
            await status_msg.edit_text("⚠️ Não há conteúdo, dados, fotos ou áudios para gerar o relatório.")
            return

        if not content_to_process.strip():
            if audio_paths and not image_paths:
                content_to_process = "Transcreva e interprete fielmente tudo o que foi falado no áudio anexo e gere um relatório executivo estruturado com todos os dados, números e decisões."
            elif image_paths and not audio_paths:
                content_to_process = "Extraia detalhadamente todos os dados, tabelas, recibos, números e informações contidas na(s) foto(s)/imagem(ns) anexa(s) e gere um relatório executivo completo."
            elif image_paths and audio_paths:
                content_to_process = "Analise o áudio explicativo em conjunto com as fotos/imagens fornecidas, combinando todos os dados visíveis e falados em um relatório executivo completo."

        active_tpl = database.get_active_template(user_id)
        if not active_tpl:
            active_tpl = {"style_instructions": "Estrutura profissional padrão com Título, Resumo, Indicadores e Conclusão."}

        # Recupera configurações de marca e tema do usuário
        user_settings = database.get_user_settings(user_id)
        user_logo = user_settings.get("logo_path")
        if user_logo and not Path(user_logo).exists():
            user_logo = None
        color_theme = user_settings.get("color_theme", "navy")

        # Gera o relatório em Markdown com Gemini de forma assíncrona
        generated_md = await asyncio.to_thread(
            gemini_service.generate_report,
            raw_content=content_to_process,
            style_instructions=active_tpl["style_instructions"],
            image_paths=image_paths,
            audio_paths=audio_paths
        )

        # Identifica o título do relatório (primeira linha com #)
        title = "Relatório Executivo"
        for line in generated_md.split("\n"):
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break

        # Cria arquivos no disco
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30]
        if not clean_title:
            clean_title = f"Relatorio_{timestamp}"
        base_name = f"{clean_title}_{timestamp}"

        docx_path = config.OUTPUTS_DIR / f"{base_name}.docx"
        pdf_path = config.OUTPUTS_DIR / f"{base_name}.pdf"
        txt_path = config.OUTPUTS_DIR / f"{base_name}.txt"

        await asyncio.to_thread(
            doc_generator.create_docx_report,
            markdown_text=generated_md,
            output_path=docx_path,
            title_hint=title,
            image_paths=image_paths,
            logo_path=user_logo,
            color_theme=color_theme
        )
        await asyncio.to_thread(
            doc_generator.create_pdf_report,
            markdown_text=generated_md,
            output_path=pdf_path,
            title_hint=title,
            image_paths=image_paths,
            logo_path=user_logo,
            color_theme=color_theme
        )
        await asyncio.to_thread(
            doc_generator.create_txt_report,
            markdown_text=generated_md,
            output_path=txt_path
        )

        # Salva no banco de dados
        database.save_report(
            user_id=user_id,
            template_id=active_tpl.get("id"),
            title=title,
            raw_input=content_to_process[:3000],
            generated_content=generated_md,
            docx_path=str(docx_path),
            pdf_path=str(pdf_path),
            txt_path=str(txt_path)
        )

        database.set_user_state(user_id, STATE_IDLE)
        try:
            await status_msg.delete()
        except Exception:
            pass

        try:
            await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        except Exception:
            pass

        # Envia os documentos gerados diretamente para o usuário
        with open(docx_path, "rb") as f_docx:
            await message.reply_document(f_docx, filename=f"{clean_title}.docx", caption=f"📄 {title} (.docx)")

        with open(pdf_path, "rb") as f_pdf:
            await message.reply_document(f_pdf, filename=f"{clean_title}.pdf", caption=f"📑 {title} (.pdf)")

        # Envia prévia e opções de ação
        title_escaped = html.escape(title)
        img_badge = "\n<i>📸 Fotos e anexos foram incluídos no documento!</i>" if image_paths else ""
        aud_badge = "\n<i>🎙️ Áudio transcrito e estruturado pela I.A!</i>" if audio_paths else ""
        preview_text = (
            f"✨ <b>Relatório Gerado com Sucesso!</b>\n\n"
            f"📌 <b>{title_escaped}</b>{img_badge}{aud_badge}\n\n"
            "Você pode baixar os arquivos acima ou solicitar alterações instantâneas clicando em <b>Ajustar / Refinar</b> abaixo:"
        )
        await safe_reply(message, preview_text, reply_markup=get_report_actions_keyboard())

    except Exception as e:
        logger.error(f"Erro ao gerar relatório: {e}", exc_info=True)
        try:
            await status_msg.edit_text(
                f"❌ Ocorreu um erro ao gerar o relatório: {e}\n\nVerifique as chaves e tente novamente.",
                reply_markup=get_main_keyboard()
            )
        except Exception:
            await safe_reply(message, f"❌ Erro ao gerar relatório: {e}", reply_markup=get_main_keyboard())

async def process_report_adjustment(message, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                    feedback_text: Optional[str] = None,
                                    image_paths: Optional[List[Path]] = None,
                                    audio_paths: Optional[List[Path]] = None):
    """Aplica ajustes ao último relatório gerado, aceitando instruções em texto, fotos ou áudios"""
    status_msg = await message.reply_text("🔄 <b>Aplicando seus ajustes ao relatório...</b>", parse_mode="HTML")
    try:
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    except Exception:
        pass

    try:
        report = database.get_latest_report(user_id)
        if not report:
            await status_msg.edit_text("Nenhum relatório encontrado para ajustar.", reply_markup=get_main_keyboard())
            return

        active_tpl = database.get_active_template(user_id)
        style_guide = active_tpl["style_instructions"] if active_tpl else ""

        fb = feedback_text or ""
        if not fb:
            if audio_paths and not image_paths:
                fb = "Aplique os ajustes e correções ditados no áudio anexo."
            elif image_paths and not audio_paths:
                fb = "Incorpore as novas informações e dados visíveis na(s) imagem(ns) anexa(s)."
            elif audio_paths and image_paths:
                fb = "Aplique os ajustes solicitados com base no áudio e imagens anexas."

        user_settings = database.get_user_settings(user_id)
        user_logo = user_settings.get("logo_path")
        if user_logo and not Path(user_logo).exists():
            user_logo = None
        color_theme = user_settings.get("color_theme", "navy")

        # Refina com Gemini em thread assíncrona
        updated_md = await asyncio.to_thread(
            gemini_service.refine_report,
            current_report=report["generated_content"],
            feedback=fb,
            style_instructions=style_guide,
            image_paths=image_paths,
            audio_paths=audio_paths
        )

        # Atualiza arquivos
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = report["title"] or "Relatório Atualizado"
        for line in updated_md.split("\n"):
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break

        clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30]
        if not clean_title:
            clean_title = f"Relatorio_rev_{timestamp}"
        base_name = f"{clean_title}_rev_{timestamp}"

        docx_path = config.OUTPUTS_DIR / f"{base_name}.docx"
        pdf_path = config.OUTPUTS_DIR / f"{base_name}.pdf"
        txt_path = config.OUTPUTS_DIR / f"{base_name}.txt"

        await asyncio.to_thread(
            doc_generator.create_docx_report,
            markdown_text=updated_md,
            output_path=docx_path,
            title_hint=title,
            image_paths=image_paths,
            logo_path=user_logo,
            color_theme=color_theme
        )
        await asyncio.to_thread(
            doc_generator.create_pdf_report,
            markdown_text=updated_md,
            output_path=pdf_path,
            title_hint=title,
            image_paths=image_paths,
            logo_path=user_logo,
            color_theme=color_theme
        )
        await asyncio.to_thread(
            doc_generator.create_txt_report,
            markdown_text=updated_md,
            output_path=txt_path
        )

        database.update_latest_report(
            report["id"],
            generated_content=updated_md,
            docx_path=str(docx_path),
            pdf_path=str(pdf_path),
            txt_path=str(txt_path)
        )

        database.set_user_state(user_id, STATE_IDLE)
        try:
            await status_msg.delete()
        except Exception:
            pass

        try:
            await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        except Exception:
            pass

        # Envia os documentos atualizados
        with open(docx_path, "rb") as f_docx:
            await message.reply_document(f_docx, filename=f"{clean_title}.docx", caption=f"📄 {title} (Atualizado)")

        with open(pdf_path, "rb") as f_pdf:
            await message.reply_document(f_pdf, filename=f"{clean_title}.pdf", caption=f"📑 {title} (Atualizado)")

        await safe_reply(
            message,
            "✅ <b>Relatório atualizado com base nos seus ajustes!</b>",
            reply_markup=get_report_actions_keyboard()
        )

    except Exception as e:
        logger.error(f"Erro ao ajustar relatório: {e}", exc_info=True)
        try:
            await status_msg.edit_text(f"❌ Ocorreu um erro ao ajustar o relatório: {e}", reply_markup=get_main_keyboard())
        except Exception:
            await safe_reply(message, f"❌ Erro ao ajustar relatório: {e}", reply_markup=get_main_keyboard())

async def cmd_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /modelo"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    database.set_user_state(user_id, STATE_WAITING_TEMPLATE)
    text = (
        "🎨 <b>Configuração de Estilo / Layout</b>\n\n"
        "Envie agora:\n"
        "1. Uma <b>foto ou imagem</b> de um modelo de relatório que você gosta;\n"
        "2. Um <b>arquivo</b> (.pdf, .docx, .txt) com um modelo/exemplo;\n"
        "3. Um <b>áudio ou mensagem de voz</b> descrevendo o estilo desejado; OU\n"
        "4. Uma <b>mensagem de texto</b> explicando como você deseja seu relatório (ex: <i>'Quero seções: Resumo, Destaques, Tabela de Indicadores, Ações. Tom executivo formal'</i>).\n\n"
        "🤖 A I.A analisará o layout e salvará como seu padrão!"
    )
    keyboard = [
        [InlineKeyboardButton("❌ Cancelar / Menu Principal", callback_data="btn_main_menu")]
    ]
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_meus_modelos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /meus_modelos"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    templates = database.get_user_templates(user_id)
    if not templates:
        await safe_reply(update.message, "Nenhum modelo cadastrado ainda.", reply_markup=get_main_keyboard())
        return

    active_tpl = database.get_active_template(user_id)
    active_id = active_tpl["id"] if active_tpl else None

    keyboard = []
    for tpl in templates:
        prefix = "✅ " if tpl["id"] == active_id else "⚪ "
        keyboard.append([InlineKeyboardButton(f"{prefix}{tpl['name']}", callback_data=f"sel_tpl_{tpl['id']}")])
    
    keyboard.append([InlineKeyboardButton("➕ Adicionar Novo Estilo", callback_data="btn_set_template")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_main_menu")])

    text = "📁 <b>Seus Modelos de Relatório Salvos:</b>\nClique em um modelo para torná-lo ativo:"
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_ajustar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ajustar"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    report = database.get_latest_report(user_id)
    if not report:
        await safe_reply(update.message, "⚠️ Nenhum relatório encontrado para ajustar. Crie um relatório primeiro!", reply_markup=get_main_keyboard())
        return
    database.set_user_state(user_id, STATE_WAITING_ADJUSTMENT)
    text = (
        "✏️ <b>Solicitar Ajustes no Relatório</b>\n\n"
        "Descreva o que deseja mudar por texto ou áudio (ex: <i>'Deixe o texto mais resumido', 'Adicione uma coluna de Responsável na tabela', 'Remova a seção de riscos'</i>)."
    )
    keyboard = [
        [InlineKeyboardButton("❌ Cancelar Ajuste", callback_data="btn_main_menu")]
    ]
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_armazenamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /armazenamento ou /disco"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    metrics = get_system_metrics()
    text = format_storage_message(metrics)
    await safe_reply(update.message, text, reply_markup=get_storage_keyboard())

async def cmd_limpar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /limpar"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    keyboard = [
        [InlineKeyboardButton("⚠️ Sim, Esvaziar Arquivos", callback_data="btn_do_clear_files")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="btn_storage_status")]
    ]
    text = (
        "🗑️ <b>Confirmação de Limpeza de Arquivos</b>\n\n"
        "Isso irá apagar permanentemente do servidor os arquivos físicos gerados (Word .docx, PDF, TXT) e anexos temporários.\n\n"
        "✅ <i>O histórico textual dos relatórios continuará salvo no seu banco de dados.</i>\n\n"
        "Deseja esvaziar agora?"
    )
    await safe_reply(update.message, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_marca(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /marca ou /cores"""
    user_id = update.effective_user.id
    if not config.is_user_allowed(user_id):
        await update.message.reply_text("⛔ Desculpe, seu usuário não está autorizado a utilizar este bot.")
        return
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    settings = database.get_user_settings(user_id)
    has_logo = bool(settings["logo_path"] and Path(settings["logo_path"]).exists())
    theme_info = doc_generator.get_theme(settings["color_theme"])
    text = (
        "🏢 <b>Personalização de Marca & Cores</b>\n\n"
        f"🖼️ <b>Logo da Empresa:</b> {'✅ Ativa' if has_logo else '❌ Nenhuma logo cadastrada'}\n"
        f"🎨 <b>Paleta de Cores:</b> <b>{theme_info['name']}</b>\n\n"
        "Personalize a identidade visual dos relatórios gerados pelo bot:"
    )
    await safe_reply(update.message, text, reply_markup=get_brand_keyboard(has_logo))

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Captura qualquer exceção não tratada e registra no log"""
    logger.error("Exceção não tratada no bot:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Ocorreu um erro temporário ao processar sua ação. Use /start para recarregar o menu principal.",
                reply_markup=get_main_keyboard()
            )
        except Exception:
            pass

BOT_START_TIME = datetime.now()
BOT_STATE = {
    "is_running": False,
    "last_error": None,
    "ping_count": 0,
    "last_ping_time": None
}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def _send_headers(self, status=200, content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_HEAD(self):
        self._send_headers(200, "text/plain")

    def do_GET(self):
        BOT_STATE["ping_count"] += 1
        BOT_STATE["last_ping_time"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        parsed_path = self.path.split("?")[0].rstrip("/")
        if parsed_path in ["/ping", "/health", "/healthz"]:
            self._send_headers(200, "application/json")
            uptime_seconds = int((datetime.now() - BOT_START_TIME).total_seconds())
            res = {
                "status": "ok" if not BOT_STATE["last_error"] else "warning",
                "bot_running": BOT_STATE["is_running"],
                "error": BOT_STATE["last_error"],
                "uptime_seconds": uptime_seconds,
                "ping_count": BOT_STATE["ping_count"],
                "last_ping": BOT_STATE["last_ping_time"],
                "model": config.GEMINI_MODEL
            }
            self.wfile.write(json.dumps(res, indent=2).encode("utf-8"))
            return

        # HTML Dashboard para quem abrir no navegador
        self._send_headers(200, "text/html; charset=utf-8")
        uptime_seconds = int((datetime.now() - BOT_START_TIME).total_seconds())
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        has_telegram = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_BOT_TOKEN != "seu_token_aqui")
        has_gemini = bool(config.GEMINI_API_KEY and config.GEMINI_API_KEY != "sua_api_key_aqui")
        is_ok = has_telegram and has_gemini and not BOT_STATE["last_error"]
        status_badge = "🟢 ONLINE 24/7" if is_ok else "🔴 ATENÇÃO REQUERIDA"

        badge_bg = "#10b981" if is_ok else "#ef4444"
        err_section = f'<div class="error-box"><b>⚠️ Detalhes do Problema:</b><br>{html.escape(str(BOT_STATE["last_error"]))}</div>' if BOT_STATE["last_error"] else ''

        html_body = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Status: Bot de Relatórios Telegram</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 1.5rem; display: flex; justify-content: center; align-items: center; min-height: 100vh; box-sizing: border-box; }}
        .card {{ background: #1e293b; border-radius: 1rem; padding: 2rem; max-width: 600px; width: 100%; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5); border: 1px solid #334155; }}
        h1 {{ margin-top: 0; font-size: 1.4rem; display: flex; align-items: center; gap: 0.5rem; }}
        .badge {{ display: inline-block; padding: 0.35rem 0.85rem; border-radius: 9999px; font-weight: bold; font-size: 0.85rem; background: {badge_bg}; color: white; margin-bottom: 1rem; }}
        .metric {{ background: #0f172a; padding: 0.75rem 1rem; border-radius: 0.5rem; margin-bottom: 0.5rem; display: flex; justify-content: space-between; font-size: 0.9rem; }}
        .metric span.value {{ font-family: monospace; font-weight: bold; }}
        .tip {{ background: #1e3a8a; border-left: 4px solid #3b82f6; padding: 0.85rem 1rem; border-radius: 0.35rem; font-size: 0.85rem; margin-top: 1.25rem; line-height: 1.5; }}
        .error-box {{ background: #7f1d1d; border-left: 4px solid #ef4444; padding: 0.85rem 1rem; border-radius: 0.35rem; font-size: 0.85rem; margin-top: 1rem; color: #fecaca; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="badge">{status_badge}</div>
        <h1>🤖 Bot de Relatórios Telegram</h1>
        <p style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 1.25rem;">Monitor de execução em nuvem e integridade do bot.</p>
        
        <div class="metric"><span>Telegram Bot:</span><span class="value">{"✅ Conectado" if has_telegram else "❌ Não configurado"}</span></div>
        <div class="metric"><span>Google Gemini API:</span><span class="value">{"✅ Configurado" if has_gemini else "❌ Não configurado"}</span></div>
        <div class="metric"><span>Modelo IA:</span><span class="value">{config.GEMINI_MODEL}</span></div>
        <div class="metric"><span>Tempo Ativo (Uptime):</span><span class="value">{uptime_str}</span></div>
        <div class="metric"><span>Pings de Manutenção:</span><span class="value">{BOT_STATE['ping_count']} requisições</span></div>
        <div class="metric"><span>Último Ping:</span><span class="value">{BOT_STATE['last_ping_time'] or 'Aguardando primeiro ping'}</span></div>
        
        {err_section}
        
        <div class="tip">
            💡 <b>Para manter rodando 24h sem hibernar no plano gratuito (Render):</b><br>
            Cadastre a URL deste site no <b>UptimeRobot.com</b> (grátis) configurando para pingar a cada 5 minutos. Isso impede que o Render suspenda o bot por inatividade!
        </div>
    </div>
</body>
</html>"""
        self.wfile.write(html_body.encode("utf-8"))

    def log_message(self, format, *args):
        pass

def _keep_alive_worker(target_url: str):
    """Thread em segundo plano que pinga a URL da aplicação para evitar o desligamento por inatividade"""
    logger.info(f"Auto Keep-Alive ativado para URL: {target_url} (intervalo: 10 minutos)")
    time.sleep(30)
    health_url = f"{target_url.rstrip('/')}/health"
    while True:
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "TelegramBotKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    logger.info("Auto Keep-Alive ping executado com sucesso.")
        except Exception as e:
            logger.debug(f"Aviso Auto Keep-Alive: {e}")
        time.sleep(600)

def _auto_cleaner_worker():
    """Thread em segundo plano que executa a limpeza de arquivos expirados periodicamente"""
    logger.info(f"Auto-limpeza ativada: expurgo de arquivos com mais de {config.AUTO_CLEAN_HOURS}h a cada hora.")
    while True:
        try:
            time.sleep(3600)  # Executa a cada 1 hora
            res = database.clean_expired_files(max_age_hours=config.AUTO_CLEAN_HOURS)
            if res["deleted_files"] > 0:
                freed_mb = res["freed_bytes"] / (1024 * 1024)
                logger.info(f"Auto-limpeza executada: {res['deleted_files']} arquivos antigos removidos ({freed_mb:.2f} MB liberados).")
        except Exception as e:
            logger.error(f"Erro na rotina de auto-limpeza: {e}")

def start_auto_cleaner():
    """Inicia thread de limpeza automática em segundo plano"""
    t = threading.Thread(target=_auto_cleaner_worker, daemon=True)
    t.start()

def start_keep_alive():
    """Verifica se há URL externa (Render, Koyeb ou variável customizada) e ativa o auto-ping"""
    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEP_ALIVE_URL") or os.getenv("APP_URL")
    if url:
        t = threading.Thread(target=_keep_alive_worker, args=(url,), daemon=True)
        t.start()

def start_health_check_server():
    """Inicia o servidor HTTP de monitoramento e keep-alive para plataformas em nuvem"""
    port = int(os.getenv("PORT", 0))
    if port:
        try:
            server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            logger.info(f"Servidor de Health Check e Monitor iniciado na porta {port}")
            start_keep_alive()
        except Exception as e:
            logger.error(f"Erro ao iniciar servidor HTTP na porta {port}: {e}")

def main():
    """Inicia o Bot Telegram"""
    start_health_check_server()
    start_auto_cleaner()
    database.init_db()

    missing = config.check_config()
    if missing:
        msg = f"As seguintes variáveis não estão configuradas: {', '.join(missing)}"
        logger.warning(
            f"\n[AVISO IMPORTANTE] {msg}\n"
            "Preencha o arquivo .env (local) ou as variáveis de ambiente na hospedagem (Render, Railway, etc.)!\n"
        )
        BOT_STATE["last_error"] = msg

    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "seu_token_aqui":
        err_msg = "TELEGRAM_BOT_TOKEN não foi configurado!"
        BOT_STATE["last_error"] = err_msg
        print("\n" + "="*70)
        print("❌ ATENÇÃO: TELEGRAM_BOT_TOKEN não foi configurado!")
        print("Se você estiver rodando na NUVEM (ex: Render, Railway, Koyeb, Alwaysdata):")
        print("👉 Acesse o painel ou console SSH e edite o arquivo .env")
        print("👉 Adicione TELEGRAM_BOT_TOKEN com o token do seu bot")
        print("👉 Adicione GEMINI_API_KEY com sua chave do Google AI Studio")
        print("Se estiver rodando LOCALMENTE no seu computador:")
        print("👉 Abra o arquivo .env e preencha as variáveis!")
        print("="*70 + "\n")

        # Se estiver rodando em nuvem com porta web ativa, mantém vivo o dashboard de diagnóstico
        if os.getenv("PORT"):
            logger.info("Mantendo servidor web ativo na nuvem para exibir página de diagnóstico...")
            try:
                while True:
                    time.sleep(3600)
            except (KeyboardInterrupt, SystemExit):
                pass
        return

    logger.info("Iniciando Bot de Relatórios no Telegram...")
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Tratamento global de erros
    app.add_error_handler(global_error_handler)

    # Comandos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_ajuda))
    app.add_handler(CommandHandler("help", cmd_ajuda))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))
    app.add_handler(CommandHandler("modelo", cmd_modelo))
    app.add_handler(CommandHandler("meus_modelos", cmd_meus_modelos))
    app.add_handler(CommandHandler("ajustar", cmd_ajustar))
    app.add_handler(CommandHandler("armazenamento", cmd_armazenamento))
    app.add_handler(CommandHandler("disco", cmd_armazenamento))
    app.add_handler(CommandHandler("limpar", cmd_limpar))
    app.add_handler(CommandHandler("marca", cmd_marca))
    app.add_handler(CommandHandler("cores", cmd_marca))

    # Callbacks inline dos botões
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Mensagens de fotos, documentos, áudios e texto
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    BOT_STATE["is_running"] = True
    BOT_STATE["last_error"] = None
    print("🚀 Bot iniciado com sucesso! Pressione Ctrl+C para encerrar.")
    try:
        app.run_polling()
    except Exception as e:
        BOT_STATE["is_running"] = False
        BOT_STATE["last_error"] = str(e)
        logger.error(f"Erro no polling do Telegram: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()


