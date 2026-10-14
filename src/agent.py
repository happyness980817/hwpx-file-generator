"""Extract customer facts and revise the required application drafts from materials."""
import json
from pathlib import Path
from openai import OpenAI, OpenAIError
from pydantic import ValidationError
from .ai import ai_ready
from .config import settings
from .draft_schema import AgentDraft, DocumentInput
from .errors import DocumentError
from .models import COUNTRIES
from urllib.parse import urlsplit

INSTRUCTIONS = Path(__file__).with_name('document_prompt.txt').read_text(encoding='utf-8')


def compose_from_materials(data, materials, request, source_notes='', history=None):
    config = settings()
    if not ai_ready():
        raise DocumentError('AI 연결이 준비되지 않았습니다. 운영자에게 문의하시거나 세부 정보에서 직접 작성해 주세요.')
    if len(request) > 4000 or len(source_notes) > 12000:
        raise DocumentError('작성 요청이 너무 깁니다. 핵심 내용으로 줄여 주세요.')
    try:
        current = DocumentInput.model_validate(data).model_dump()
        content = [{'type': 'input_text', 'text': json.dumps({'current_document': current, 'available_export_countries': COUNTRIES, 'source_notes': source_notes, 'recent_conversation': (history or [])[-8:], 'writing_request': request or '첨부 자료에서 정보를 추출하고 필작성 서류의 초안을 작성해 주세요.'}, ensure_ascii=False)}]
        for material in materials:
            part = material.input_part()
            if part['type'] == 'input_image':
                content.append({'type': 'input_text', 'text': json.dumps({'attachment_filename': material.name}, ensure_ascii=False)})
            content.append(part)
        with OpenAI(api_key=config['OPENAI_API_KEY'], timeout=300, max_retries=0) as client:
            response = client.responses.parse(model=config['OPENAI_MODEL'], store=False, max_output_tokens=20000,
                reasoning={'effort': config.get('OPENAI_REASONING_EFFORT', 'high')},
                instructions=INSTRUCTIONS, input=[{'role': 'user', 'content': content}], text_format=AgentDraft,
                tools=[{'type': 'web_search', 'search_context_size': 'medium'}],
                tool_choice='auto', max_tool_calls=4, include=['web_search_call.action.sources'])
        if response.status != 'completed' or response.output_parsed is None:
            raise DocumentError('문안 작성을 완료하지 못했습니다. 자료를 줄이거나 요청을 나누어 다시 시도해 주세요. 기존 내용은 유지됩니다.')
        result = response.output_parsed.model_dump()
        result['search_sources'] = search_sources(response)
        return result
    except (OpenAIError, ValidationError) as exc:
        raise DocumentError('자료 분석에 실패했습니다. 파일 내용과 AI 연결 상태를 확인한 뒤 다시 시도해 주세요. 기존 내용은 유지됩니다.') from exc


def search_sources(response):
    """Use tool provenance, never URLs invented inside the drafted JSON."""
    urls = []
    for item in getattr(response, 'output', []) or []:
        if getattr(item, 'type', '') == 'web_search_call' and getattr(item, 'status', '') == 'completed':
            for source in getattr(getattr(item, 'action', None), 'sources', []) or []:
                urls.append(getattr(source, 'url', ''))
        elif getattr(item, 'type', '') == 'message':
            for part in getattr(item, 'content', []):
                for annotation in getattr(part, 'annotations', []):
                    if getattr(annotation, 'type', '') == 'url_citation':
                        urls.append(getattr(annotation, 'url', ''))
    safe = []
    for url in urls:
        try:
            parts = urlsplit(url)
            if parts.scheme in ('https', 'http') and parts.hostname and not parts.username and not parts.password:
                safe.append(url)
        except ValueError:
            pass
    return list(dict.fromkeys(safe))[:30]
