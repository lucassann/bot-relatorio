import os
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
            InlineKeyboardButton("❓ Ajuda / Como Usar", callback_data="btn_help")
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
    db_user = database.get_or_create_user(user.id, user.username, user.first_name)
    database.set_user_state(user.id, STATE_IDLE)

    active_tpl = database.get_active_template(user.id)
    tpl_name = active_tpl["name"] if active_tpl else "Nenhum selecionado"

    text = (
        f"👋 Olá, *{user.first_name}*! Bem-vindo ao seu **Gerador Inteligente de Relatórios**.\n\n"
        f"🎯 **Estilo/Modelo Ativo Atual**: `{tpl_name}`\n\n"
        "Com este bot, você pode:\n"
        "1. **Definir seu Estilo/Layout**: Envie um PDF, Word (.docx), TXT ou digite como quer a estrutura do seu relatório.\n"
        "2. **Gerar Relatórios**: Envie seus dados brutos, anotações ou documentos e receba o relatório formatado em **Word (.docx)**, **PDF** e **TXT**.\n"
        "3. **Refinar e Ajustar**: Peça alterações na hora ('mude a tabela', 'adicione conclusões', 'deixe mais formal').\n\n"
        "O que deseja fazer agora?"
    )

    await update.message.reply_text(
        text=text,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )

