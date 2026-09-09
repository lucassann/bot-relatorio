import logging
from typing import Optional, Dict, Any
from google import genai
from google.genai import types
import config

logger = logging.getLogger(__name__)

def get_client() -> Optional[genai.Client]:
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "sua_api_key_aqui":
        return None
    return genai.Client(api_key=config.GEMINI_API_KEY)

def analyze_and_extract_style(sample_text: str, user_hints: str = "") -> Dict[str, str]:
    """
    Analisa um documento ou instrução de exemplo para extrair:
    - Um nome sugerido para o modelo
    - Regras de layout, estrutura de seções, formatação e tom de voz
    """
    client = get_client()
    if not client:
        raise ValueError("Chave GEMINI_API_KEY não configurada no arquivo .env!")

    prompt = f"""Você é um especialista em design de documentos e padronização de relatórios corporativos.
Analise o exemplo e/ou instruções de estilo abaixo fornecidos pelo usuário:

--- EXEMPLO / INSTRUÇÕES FORNECIDAS ---
{sample_text[:12000]}
--- FIM DO EXEMPLO ---

{f'Observações extras do usuário: {user_hints}' if user_hints else ''}

Sua tarefa:
1. Identifique o formato, a estrutura de seções (ex: Título, Resumo Executivo, Indicadores, Tabelas, Conclusão), o estilo de escrita (formal, técnico, executivo, direto), e as regras de formatação.
2. Sugira um NOME curto e descritivo para este modelo (máximo 4 palavras, ex: "Relatório Executivo Semanal").
3. Escreva um GUIA DE ESTILO detalhado e objetivo que descreva a estrutura exata que os futuros relatórios desse modelo devem seguir.

Responda EXATAMENTE no seguinte formato:
NOME: [Nome sugerido aqui]
GUIA:
[Escreva aqui a estrutura de seções, o tom de voz, convenções de títulos, tópicos e tabelas recomendadas]
"""

    # Tenta usar o modelo configurado ou fallbacks
    models_to_try = [config.GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-flash-latest"]
    last_err = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=prompt
            )
            text = response.text.strip()
            
            name = "Modelo Personalizado"
            guide = text

            if "NOME:" in text and "GUIA:" in text:
                parts = text.split("GUIA:", 1)
                name_line = parts[0].replace("NOME:", "").strip()
                if name_line:
                    name = name_line.split("\n")[0].strip()
                guide = parts[1].strip()

            return {
                "name": name,
                "style_instructions": guide
            }
        except Exception as e:
            last_err = e
            logger.warning(f"Falha com modelo {m}: {e}")
            continue

    raise RuntimeError(f"Erro ao comunicar com o Gemini: {last_err}")

def generate_report(raw_content: str, style_instructions: str, extra_prompt: str = "") -> str:
    """
    Gera o relatório final aplicando o estilo e layout ativo sobre os dados brutos enviados.
    """
    client = get_client()
    if not client:
        raise ValueError("Chave GEMINI_API_KEY não configurada no arquivo .env!")

    system_instruction = """Você é um redator executivo e analista sênior de dados.
Sua missão é transformar rascunhos, dados brutos, anotações ou documentos enviados em um relatório profissional de altíssimo nível.
Você DEVE seguir rigorosamente o LAYOUT, ESTRUTURA DE SEÇÕES e ESTILO especificados no Guia de Estilo.
Formate a resposta em Markdown padrão:
- Use # para o Título Principal
- Use ## para Seções Principais
- Use ### para Subseções
- Use tabelas Markdown (| col1 | col2 |) para exibir dados comparativos, números, métricas ou status
- Use listas com marcadores (-) ou numéricas (1.) para destacar pontos importantes
- Mantenha o tom profissional e gramática impecável em Português (Brasil).
NÃO inclua blocos ```markdown no início ou fim, apenas o texto do relatório diretamente."""

    user_message = f"""--- GUIA DE ESTILO E LAYOUT A SEGUIR ---
{style_instructions}
--- FIM DO GUIA DE ESTILO ---

{f'--- PEDIDO ADICIONAL DO USUÁRIO ---\n{extra_prompt}\n--- FIM DO PEDIDO ---' if extra_prompt else ''}

--- DADOS BRUTOS / RASCUNHO PARA O RELATÓRIO ---
{raw_content}
--- FIM DOS DADOS BRUTOS ---

Gere agora o relatório completo, estruturado e formatado de acordo com o Guia de Estilo."""

    models_to_try = [config.GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-flash-latest"]
    last_err = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3
                )
            )
            return response.text.strip()
        except Exception as e:
            last_err = e
            logger.warning(f"Falha ao gerar relatório com modelo {m}: {e}")
            continue

    raise RuntimeError(f"Erro ao gerar relatório com o Gemini: {last_err}")

def refine_report(current_report: str, feedback: str, style_instructions: str = "") -> str:
    """
    Refina ou altera um relatório gerado com base nas correções do usuário.
    """
    client = get_client()
    if not client:
        raise ValueError("Chave GEMINI_API_KEY não configurada no arquivo .env!")

    system_instruction = """Você é um redator executivo e editor sênior.
Sua tarefa é modificar o relatório existente de acordo com as instruções de ajuste do usuário, mantendo a coerência, o estilo e a formatação profissional em Markdown."""

    prompt = f"""--- RELATÓRIO ATUAL ---
{current_report}
--- FIM DO RELATÓRIO ATUAL ---

{f'--- GUIA DE ESTILO ---\n{style_instructions}\n---' if style_instructions else ''}

--- AJUSTES SOLICITADOS PELO USUÁRIO ---
{feedback}
--- FIM DOS AJUSTES ---

Reescreva o relatório completo aplicando pontualmente todos os ajustes solicitados. Retorne apenas o relatório em Markdown atualizado."""

    models_to_try = [config.GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-flash-latest"]
    last_err = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3
                )
            )
            return response.text.strip()
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(f"Erro ao ajustar relatório com o Gemini: {last_err}")
