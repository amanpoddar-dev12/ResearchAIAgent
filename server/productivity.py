"""Owned collections, explicit report sharing, and bounded research alerts."""
import asyncio
import hashlib
import time
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from app.models import ResearchState, ResearchQuestion, Source, StructuredReport
from app.assistant_context import AssistantRequest
from server import workspace

router = APIRouter()
logger = logging.getLogger(__name__)
class CheckpointChoice(BaseModel):
    token: str = Field(max_length=32)
    gap_ids: list[str] = Field(default_factory=list, max_length=3)


@router.post('/api/research/{identifier}/checkpoint')
async def resume_checkpoint(identifier: str, choice: CheckpointChoice):
    from server.api.research import jobs, _event
    job = jobs.get(identifier)
    if not job or not job.review_future or job.review_future.done() or choice.token != job.review_token:
        raise HTTPException(409, 'This checkpoint is no longer waiting for a decision.')
    if not set(choice.gap_ids) <= job.review_gaps:
        raise HTTPException(400, 'Unknown evidence gap.')
    job.review_future.set_result(list(dict.fromkeys(choice.gap_ids)))
    # The agent resumes through the normal progress stream.
    return {'resumed': True}


class Collection(BaseModel):
    id: str = Field(max_length=150)
    name: str = Field(min_length=1, max_length=100)
    researchIds: list[str] = Field(default_factory=list, max_length=10)
    chatIds: list[str] = Field(default_factory=list, max_length=10)
    pdfIds: list[str] = Field(default_factory=list, max_length=5)


class Feedback(BaseModel):
    id: str = Field(max_length=150)
    researchId: str = Field(max_length=150)
    section: str = Field(max_length=150)
    category: str = Field(pattern=r'^(Helpful|Missing information|Citation issue)$')
    note: str = Field(default='', max_length=2000)
    createdAt: str = Field(max_length=60)


async def validate_productivity(owner, kind, payload):
    from pydantic import ValidationError
    try:
        item = (Collection if kind == 'collection' else Feedback).model_validate(payload)
    except ValidationError:
        raise HTTPException(400, 'Invalid collection or feedback fields.') from None
    if kind == 'feedback' and item.category != 'Helpful' and not item.note.strip():
        raise HTTPException(400, 'Describe the missing information or citation issue.')
    references = [('research', identifier) for identifier in item.researchIds] + [('chat', identifier) for identifier in item.chatIds] + [('pdf', identifier) for identifier in item.pdfIds] if kind == 'collection' else [('research', item.researchId)]
    for record_kind, identifier in references:
        workspace.validate_record(record_kind, identifier)
        if not await workspace.load(owner, record_kind, identifier):
            raise HTTPException(404, 'An attached item is missing from your workspace.')
    return item.model_dump()


async def collection_state(owner: str, identifier: str) -> ResearchState:
    record = await workspace.load(owner, 'collection', identifier)
    if not record:
        raise HTTPException(404, 'Collection not found.')
    collection = Collection.model_validate(record)
    sources, reports = [], []
    for kind, identifiers in [('research', collection.researchIds), ('chat', collection.chatIds), ('pdf', collection.pdfIds)]:
        for entry in identifiers:
            item = await workspace.load(owner, kind, entry)
            if not item:
                continue  # Removed items never remain as retained copies in a collection.
            if kind == 'research':
                # Each source becomes a uniquely numbered collection source. Original
                # findings remain report text, not newly validated merged claims.
                mapping = {}
                for source in item.get('sources', []):
                    new_id = f'S{len(sources) + 1}'
                    mapping[str(source['id'])] = new_id
                    sources.append(Source.model_validate({**source, 'id': new_id, 'content': source.get('content', ''), 'title': f"{item.get('question', 'Research')}: {source.get('title', '')}"}))
                text = item.get('report', '')
                original = item.get('sources', [])
                def remap(match):
                    references = []
                    for token in re.split(r'\s*[,;]\s*', match[1]):
                        old = token if token.startswith('S') else str(original[int(token)-1]['id']) if 0 < int(token) <= len(original) else ''
                        references.append(f'[{mapping[old]}]' if old in mapping else '[citation unavailable]')
                    return ' '.join(references)
                text = re.sub(r'\[((?:S\d+|\d+)(?:\s*[,;]\s*(?:S\d+|\d+))*)\](?!\()', remap, text)
                new = Source(id=f'S{len(sources)+1}', title=f"Saved report: {item.get('question', 'Research')}", url='', domain='saved report', content=text)
                sources.append(new)
                reports.append(f"Saved research (not independently reverified): {new.title} [{new.id}]")
            else:
                text = '\n\n'.join(f"Page {page['page']}: {page['text']}" for page in item.get('pages', [])) if kind == 'pdf' else '\n'.join(f"{message.get('role')}: {message.get('content', '')}" for message in item.get('messages', []))
                if text:
                    new = Source(id=f'S{len(sources)+1}', title=item.get('name') or item.get('title') or kind, url='', domain='uploaded PDF' if kind == 'pdf' else 'conversation (unverified)', content=text)
                    sources.append(new)
                    reports.append(f"{new.title} [{new.id}]. {'Conversation statements are not verified evidence.' if kind == 'chat' else 'Cite the page number from retrieved text.'}")
    if sum(len(source.content.encode()) for source in sources) > 16_000_000:
        raise HTTPException(413, 'This collection is too large for one chat. Use a smaller collection.')
    return ResearchState(question=ResearchQuestion(question=f'Research collection: {collection.name}'), sources=sources, final_report=('\n'.join(reports) or 'The collection has no readable content.') + '\nUse only the current source catalog citation IDs. Original claim/evidence identifiers inside saved reports are historical references, not merged or reverified claims.', status='complete')


