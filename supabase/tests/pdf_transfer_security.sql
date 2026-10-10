-- Read-only catalog regression: this fails before the ownership migration.
do $$
begin
  if exists (select 1 from pg_policies where schemaname='storage'
      and tablename='objects' and policyname='own_pdf_read') then
    raise exception 'Original guest folder access remains after transfer';
  end if;
  if not exists (select 1 from pg_policies where schemaname='storage'
      and tablename='objects' and policyname='transferred_pdf_read'
      and cmd='SELECT' and qual like '%owner_id%' and qual like '%auth.uid()%') then
    raise exception 'Current workspace ownership read policy is missing';
  end if;
end $$;