async def cmd_ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ajuda"""
    text = (
        "📖 **Guia Rápido de Uso**:\n\n"
        "🔹 **Como definir o estilo desejado?**\n"
        "Clique em *'🎨 Definir Novo Estilo'* ou envie o comando `/modelo`.\n"
        "Em seguida, envie um arquivo (Word, PDF ou TXT) ou escreva as orientações de formato que você deseja (ex: seções obrigatórias, tom de voz, tabelas).\n\n"
        "🔹 **Como gerar um relatório?**\n"
        "Basta colar o texto com seus dados/anotações aqui no chat ou enviar um arquivo com as informações. O bot aplicará a I.A Gemini para criar o relatório segundo o modelo ativo.\n\n"
        "🔹 **Como pedir ajustes?**\n"
        "Após a geração do relatório, clique no botão *'✏️ Ajustar / Refinar'* e envie as mudanças que quiser. O documento será atualizado na hora!\n\n"
        "🔹 **Comandos rápidos**:\n"
        "• `/start` - Menu Principal\n"
        "• `/modelo` - Configurar novo modelo de layout\n"
        "• `/meus_modelos` - Listar e trocar de modelo\n"
        "• `/ajustar` - Ajustar o último relatório\n"
        "• `/cancelar` - Cancelar operação atual"
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /cancelar"""
    user_id = update.effective_user.id
    database.set_user_state(user_id, STATE_IDLE)
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Operação cancelada. Você está no menu principal.",
        reply_markup=get_main_keyboard()
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerencia cliques nos botões inline"""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    database.get_or_create_user(user_id, query.from_user.username, query.from_user.first_name)

    if data == "btn_main_menu":
        database.set_user_state(user_id, STATE_IDLE)
        active_tpl = database.get_active_template(user_id)
        tpl_name = active_tpl["name"] if active_tpl else "Nenhum"
        await query.message.reply_text(
            f"🏠 **Menu Principal**\n\n📌 Estilo ativo: `{tpl_name}`",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )

    elif data == "btn_help":
        await cmd_ajuda(query, context)

    elif data == "btn_view_template":
        active_tpl = database.get_active_template(user_id)
        if not active_tpl:
            await query.message.reply_text("Você ainda não possui nenhum estilo configurado.", reply_markup=get_main_keyboard())
            return

        text = (
            f"📋 **Estilo Ativo Atual**: *{active_tpl['name']}*\n\n"
            f"**Regras e Diretrizes do Layout:**\n{active_tpl['style_instructions'][:2500]}"
        )
        keyboard = [
            [InlineKeyboardButton("🎨 Criar Novo Modelo", callback_data="btn_set_template")],
            [InlineKeyboardButton("📁 Escolher Outro Modelo", callback_data="btn_my_templates")],
            [InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_main_menu")]
        ]
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "btn_set_template":
        database.set_user_state(user_id, STATE_WAITING_TEMPLATE)
        text = (
            "🎨 **Configuração de Estilo / Layout**\n\n"
            "Envie agora:\n"
            "1. Um **arquivo** (.pdf, .docx, .txt) com um modelo/exemplo de relatório que você gosta; OU\n"
            "2. Uma **mensagem de texto** explicando como você deseja seu relatório (ex: 'Quero seções: Resumo, Destaques, Tabela de Indicadores, Ações. Tom executivo formal').\n\n"
            "A I.A irá analisar o layout e salvar como seu padrão!"
        )
        await query.message.reply_text(text, parse_mode="Markdown")

    elif data == "btn_my_templates":
        templates = database.get_user_templates(user_id)
        if not templates:
            await query.message.reply_text("Nenhum modelo cadastrado ainda.", reply_markup=get_main_keyboard())
            return

        active_tpl = database.get_active_template(user_id)
        active_id = active_tpl["id"] if active_tpl else None

        keyboard = []
        for tpl in templates:
            prefix = "✅ " if tpl["id"] == active_id else "⚪ "
            keyboard.append([InlineKeyboardButton(f"{prefix}{tpl['name']}", callback_data=f"sel_tpl_{tpl['id']}")])
        
        keyboard.append([InlineKeyboardButton("➕ Adicionar Novo Estilo", callback_data="btn_set_template")])
        keyboard.append([InlineKeyboardButton("🏠 Voltar", callback_data="btn_main_menu")])

        await query.message.reply_text(
            "📁 **Seus Modelos de Relatório Salvos**:\nClique em um modelo para torná-lo ativo:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data.startswith("sel_tpl_"):
        tpl_id = int(data.replace("sel_tpl_", ""))
        database.set_active_template(user_id, tpl_id)
        tpl = database.get_template_by_id(tpl_id)
        tpl_name = tpl["name"] if tpl else "Modelo"
        await query.message.reply_text(
            f"✅ **Modelo Ativado**: `{tpl_name}`!\n\nAgora os seus próximos relatórios serão estruturados de acordo com este estilo.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )

    elif data == "btn_new_report":
        database.set_user_state(user_id, STATE_WAITING_REPORT_INPUT)
        active_tpl = database.get_active_template(user_id)
        tpl_name = active_tpl["name"] if active_tpl else "Padrão"
        await query.message.reply_text(
            f"🚀 **Criar Novo Relatório** (Modelo: `{tpl_name}`)\n\n"
            "Envie agora o rascunho, anotações, dados ou envie um arquivo (.txt, .pdf, .docx) com as informações do relatório.\n"
            "A I.A processará os dados e criará os arquivos Word e PDF automaticamente!",
            parse_mode="Markdown"
        )

    elif data == "btn_adjust":
        report = database.get_latest_report(user_id)
        if not report:
            await query.message.reply_text("Nenhum relatório encontrado para ajustar. Crie um relatório primeiro!", reply_markup=get_main_keyboard())
            return
        database.set_user_state(user_id, STATE_WAITING_ADJUSTMENT)
        await query.message.reply_text(
            "✏️ **Solicitar Ajustes no Relatório**\n\n"
            "Descreva o que deseja mudar (ex: 'Deixe o texto mais resumido', 'Adicione uma coluna de Responsável na tabela', 'Remova a seção de riscos').",
            parse_mode="Markdown"
        )

    elif data == "btn_dl_docx":
        report = database.get_latest_report(user_id)
        if report and report["docx_path"] and Path(report["docx_path"]).exists():
            with open(report["docx_path"], "rb") as f:
                await query.message.reply_document(f, filename=Path(report["docx_path"]).name, caption="📄 Relatório em Microsoft Word (.docx)")
        else:
            await query.message.reply_text("Arquivo DOCX não disponível. Gere um relatório primeiro!")

    elif data == "btn_dl_pdf":
        report = database.get_latest_report(user_id)
        if report and report["pdf_path"] and Path(report["pdf_path"]).exists():
            with open(report["pdf_path"], "rb") as f:
                await query.message.reply_document(f, filename=Path(report["pdf_path"]).name, caption="📑 Relatório em PDF")
        else:
            await query.message.reply_text("Arquivo PDF não disponível. Gere um relatório primeiro!")

    elif data == "btn_dl_txt":
        report = database.get_latest_report(user_id)
        if report and report["txt_path"] and Path(report["txt_path"]).exists():
            with open(report["txt_path"], "rb") as f:
                await query.message.reply_document(f, filename=Path(report["txt_path"]).name, caption="📝 Relatório em Texto Puro (.txt)")
        else:
            await query.message.reply_text("Arquivo TXT não disponível.")

    elif data.startswith("act_gen_"):
        # Usuário clicou em 'Gerar Relatório a partir deste arquivo'
        file_path_str = context.user_data.get("last_uploaded_file")
        if not file_path_str or not Path(file_path_str).exists():
            await query.message.reply_text("Arquivo não encontrado. Por favor, envie novamente.")
            return
        await process_report_generation(query.message, context, user_id, file_path=Path(file_path_str))

    elif data.startswith("act_tpl_"):
        # Usuário clicou em 'Usar este arquivo como Modelo de Estilo'
        file_path_str = context.user_data.get("last_uploaded_file")
        if not file_path_str or not Path(file_path_str).exists():
            await query.message.reply_text("Arquivo não encontrado. Por favor, envie novamente.")
            return
        await process_template_creation(query.message, context, user_id, file_path=Path(file_path_str))

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa mensagens de texto enviadas pelo usuário"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    db_user = database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    current_state = database.get_user_state(user_id)

    if current_state == STATE_WAITING_TEMPLATE:
        await process_template_creation(update.message, context, user_id, raw_text=text)

    elif current_state == STATE_WAITING_ADJUSTMENT:
        await process_report_adjustment(update.message, context, user_id, feedback_text=text)

    else:
        # Por padrão no estado normal (ou WAITING_REPORT_INPUT), se o usuário enviar texto, geramos o relatório!
        await process_report_generation(update.message, context, user_id, raw_text=text)

async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa documentos enviados (.docx, .pdf, .txt, etc.)"""
    user_id = update.effective_user.id
    db_user = database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    current_state = database.get_user_state(user_id)
    doc = update.message.document

    # Faz o download do arquivo
    status_msg = await update.message.reply_text("📥 Recebendo arquivo...")
    file = await context.bot.get_file(doc.file_id)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{doc.file_name}"
    local_path = config.UPLOADS_DIR / safe_name
    await file.download_to_drive(str(local_path))
    await status_msg.delete()

    context.user_data["last_uploaded_file"] = str(local_path)

    # Se estava esperando template explicitamente
    if current_state == STATE_WAITING_TEMPLATE:
        await process_template_creation(update.message, context, user_id, file_path=local_path)
        return

    # Se estava esperando entrada de relatório explicitamente
    if current_state == STATE_WAITING_REPORT_INPUT:
        await process_report_generation(update.message, context, user_id, file_path=local_path)
        return

    # Se enviou o arquivo diretamente sem comando prévio, pergunta como deseja usar:
    keyboard = [
        [
            InlineKeyboardButton("📊 Gerar Relatório com este arquivo", callback_data=f"act_gen_{doc.file_id}")
        ],
        [
            InlineKeyboardButton("🎨 Usar como Novo Modelo / Estilo", callback_data=f"act_tpl_{doc.file_id}")
        ],
        [
            InlineKeyboardButton("❌ Cancelar", callback_data="btn_main_menu")
        ]
    ]
    await update.message.reply_text(
        f"📄 Recebi o arquivo: `{doc.file_name}`\n\nComo você deseja utilizá-lo?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def process_template_creation(message, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                    file_path: Optional[Path] = None, raw_text: Optional[str] = None):
    """Cria e salva um novo modelo de estilo a partir de arquivo ou texto"""
    status_msg = await message.reply_text("🤖 A I.A Gemini está analisando o layout e a estrutura do seu modelo...")

    try:
        sample_content = ""
        if file_path:
            sample_content = parsers.extract_text_from_file(file_path)
        elif raw_text:
            sample_content = raw_text

        if not sample_content.strip():
            await status_msg.edit_text("⚠️ Não foi possível encontrar texto ou conteúdo para analisar.")
            return

        result = gemini_service.analyze_and_extract_style(sample_content)
        tpl_name = result["name"]
        style_guide = result["style_instructions"]

        tpl_id = database.save_template(user_id, tpl_name, style_guide, sample_content[:3000])
        database.set_user_state(user_id, STATE_IDLE)

        await status_msg.delete()
        response_text = (
            f"✅ **Novo Modelo Salvo e Ativado com Sucesso!**\n\n"
            f"🏷️ **Nome**: `{tpl_name}`\n\n"
            f"📋 **Estrutura identificada pela I.A:**\n{style_guide[:1200]}\n\n"
            "Agora qualquer dado ou rascunho que você enviar será formatado neste padrão!"
        )
        await message.reply_text(response_text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Erro ao processar modelo: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ocorreu um erro ao processar o modelo: {e}\n\nVerifique se sua chave `GEMINI_API_KEY` está configurada corretamente no `.env`.")

async def process_report_generation(message, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                    file_path: Optional[Path] = None, raw_text: Optional[str] = None):
    """Gera o relatório com Gemini e cria os arquivos DOCX, PDF e TXT"""
    status_msg = await message.reply_text("🧠 **Gerando seu relatório com a I.A Gemini...**\nAguarde alguns instantes.")

    try:
        content_to_process = ""
        if file_path:
            content_to_process = parsers.extract_text_from_file(file_path)
        elif raw_text:
            content_to_process = raw_text

        if not content_to_process.strip():
            await status_msg.edit_text("⚠️ Não há conteúdo ou dados para gerar o relatório.")
            return

        active_tpl = database.get_active_template(user_id)
        if not active_tpl:
            active_tpl = {"style_instructions": "Estrutura profissional padrão com Título, Resumo, Indicadores e Conclusão."}

        # Gera o relatório em Markdown com Gemini
        generated_md = gemini_service.generate_report(content_to_process, active_tpl["style_instructions"])

        # Identifica o título do relatório (primeira linha com #)
        title = "Relatório Executivo"
        for line in generated_md.split("\n"):
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break

        # Cria arquivos no disco
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30]
        base_name = f"{clean_title}_{timestamp}"

        docx_path = config.OUTPUTS_DIR / f"{base_name}.docx"
        pdf_path = config.OUTPUTS_DIR / f"{base_name}.pdf"
        txt_path = config.OUTPUTS_DIR / f"{base_name}.txt"

        doc_generator.create_docx_report(generated_md, docx_path, title_hint=title)
        doc_generator.create_pdf_report(generated_md, pdf_path, title_hint=title)
        doc_generator.create_txt_report(generated_md, txt_path)

        # Salva no banco de dados
        report_id = database.save_report(
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
        await status_msg.delete()

        # Envia os documentos gerados diretamente para o usuário
        with open(docx_path, "rb") as f_docx:
            await message.reply_document(f_docx, filename=f"{clean_title}.docx", caption=f"📄 **{title}** (.docx)")

        with open(pdf_path, "rb") as f_pdf:
            await message.reply_document(f_pdf, filename=f"{clean_title}.pdf", caption=f"📑 **{title}** (.pdf)")

        # Envia prévia do texto e opções de ação
        preview_text = (
            f"✨ **Relatório Gerado com Sucesso!**\n\n"
            f"📌 **{title}**\n\n"
            f"Você pode baixar os arquivos acima ou solicitar alterações instantâneas clicando em *Ajustar / Refinar*."
        )
        await message.reply_text(preview_text, reply_markup=get_report_actions_keyboard(), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Erro ao gerar relatório: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ocorreu um erro ao gerar o relatório: {e}\n\nVerifique as chaves e modelos configurados.")

async def process_report_adjustment(message, context: ContextTypes.DEFAULT_TYPE, user_id: int, feedback_text: str):
    """Aplica ajustes ao último relatório gerado"""
    status_msg = await message.reply_text("🔄 **Aplicando seus ajustes ao relatório...**")

    try:
        report = database.get_latest_report(user_id)
        if not report:
            await status_msg.edit_text("Nenhum relatório encontrado para ajustar.")
            return

        active_tpl = database.get_active_template(user_id)
        style_guide = active_tpl["style_instructions"] if active_tpl else ""

        # Refina com Gemini
        updated_md = gemini_service.refine_report(report["generated_content"], feedback_text, style_guide)

        # Atualiza arquivos
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title = report["title"] or "Relatório Atualizado"
        for line in updated_md.split("\n"):
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break

        clean_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:30]
        base_name = f"{clean_title}_rev_{timestamp}"

        docx_path = config.OUTPUTS_DIR / f"{base_name}.docx"
        pdf_path = config.OUTPUTS_DIR / f"{base_name}.pdf"
        txt_path = config.OUTPUTS_DIR / f"{base_name}.txt"

        doc_generator.create_docx_report(updated_md, docx_path, title_hint=title)
        doc_generator.create_pdf_report(updated_md, pdf_path, title_hint=title)
        doc_generator.create_txt_report(updated_md, txt_path)

        database.update_latest_report(
            report["id"],
            generated_content=updated_md,
            docx_path=str(docx_path),
            pdf_path=str(pdf_path),
            txt_path=str(txt_path)
        )

        database.set_user_state(user_id, STATE_IDLE)
        await status_msg.delete()

        # Envia os documentos atualizados
        with open(docx_path, "rb") as f_docx:
            await message.reply_document(f_docx, filename=f"{clean_title}.docx", caption=f"📄 **{title}** (Atualizado)")

        with open(pdf_path, "rb") as f_pdf:
            await message.reply_document(f_pdf, filename=f"{clean_title}.pdf", caption=f"📑 **{title}** (Atualizado)")

        await message.reply_text(
            "✅ **Relatório atualizado com base nos seus ajustes!**",
            reply_markup=get_report_actions_keyboard(),
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Erro ao ajustar relatório: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Ocorreu um erro ao ajustar o relatório: {e}")

async def cmd_modelo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /modelo"""
    user_id = update.effective_user.id
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    database.set_user_state(user_id, STATE_WAITING_TEMPLATE)
    text = (
        "🎨 **Configuração de Estilo / Layout**\n\n"
        "Envie agora:\n"
        "1. Um **arquivo** (.pdf, .docx, .txt) com um modelo/exemplo de relatório que você gosta; OU\n"
        "2. Uma **mensagem de texto** explicando como você deseja seu relatório (ex: 'Quero seções: Resumo, Destaques, Tabela de Indicadores, Ações. Tom executivo formal').\n\n"
        "A I.A irá analisar o layout e salvar como seu padrão!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_meus_modelos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /meus_modelos"""
    user_id = update.effective_user.id
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    templates = database.get_user_templates(user_id)
    if not templates:
        await update.message.reply_text("Nenhum modelo cadastrado ainda.", reply_markup=get_main_keyboard())
        return

    active_tpl = database.get_active_template(user_id)
    active_id = active_tpl["id"] if active_tpl else None

    keyboard = []
    for tpl in templates:
        prefix = "✅ " if tpl["id"] == active_id else "⚪ "
        keyboard.append([InlineKeyboardButton(f"{prefix}{tpl['name']}", callback_data=f"sel_tpl_{tpl['id']}")])
    
    keyboard.append([InlineKeyboardButton("➕ Adicionar Novo Estilo", callback_data="btn_set_template")])
    keyboard.append([InlineKeyboardButton("🏠 Menu Principal", callback_data="btn_main_menu")])

    await update.message.reply_text(
        "📁 **Seus Modelos de Relatório Salvos**:\nClique em um modelo para torná-lo ativo:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def cmd_ajustar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ajustar"""
    user_id = update.effective_user.id
    database.get_or_create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    report = database.get_latest_report(user_id)
    if not report:
        await update.message.reply_text("Nenhum relatório encontrado para ajustar. Crie um relatório primeiro!", reply_markup=get_main_keyboard())
        return
    database.set_user_state(user_id, STATE_WAITING_ADJUSTMENT)
    await update.message.reply_text(
        "✏️ **Solicitar Ajustes no Relatório**\n\n"
        "Descreva o que deseja mudar (ex: 'Deixe o texto mais resumido', 'Adicione uma coluna de Responsável na tabela', 'Remova a seção de riscos').",
        parse_mode="Markdown"
    )

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot de Relatorios online no Render!")

    def log_message(self, format, *args):
        pass  # Silencia logs de health check para manter o terminal limpo

def start_health_check_server():
    """Inicia um mini servidor HTTP para plataformas em nuvem como o Render.com"""
    port = int(os.getenv("PORT", 0))
    if port:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Servidor de Health Check iniciado na porta {port} para o Render")

def main():
    """Inicia o Bot Telegram"""
    start_health_check_server()
    database.init_db()

    missing = config.check_config()
    if missing:
        logger.warning(
            f"\n[AVISO IMPORTANTE] As seguintes variáveis não estão configuradas no .env: {', '.join(missing)}\n"
            "Preencha o arquivo .env com o TELEGRAM_BOT_TOKEN e a GEMINI_API_KEY antes de iniciar o bot em produção!\n"
        )

    if not config.TELEGRAM_BOT_TOKEN or config.TELEGRAM_BOT_TOKEN == "seu_token_aqui":
        print("\n" + "="*70)
        print("❌ ATENÇÃO: TELEGRAM_BOT_TOKEN não foi configurado no arquivo .env!")
        print("1. Abra o arquivo .env")
        print("2. Insira o token do seu bot obtido no @BotFather do Telegram")
        print("3. Insira a sua GEMINI_API_KEY obtida no Google AI Studio")
        print("4. Execute novamente: ./run.sh ou python bot.py")
        print("="*70 + "\n")
        return

    logger.info("Iniciando Bot de Relatórios no Telegram...")
    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ajuda", cmd_ajuda))
    app.add_handler(CommandHandler("help", cmd_ajuda))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))
    app.add_handler(CommandHandler("modelo", cmd_modelo))
    app.add_handler(CommandHandler("meus_modelos", cmd_meus_modelos))
    app.add_handler(CommandHandler("ajustar", cmd_ajustar))

    # Callbacks inline
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Mensagens de texto e documentos
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    print("🚀 Bot iniciado com sucesso! Pressione Ctrl+C para encerrar.")
    app.run_polling()

if __name__ == "__main__":
    main()
