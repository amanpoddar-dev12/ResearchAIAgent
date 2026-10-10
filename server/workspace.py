"""Supabase HTTP integration. Secrets and ownership decisions stay on the server."""
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request
from app.config import Settings


def configured() -> bool:
    settings = Settings()
    return bool(settings.supabase_url or settings.supabase_publishable_key or settings.supabase_secret_key)


async def remote(method: str, path: str, *, token: str | None = None, **kwargs):
    settings = Settings()
    key = settings.supabase_secret_key if token is None else settings.supabase_publishable_key
    if not settings.supabase_url or not key:
        raise HTTPException(503, "Supabase configuration is incomplete. See docs/SUPABASE_SETUP.md.")
    headers = {"apikey": key, **kwargs.pop("headers", {})}
    # Modern sb_secret keys are API keys, not JWTs. Legacy service-role keys are JWTs.
    if token or key.startswith('eyJ'):
        headers['Authorization'] = f'Bearer {token or key}'
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            result = await client.request(method, settings.supabase_url.rstrip('/') + path, headers=headers, **kwargs)
        if not result.is_success:
            # Do not expose Supabase responses, credentials or SQL details.
            raise HTTPException(503, "Cloud storage is unavailable. Check Supabase configuration and migrations.")
        return result.json() if result.content else None
    except httpx.HTTPError:
        raise HTTPException(503, "Cloud storage could not be reached. Please retry.") from None


async def authenticate(request: Request) -> dict | None:
    if not configured():
        return None
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    if not token or len(token) > 12000:
        raise HTTPException(401, "Sign in or start a guest session to continue.")
    settings = Settings()
    if not settings.supabase_url or not settings.supabase_publishable_key or not settings.supabase_secret_key:
        raise HTTPException(503, 'Supabase configuration is incomplete. See docs/SUPABASE_SETUP.md.')
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(settings.supabase_url.rstrip('/') + '/auth/v1/user',
                headers={'apikey': settings.supabase_publishable_key, 'Authorization': f'Bearer {token}'})
        if response.status_code in (401, 403):
            raise HTTPException(401, "Your session expired. Please sign in again.")
        if not response.is_success:
            raise HTTPException(503, "Authentication is temporarily unavailable.")
        user = response.json()
        if not user.get('id'):
            raise HTTPException(401, "Invalid session.")
        return user
    except httpx.HTTPError:
        raise HTTPException(503, "Authentication could not be reached.") from None


def record_path(owner: str, kind: str, identifier: str | None = None) -> str:
    path = f'/rest/v1/workspace_records?owner_id=eq.{quote(owner,safe="")}&kind=eq.{kind}'
    return path + (f'&record_id=eq.{quote(identifier,safe="")}' if identifier else '')


async def load(owner: str, kind: str, identifier: str) -> dict | None:
    rows = await remote('GET', record_path(owner, kind, identifier))
    return rows[0]['payload'] if rows else None


async def save(owner: str, kind: str, identifier: str, payload: dict):
    await remote('POST', '/rest/v1/workspace_records?on_conflict=owner_id,kind,record_id',
        headers={'Prefer': 'resolution=merge-duplicates'}, json={
            'owner_id': owner, 'kind': kind, 'record_id': identifier, 'payload': payload,
            'updated_at': datetime.now(timezone.utc).isoformat()})


async def reserve(user: dict, identifier: str):
    accepted = await remote('POST', '/rest/v1/rpc/reserve_research', json={
        'p_owner': user['id'], 'p_research': identifier, 'p_guest': bool(user.get('is_anonymous'))})
    if not accepted:
        raise HTTPException(403, "Your five guest research runs are used. Sign in with Google to continue.")


async def refund(owner: str, identifier: str):
    await remote('PATCH', f'/rest/v1/research_allowances?owner_id=eq.{quote(owner)}&research_id=eq.{quote(identifier)}', json={'refunded': True})


async def usage(user: dict) -> dict:
    guest = bool(user.get('is_anonymous'))
    rows = await remote('GET', f'/rest/v1/research_allowances?owner_id=eq.{quote(user["id"])}&refunded=eq.false&select=research_id') if guest else []
    return {'guest': guest, 'remaining': max(0, 5-len(rows)) if guest else None, 'limit': 5 if guest else None}


def validate_record(kind: str, identifier: str, payload: dict | None = None):
    if kind not in {'research', 'chat', 'pdf', 'collection', 'feedback'} or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', identifier):
        raise HTTPException(400, 'Invalid workspace record.')
    if payload is not None and len(json.dumps(payload, ensure_ascii=False).encode()) > 48 * 1024 * 1024:
        raise HTTPException(413, 'This workspace record is too large.')
    if payload is not None and kind == 'chat':
        messages = payload.get('messages')
        if payload.get('id') != identifier or not isinstance(messages, list) or len(messages) > 2000 or not isinstance(payload.get('title'), str):
            raise HTTPException(400, 'Invalid conversation.')
        if any(not isinstance(item, dict) or item.get('role') not in {'user','assistant'}
            or not isinstance(item.get('content'), str) or len(item['content']) > 50000 for item in messages):
            raise HTTPException(400, 'Invalid conversation messages.')
    if payload is not None and kind == 'pdf':
        from app.pdf_documents import MAX_PAGES, MAX_TEXT
        pages = payload.get('pages')
        count = payload.get('page_count')
        if not isinstance(count, int) or not 1 <= count <= MAX_PAGES or not isinstance(pages, list) or len(pages) > MAX_PAGES:
            raise HTTPException(400, 'Invalid extracted document.')
        if any(not isinstance(page, dict) or not isinstance(page.get('page'), int)
            or not 1 <= page['page'] <= count or not isinstance(page.get('text'), str) for page in pages):
            raise HTTPException(400, 'Invalid document pages.')
        if sum(len(page['text']) for page in pages) > MAX_TEXT:
            raise HTTPException(413, 'The extracted document is too large.')
