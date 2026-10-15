-- English Actors Register: visitor submissions (suggested actors and photos) and the admin dashboard.
-- Run this once in Supabase → SQL Editor → New query → Run, after setup.sql. Safe to run again.
--
-- Visitors can only submit (through ear_submit) and upload new files into a private "pending" folder.
-- Only accounts listed in ear_admins can read, edit, approve or delete submissions.
-- Approved photos are copied by the dashboard into a public bucket, and the site reads the
-- approved list through ear_approved().

-- Who counts as an admin: their sign-in email. Add yourself with the separate one-line command in the README.
create table if not exists public.ear_admins (email text primary key);
alter table public.ear_admins enable row level security;
revoke all on public.ear_admins from anon, authenticated;

create or replace function public.ear_is_admin()
returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (select 1 from ear_admins where lower(email) = lower(coalesce(auth.jwt() ->> 'email', '')));
$$;
revoke all on function public.ear_is_admin() from public;
grant execute on function public.ear_is_admin() to anon, authenticated;

create table if not exists public.ear_submissions (
  id                  uuid primary key default gen_random_uuid(),
  kind                text not null check (kind in ('actor', 'photo')),
  status              text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_at          timestamptz not null default now(),
  reviewed_at         timestamptz,
  submitter_email     text not null check (char_length(submitter_email) <= 254 and submitter_email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  actor_first         text check (char_length(actor_first) <= 100),
  actor_last          text check (char_length(actor_last) <= 100),
  film                text check (char_length(film) <= 200),
  actor_title         text check (char_length(actor_title) <= 200),   -- photo submissions: which actor on the page
  note                text check (char_length(note) <= 1000),
  photo_path          text,                                           -- in private bucket ear-submissions
  approved_photo_path text,                                           -- in public bucket ear-approved
  rights_confirmed    boolean not null default false
);
create index if not exists ear_submissions_status on public.ear_submissions (status, created_at desc);
create index if not exists ear_submissions_email on public.ear_submissions (lower(submitter_email), created_at desc);

alter table public.ear_submissions enable row level security;
revoke all on public.ear_submissions from anon, authenticated;
grant select, update, delete on public.ear_submissions to authenticated;
drop policy if exists "ear admins read"   on public.ear_submissions;
drop policy if exists "ear admins update" on public.ear_submissions;
drop policy if exists "ear admins delete" on public.ear_submissions;
create policy "ear admins read"   on public.ear_submissions for select to authenticated using (public.ear_is_admin());
create policy "ear admins update" on public.ear_submissions for update to authenticated using (public.ear_is_admin()) with check (public.ear_is_admin());
create policy "ear admins delete" on public.ear_submissions for delete to authenticated using (public.ear_is_admin());

-- The only way visitors can add a submission. Checks every field and limits how much one email can send.
create or replace function public.ear_submit(
  p_kind text, p_email text, p_first text default null, p_last text default null, p_film text default null,
  p_actor_title text default null, p_note text default null, p_photo_path text default null,
  p_rights boolean default false, p_website text default null)
returns json
language plpgsql security definer set search_path = public
as $$
declare
  v_email text := lower(btrim(coalesce(p_email, '')));
  v_id uuid;
begin
  if coalesce(btrim(p_website), '') <> '' then              -- hidden field only bots fill in
    return json_build_object('ok', true);
  end if;
  if v_email !~* '^[^@\s]+@[^@\s]+\.[^@\s]+$' or char_length(v_email) > 254 then
    raise exception 'Please enter a valid email address.';
  end if;
  if p_kind = 'actor' then
    if coalesce(btrim(p_first), '') = '' or coalesce(btrim(p_last), '') = '' or coalesce(btrim(p_film), '') = '' then
      raise exception 'First name, last name and a film are all required.';
    end if;
  elsif p_kind = 'photo' then
    if coalesce(btrim(p_actor_title), '') = '' or p_photo_path is null then
      raise exception 'Please choose a photo.';
    end if;
  else
    raise exception 'Unknown submission type.';
  end if;
  if p_photo_path is not null then
    if p_photo_path !~ '^pending/[0-9a-f-]{36}\.(jpg|png|webp)$' then raise exception 'Photo upload not recognised.'; end if;
    if not coalesce(p_rights, false) then raise exception 'Please confirm you may share this photo.'; end if;
  end if;
  if (select count(*) from ear_submissions where lower(submitter_email) = v_email and created_at > now() - interval '1 day') >= 20 then
    raise exception 'Thanks! You have sent a lot today. Please try again tomorrow.';
  end if;
  if (select count(*) from ear_submissions where status = 'pending') >= 2000 then
    raise exception 'We have a backlog of suggestions to review. Please try again later.';
  end if;
  insert into ear_submissions (kind, submitter_email, actor_first, actor_last, film, actor_title, note, photo_path, rights_confirmed)
  values (p_kind, v_email, nullif(btrim(p_first), ''), nullif(btrim(p_last), ''), nullif(btrim(p_film), ''),
          nullif(btrim(p_actor_title), ''), nullif(btrim(p_note), ''), p_photo_path, coalesce(p_rights, false))
  returning id into v_id;
  return json_build_object('ok', true, 'id', v_id);
end;
$$;

-- What the public site shows: approved photos (by actor) and approved new actors. No submitter details.
create or replace function public.ear_approved()
returns json
language sql stable security definer set search_path = public
as $$
  select json_build_object(
    'photos', coalesce((select json_object_agg(actor_title, approved_photo_path)
                        from (select distinct on (actor_title) actor_title, approved_photo_path
                              from ear_submissions
                              where kind = 'photo' and status = 'approved' and approved_photo_path is not null
                              order by actor_title, reviewed_at desc) p), '{}'::json),
    'actors', coalesce((select json_agg(json_build_object('id', id, 'first', actor_first, 'last', actor_last,
                                                         'film', film, 'photo', approved_photo_path) order by actor_last, actor_first)
                        from ear_submissions where kind = 'actor' and status = 'approved'), '[]'::json));
$$;

revoke all on function public.ear_submit(text, text, text, text, text, text, text, text, boolean, text), public.ear_approved() from public;
grant execute on function public.ear_submit(text, text, text, text, text, text, text, text, boolean, text), public.ear_approved() to anon, authenticated;

-- Photo storage: a private bucket for uploads waiting for review, a public one for approved photos.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('ear-submissions', 'ear-submissions', false, 5242880, array['image/jpeg', 'image/png', 'image/webp']),
       ('ear-approved',    'ear-approved',    true,  5242880, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update set public = excluded.public, file_size_limit = excluded.file_size_limit,
                               allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "ear visitors upload pending" on storage.objects;
drop policy if exists "ear admins read uploads"      on storage.objects;
drop policy if exists "ear admins delete uploads"    on storage.objects;
drop policy if exists "ear admins add approved"      on storage.objects;
drop policy if exists "ear admins change approved"   on storage.objects;
drop policy if exists "ear admins remove approved"   on storage.objects;
-- visitors may only add new files under pending/ (they can't list, read, replace or delete anything)
create policy "ear visitors upload pending" on storage.objects for insert to anon, authenticated
  with check (bucket_id = 'ear-submissions' and (storage.foldername(name))[1] = 'pending');
create policy "ear admins read uploads"    on storage.objects for select to authenticated
  using (bucket_id in ('ear-submissions', 'ear-approved') and public.ear_is_admin());
create policy "ear admins delete uploads"  on storage.objects for delete to authenticated
  using (bucket_id = 'ear-submissions' and public.ear_is_admin());
create policy "ear admins add approved"    on storage.objects for insert to authenticated
  with check (bucket_id = 'ear-approved' and public.ear_is_admin());
create policy "ear admins change approved" on storage.objects for update to authenticated
  using (bucket_id = 'ear-approved' and public.ear_is_admin());
create policy "ear admins remove approved" on storage.objects for delete to authenticated
  using (bucket_id = 'ear-approved' and public.ear_is_admin());
