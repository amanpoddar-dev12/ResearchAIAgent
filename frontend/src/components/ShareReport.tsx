import { useState } from 'react';
import { libraryRequest } from '../services/api';
import { cloudEnabled } from '../services/auth';
export function ShareReport({ researchId }: { researchId: string }) {
  const [link, setLink] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const create = async () => { if (!window.confirm('Create a read-only link? Anyone with the link can read this report, charts and source references for 30 days. Chats, PDFs and private session state are excluded. A new link replaces the previous one.')) return; setBusy(true); try { const result = await libraryRequest<{token:string}>(`library/shares/${researchId}`, { method: 'POST' }); setLink(`${window.location.origin}/share/${result.token}`); setStatus('Link created.'); } catch (error) { setStatus(error instanceof Error ? error.message : 'Sharing failed.'); } finally { setBusy(false); } };
  const revoke = async () => { setBusy(true); try { await libraryRequest(`library/shares/${researchId}`, { method: 'DELETE' }); setLink(''); setStatus('All links for this report have been revoked.'); } catch { setStatus('Revocation failed. The link may still work; retry.'); } finally { setBusy(false); } };
  return <details className="card no-print"><summary className="cursor-pointer text-sm font-medium">Share read-only report</summary><p className="mt-3 text-xs text-muted-foreground">Private by default. Sharing publishes a snapshot that expires after 30 days; later research does not update it.</p><div className="mt-3 flex flex-wrap gap-2"><button className="button-secondary" disabled={!cloudEnabled || busy} onClick={() => void create()}>Create share link</button><button className="button-secondary" disabled={!cloudEnabled || busy} onClick={() => void revoke()}>Revoke links</button></div>{!cloudEnabled && <p className="mt-2 text-xs">Cloud setup is required for sharing.</p>}{link && <label className="mt-3 block text-xs">Read-only URL<input readOnly value={link} className="select mt-1 w-full" onFocus={event => event.target.select()} /></label>}<p className="mt-2 text-xs" role="status">{status}</p></details>;
}
