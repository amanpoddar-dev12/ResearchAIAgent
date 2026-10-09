-- Run once in the Supabase SQL editor. No automatic expiry of user data.
create table public.workspace_records (
  owner_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('research', 'chat', 'pdf')),
  record_id text not null check (length(record_id) between 1 and 150),
  payload jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (owner_id, kind, record_id)
);
alter table public.workspace_records enable row level security;
create policy own_records on public.workspace_records for select to authenticated
using (owner_id = (select auth.uid()));
-- Mutations go through the backend, which validates ownership and payload size.
create table public.research_allowances (
  owner_id uuid not null references auth.users(id) on delete cascade,
  research_id text not null,
  refunded boolean not null default false,
  created_at timestamptz not null default now(),
  primary key (owner_id, research_id)
);
alter table public.research_allowances enable row level security;
create policy own_allowances on public.research_allowances for select to authenticated
using (owner_id = (select auth.uid()));
create function public.reserve_research(p_owner uuid, p_research text, p_guest boolean)
returns boolean language plpgsql security definer set search_path = '' as $$
declare used integer;
begin
  if not p_guest then return true; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_owner::text, 0));
  if exists (select 1 from public.research_allowances where owner_id=p_owner and research_id=p_research) then
    return true;
  end if;
  select count(*) into used from public.research_allowances where owner_id=p_owner and not refunded;
  if p_guest and used >= 5 then return false; end if;
  insert into public.research_allowances(owner_id,research_id) values(p_owner,p_research);
  return true;
end $$;
revoke all on function public.reserve_research(uuid,text,boolean) from public, anon, authenticated;
grant execute on function public.reserve_research(uuid,text,boolean) to service_role;
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('research-pdfs','research-pdfs',false,26214400,array['application/pdf'])
on conflict(id) do nothing;
create policy own_pdf_read on storage.objects for select to authenticated
using(bucket_id='research-pdfs' and (storage.foldername(name))[1]=(select auth.uid())::text);

-- One-use transfer capability lets a guest import into an existing Google account.
create table public.guest_transfers (
  token_hash text primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  expires_at timestamptz not null
);
alter table public.guest_transfers enable row level security;
create function public.claim_guest_workspace(p_token text, p_target uuid)
returns boolean language plpgsql security definer set search_path='' as $$
declare previous uuid;
begin
  delete from public.guest_transfers where token_hash=p_token and expires_at>now() returning owner_id into previous;
  if previous is null then return false; end if;
  if not exists(select 1 from auth.users where id=previous and is_anonymous=true) then return false; end if;
  if not exists(select 1 from auth.users where id=p_target and is_anonymous=false) then return false; end if;
  insert into public.workspace_records(owner_id,kind,record_id,payload,updated_at)
    select p_target,kind,record_id,payload,updated_at from public.workspace_records where owner_id=previous
    on conflict(owner_id,kind,record_id) do nothing;
  delete from public.workspace_records where owner_id=previous;
  return true;
end $$;
revoke all on function public.claim_guest_workspace(text,uuid) from public,anon,authenticated;
grant execute on function public.claim_guest_workspace(text,uuid) to service_role;
-- Transferred documents keep their object path, but access follows record ownership.
create policy transferred_pdf_read on storage.objects for select to authenticated
using(bucket_id='research-pdfs' and exists(select 1 from public.workspace_records r
  where r.owner_id=(select auth.uid()) and r.kind='pdf' and r.payload->>'storage_path'=name));

grant select on public.workspace_records, public.research_allowances to authenticated;
grant all on public.workspace_records, public.research_allowances, public.guest_transfers to service_role;