@router.get('/api/library/collections/{identifier}/context')
async def get_collection(identifier: str, request: Request):
    return (await collection_state(request.state.user['id'], identifier)).model_dump(mode='json')


class CollectionChatRequest(AssistantRequest):
    conversation_id: str = Field(pattern=r'^general-chat-[a-fA-F0-9-]{36}$')


@router.post('/api/library/collections/{identifier}/chat')
async def collection_chat(identifier: str, body: CollectionChatRequest, request: Request):
    from server.api.research import stream_chat, jobs, ResearchJob
    state = await collection_state(request.state.user['id'], identifier)
    body.saved_state = None
    body.pdf_context = None
    body.retrieval = None
    temporary = f'general-chat-{uuid4()}'
    jobs[temporary] = ResearchJob(state=state, done=True, finished_at=time.monotonic(), owner_id=request.state.user['id'])
    async def answer():
        try:
            async for event in stream_chat(temporary, body, response_id=body.conversation_id):
                yield event
        finally:
            jobs.pop(temporary, None)
    return StreamingResponse(answer(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})


def share_snapshot(item: dict) -> dict:
    # Explicitly whitelist the published document. No chat, PDF text, audit,
    # extracted source bodies, owner identity or session state is exposed.
    structured = item.get('structuredReport') or (item.get('state') or {}).get('structured_report')
    if structured:
        try:
            structured = StructuredReport.model_validate(structured).model_dump(mode='json')
            # Visual rows are open dictionaries internally; publish only displayed cells.
            for kind, row_key in [('charts', 'data'), ('tables', 'rows')]:
                for visual in structured[kind]:
                    columns = {visual['x_key'], *(series['key'] for series in visual['series'])} if kind == 'charts' else set(visual['columns'])
                    visual[row_key] = [{key: value for key, value in row.items()
                        if key in columns and (value is None or isinstance(value, (str, int, float, bool)))} for row in visual[row_key]]
        except (ValidationError, ValueError, TypeError):
            structured = None  # Legacy Markdown remains available if imported visuals are invalid.
    return {'question': item.get('question', ''), 'report': item.get('report', ''), 'structuredReport': structured,
            'sources': [{key: source[key] for key in ('id', 'title', 'url', 'domain', 'publication_date', 'source_type') if key in source} for source in item.get('sources', [])], 'savedAt': item.get('savedAt')}


