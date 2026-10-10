-- Additive feature storage. Apply only after review; no live scheduler is created.
alter table public.workspace_records drop constraint workspace_records_kind_check;
alter table public.workspace_records add constraint workspace_records_kind_check
  check (kind in ('research', 'chat', 'pdf', 'collection', 'feedback'));

create table public.report_shares (
  owner_id uuid not null references auth.users(id) on delete cascade,
  research_id text not null,
  token_hash text not null unique check (length(token_hash) = 64),
  payload jsonb not null,
  expires_at timestamptz not null,
  primary key (owner_id, research_id)
);
alter table public.report_shares enable row level security;
revoke all on public.report_shares from anon, authenticated;
grant all on public.report_shares to service_role;
-- Public links are resolved by the server using a hashed 256-bit capability.
-- Neither anonymous nor authenticated clients can enumerate these rows.

create table public.research_alerts (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  research_id text not null,
  interval_days integer not null check (interval_days in (1,7)),
  enabled boolean not null default true,
  next_run timestamptz not null,
  last_research_id text,
  has_update boolean not null default false,
  status text not null default 'Waiting for the first scheduled check.',
  unique (owner_id, research_id)
);
alter table public.research_alerts enable row level security;
revoke all on public.research_alerts from anon, authenticated;
grant all on public.research_alerts to service_role;
create index research_alerts_due on public.research_alerts(next_run) where enabled;

create function public.create_research_alert(p_owner uuid, p_research text, p_days integer)
returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  if p_days not in (1,7) then return false; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_owner::text, 1));
  if (select count(*) from public.research_alerts where owner_id=p_owner and enabled) >= 3
    or exists(select 1 from public.research_alerts where owner_id=p_owner and research_id=p_research)
    then return false; end if;
  insert into public.research_alerts(owner_id,research_id,interval_days,next_run)
    values(p_owner,p_research,p_days,now()+make_interval(days=>p_days));
  return true;
end $$;

create function public.switch_research_alert(p_owner uuid, p_id uuid, p_enabled boolean)
returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  perform pg_advisory_xact_lock(hashtextextended(p_owner::text, 1));
  if p_enabled and (select count(*) from public.research_alerts where owner_id=p_owner and enabled and id<>p_id) >= 3 then return false; end if;
  update public.research_alerts set enabled=p_enabled,
    next_run=case when p_enabled then now()+make_interval(days=>interval_days) else next_run end
    where owner_id=p_owner and id=p_id;
  return found;
end $$;

create function public.claim_research_alert()
returns setof public.research_alerts language sql security invoker set search_path = '' as $$
  update public.research_alerts set next_run=now()+make_interval(days=>interval_days),
    status='Research update queued. If the backend restarts mid-run, inspect the saved run; the next scheduled check remains durable.', has_update=false
  where id in (select id from public.research_alerts where enabled and next_run<=now()
    order by next_run for update skip locked limit 1)
  returning *;
$$;
revoke all on function public.create_research_alert(uuid,text,integer), public.switch_research_alert(uuid,uuid,boolean), public.claim_research_alert() from public, anon, authenticated;
grant execute on function public.create_research_alert(uuid,text,integer), public.switch_research_alert(uuid,uuid,boolean), public.claim_research_alert() to service_role;
