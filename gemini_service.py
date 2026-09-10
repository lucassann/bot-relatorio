import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from google import genai
from google.genai import types
import config

logger = logging.getLogger(__name__)

def get_client() -> Optional[genai.Client]:
    if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "sua_api_key_aqui":
        return None
    return genai.Client(api_key=config.GEMINI_API_KEY)

def _prepare_image_parts(image_paths: Optional[List[Path]]) -> List[types.Part]:
    """Converte caminhos de imagens em objetos Part do google-genai"""
    parts = []
    if not image_paths:
        return parts

    for img_p in image_paths:
        p = Path(img_p)
        if p.exists():
            suffix = p.suffix.lower()
            mime_type = "image/jpeg"
            if suffix == ".png":
                mime_type = "image/png"
            elif suffix == ".webp":
                mime_type = "image/webp"
            elif suffix in [".jpg", ".jpeg"]:
                mime_type = "image/jpeg"
            elif suffix == ".gif":
                mime_type = "image/gif"

            try:
                with open(p, "rb") as f:
                    data = f.read()
                parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))
            except Exception as e:
                logger.error(f"Erro ao carregar imagem {img_p}: {e}")
    return parts

def analyze_and_extract_style(sample_text: str = "", image_paths: Optional[List[Path]] = None, user_hints: str = "") -> Dict[str, str]:
    """
    Analisa um documento, texto ou foto/imagem de exemplo para extrair:
    - Um nome sugerido para o modelo
    - Regras de layout, estrutura de seções, formatação e tom de voz
    """
    client = get_client()
    if not client:
        raise ValueError("Chave GEMINI_API_KEY não configurada no arquivo .env!")

    prompt = f"""Você é um especialista em design de documentos e padronização de relatórios corporativos com visão computacional.
Analise o exemplo, documento, foto ou instruções de estilo fornecidos abaixo pelo usuário:

--- EXEMPLO / INSTRUÇÕES FORNECIDAS ---
{sample_text[:12000] if sample_text else '[Consulte a foto/imagem do modelo anexada]'}
--- FIM DO EXEMPLO ---

{f'Observações extras do usuário: {user_hints}' if user_hints else ''}

Sua tarefa:
1. Identifique o formato visual, a hierarquia de títulos, a estrutura de seções (ex: Título, Resumo, Indicadores, Tabelas, Conclusão), o estilo de escrita e o layout.
2. Sugira um NOME curto e descritivo para este modelo (máximo 4 palavras, ex: "Relatório Financeiro Fotográfico").
3. Escreva um GUIA DE ESTILO detalhado e objetivo que descreva a estrutura exata que os futuros relatórios desse modelo devem seguir.

Responda EXATAMENTE no seguinte formato:
NOME: [Nome sugerido aqui]
GUIA:
[Escreva aqui a estrutura de seções, o tom de voz, convenções de títulos, tópicos e tabelas recomendadas]
"""

    contents = []
    contents.extend(_prepare_image_parts(image_paths))
    contents.append(prompt)

    models_to_try = [config.GEMINI_MODEL, "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]
    last_err = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=contents
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

def generate_report(raw_content: str, style_instructions: str, image_paths: Optional[List[Path]] = None, extra_prompt: str = "") -> str:
    """
    Gera o relatório final aplicando o estilo e layout ativo sobre os dados brutos enviados,
    com suporte multimodal completo a extração de dados de fotos/imagens.
    """
    client = get_client()
    if not client:
        raise ValueError("Chave GEMINI_API_KEY não configurada no arquivo .env!")

    system_instruction = """Você é um redator executivo e analista sênior de dados com capacidades avançadas de OCR e visão computacional multimodal.
Sua missão é transformar rascunhos, dados brutos, anotações, documentos ou FOTOS/IMAGENS (recibos, notas fiscais, relatórios escaneados, dashboards, gráficos, planilhas impressas, lousas ou anotações manuscritas) em um relatório profissional de altíssimo nível.
Ao analisar imagens ou fotos:
1. Extraia detalhadamente todos os dados textuais, datas, nomes, tabelas, números, valores financeiros e métricas visíveis.
2. Integre perfeitamente as informações extraídas das fotos com o texto ou rascunho enviado pelo usuário.
3. Siga rigorosamente o LAYOUT, ESTRUTURA DE SEÇÕES e ESTILO especificados no Guia de Estilo.
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

--- DADOS BRUTOS / RASCUNHO FORNECIDOS ---
{raw_content if raw_content.strip() else '[Dados contidos nas imagens/fotos anexadas]'}
--- FIM DOS DADOS BRUTOS ---

Analise com atenção todas as fotos/imagens e textos fornecidos. Extraia minuciosamente todos os números, tabelas, dados e informações visíveis e gere o relatório completo estruturado de acordo com o Guia de Estilo."""

    contents = []
    image_parts = _prepare_image_parts(image_paths)
    contents.extend(image_parts)
    contents.append(user_message)

    models_to_try = [config.GEMINI_MODEL, "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]
    last_err = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=contents,
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

def refine_report(current_report: str, feedback: str, style_instructions: str = "", image_paths: Optional[List[Path]] = None) -> str:
    """
    Refina ou altera um relatório gerado com base nas correções do usuário e eventuais imagens.
    """
    client = get_client()
    if not client:
        raise ValueError("Chave GEMINI_API_KEY não configurada no arquivo .env!")

    system_instruction = """Você é um redator executivo e editor sênior.
Sua tarefa é modificar o relatório existente de acordo com as instruções de ajuste do usuário (e quaisquer dados contidos em fotos/imagens anexadas), mantendo a coerência, o estilo e a formatação profissional em Markdown."""

    prompt = f"""--- RELATÓRIO ATUAL ---
{current_report}
--- FIM DO RELATÓRIO ATUAL ---

{f'--- GUIA DE ESTILO ---\n{style_instructions}\n---' if style_instructions else ''}

--- AJUSTES SOLICITADOS PELO USUÁRIO ---
{feedback}
--- FIM DOS AJUSTES ---

Reescreva o relatório completo aplicando pontualmente todos os ajustes solicitados e incorporando os dados das fotos (se houver). Retorne apenas o relatório em Markdown atualizado."""

    contents = []
    contents.extend(_prepare_image_parts(image_paths))
    contents.append(prompt)

    models_to_try = [config.GEMINI_MODEL, "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]
    last_err = None

    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=contents,
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

def extract_data_from_image(image_path: Path, prompt_hint: str = "") -> str:
    """Extrai texto, tabelas e dados brutos de uma imagem usando OCR inteligente do Gemini"""
    client = get_client()
    if not client:
        raise ValueError("Chave GEMINI_API_KEY não configurada no arquivo .env!")

    parts = _prepare_image_parts([image_path])
    prompt = "Extraia e transcreva com exatidão todos os dados, tabelas, números, datas e textos presentes nesta imagem. Organize os dados em formato Markdown estruturado."
    if prompt_hint:
        prompt += f"\nFoco especial do usuário: {prompt_hint}"

    parts.append(prompt)
    for m in [config.GEMINI_MODEL, "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest"]:
        try:
            res = client.models.generate_content(model=m, contents=parts)
            return res.text.strip()
        except Exception as e:
            continue
    return ""

