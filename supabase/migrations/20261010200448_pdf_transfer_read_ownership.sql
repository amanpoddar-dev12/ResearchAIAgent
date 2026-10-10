-- PDF access follows the current workspace owner, including after guest transfer.
-- transferred_pdf_read already grants reads through an owned PDF record.
-- Remove the obsolete folder policy: the original guest retains that folder prefix.
drop policy if exists own_pdf_read on storage.objects;