@router.post('/api/library/shares/{identifier}')
async def create_share(identifier: str, request: Request):
    item = await workspace.load(request.state.user['id'], 'research', identifier)
    if not item or not item.get('report'):
        raise HTTPException(404, 'Completed report not found.')
    token = secrets.token_urlsafe(32)
    await workspace.remote('POST', '/rest/v1/report_shares?on_conflict=owner_id,research_id', headers={'Prefer': 'resolution=merge-duplicates'}, json={
        'owner_id': request.state.user['id'], 'research_id': identifier, 'token_hash': hashlib.sha256(token.encode()).hexdigest(), 'payload': share_snapshot(item),
        'expires_at': (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()})
    return {'token': token, 'expiresInDays': 30}


@router.delete('/api/library/shares/{identifier}')
async def revoke_share(identifier: str, request: Request):
    await workspace.remote('DELETE', f'/rest/v1/report_shares?owner_id=eq.{quote(request.state.user["id"],safe="")}&research_id=eq.{quote(identifier,safe="")}')
    return {'revoked': True}


@router.get('/api/public/reports/{token}')
async def public_report(token: str):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(404, 'Shared report not found.')
    digest = hashlib.sha256(token.encode()).hexdigest()
    rows = await workspace.remote('GET', f'/rest/v1/report_shares?token_hash=eq.{digest}&expires_at=gt.{quote(datetime.now(timezone.utc).isoformat(),safe="")}&select=payload,owner_id,research_id')
    if not rows or not await workspace.load(rows[0]['owner_id'], 'research', rows[0]['research_id']):
        raise HTTPException(404, 'This share expired or was revoked.')
    from fastapi.responses import JSONResponse
    return JSONResponse(share_snapshot(rows[0]['payload']), headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow'})


class AlertRequest(BaseModel):
    research_id: str = Field(min_length=1, max_length=150)
    interval_days: Literal[1, 7] = 7


def member(request: Request):
    user = request.state.user
    if user.get('is_anonymous'):
        raise HTTPException(403, 'Sign in with Google to use scheduled research alerts.')
    return user['id']


@router.get('/api/library/alerts')
async def list_alerts(request: Request):
    owner = member(request)
    return await workspace.remote('GET', f'/rest/v1/research_alerts?owner_id=eq.{quote(owner,safe="")}&order=next_run.asc')


@router.post('/api/library/alerts')
async def add_alert(body: AlertRequest, request: Request):
    owner = member(request)
    report = await workspace.load(owner, 'research', body.research_id)
    if not report or not report.get('report'):
        raise HTTPException(404, 'Completed research not found.')
    accepted = await workspace.remote('POST', '/rest/v1/rpc/create_research_alert', json={'p_owner': owner, 'p_research': body.research_id, 'p_days': body.interval_days})
    if not accepted:
        raise HTTPException(409, 'You already have an alert for this report or three active alerts. Pause one to add another.')
    return {'created': True}


class AlertSwitch(BaseModel):
    enabled: bool


@router.patch('/api/library/alerts/{identifier}')
async def switch_alert(identifier: str, body: AlertSwitch, request: Request):
    owner = member(request)
    # Resume is atomic and observes the same per-owner active limit.
    accepted = await workspace.remote('POST', '/rest/v1/rpc/switch_research_alert', json={'p_owner': owner, 'p_id': identifier, 'p_enabled': body.enabled})
    if not accepted:
        raise HTTPException(409, 'Alert not found or the three-active-alert limit was reached.')
    return {'updated': True}


async def run_due_alert():
    from server.api.models import ResearchRequest
    from server.api.research import start_research, jobs, MAX_ACTIVE_JOBS
    if sum(not job.done for job in jobs.values()) >= MAX_ACTIVE_JOBS:
        return
    alerts = await workspace.remote('POST', '/rest/v1/rpc/claim_research_alert', json={})
    for alert in alerts or []:
        path = f'/rest/v1/research_alerts?id=eq.{quote(alert["id"],safe="")}&owner_id=eq.{quote(alert["owner_id"],safe="")}'
        try:
            original = await workspace.load(alert['owner_id'], 'research', alert['research_id'])
            if not original or not original.get('state'):
                await workspace.remote('PATCH', path, json={'enabled': False, 'status': 'Original report removed; alert paused.'})
                continue
            identifier = await start_research(ResearchRequest(question=f"Update this research with recent primary evidence: {original['question']}", mode='quick', depth='quick', max_sources=5,
                parent_research_id=alert['research_id'], brief=original['state'].get('brief', {})), {'id': alert['owner_id'], 'is_anonymous': False})
            await workspace.remote('PATCH', path, json={'last_research_id': identifier})
            await jobs[identifier].task
            job = jobs[identifier]
            if job.error or not job.state:
                raise RuntimeError('Research did not complete')
            old = original['state']
            known = {item['claim'].strip().casefold(): item.get('evidence_status') for item in old.get('findings', [])}
            changed = sum(known.get(item.claim.strip().casefold()) != item.evidence_status for item in job.state.findings)
            new_sources = len({source.url for source in job.state.sources} - {source['url'] for source in old.get('sources', [])})
            await workspace.remote('PATCH', path, json={'status': f'Updated report: {changed} changed/new claim record(s), {new_sources} new source URL(s). These are record changes, not proof of new discoveries.', 'has_update': bool(changed or new_sources)})
        except Exception:
            logger.warning('Scheduled research could not complete for alert %s', alert['id'])
            await workspace.remote('PATCH', path, json={'status': 'Scheduled run failed or was interrupted. Retry at the next scheduled time.', 'has_update': False})


async def alert_worker():
    # Durable dates and atomic claims survive restarts; delivery still requires
    # an awake backend. Deploy on an always-on worker for exact scheduled timing.
    while True:
        try:
            if workspace.configured():
                await run_due_alert()
        except Exception:
            logger.debug('Alert scheduling unavailable; migration or backend configuration may be pending.')
        await asyncio.sleep(60)
