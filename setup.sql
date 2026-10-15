-- English Actors Register: visitor counter and actor votes.
-- Paste all of this into Supabase → SQL Editor → New query, and press Run. Safe to run again.
--
-- Visitors' browsers keep a random ID (no names, emails or IP addresses are stored).
-- The tables are locked: the website can only call the three functions at the bottom,
-- which count a visit, record one vote per browser per actor, and return the totals.

create table if not exists public.ear_visitors (
  visitor    uuid primary key,
  first_seen timestamptz not null default now(),
  last_seen  timestamptz not null default now(),
  views      integer     not null default 1
);

create table if not exists public.ear_votes (
  actor      text        not null check (char_length(actor) between 1 and 200),
  visitor    uuid        not null,
  choice     smallint    not null check (choice in (-1, 0, 1)),   -- 1 like, -1 dislike, 0 neutral
  updated_at timestamptz not null default now(),
  primary key (actor, visitor)
);

-- No direct access to the tables from the website
alter table public.ear_visitors enable row level security;
alter table public.ear_votes    enable row level security;
revoke all on public.ear_visitors, public.ear_votes from anon, authenticated;

-- Count a page view; returns {"visitors": distinct browsers, "views": total page views}
create or replace function public.ear_record_visit(p_visitor uuid)
returns json
language plpgsql security definer set search_path = public
as $$
begin
  if p_visitor is null then raise exception 'missing visitor'; end if;
  insert into ear_visitors (visitor) values (p_visitor)
  on conflict (visitor) do update set views = ear_visitors.views + 1, last_seen = now();
  return (select json_build_object('visitors', count(*), 'views', coalesce(sum(views), 0)) from ear_visitors);
end;
$$;

-- Set this browser's vote on one actor: 'like', 'dislike', 'neutral', or 'none' to remove it.
-- Returns that actor's totals {"like": n, "dislike": n, "neutral": n}.
create or replace function public.ear_vote(p_actor text, p_visitor uuid, p_choice text)
returns json
language plpgsql security definer set search_path = public
as $$
declare v smallint;
begin
  if p_visitor is null then raise exception 'missing visitor'; end if;
  if p_actor is null or char_length(p_actor) not between 1 and 200 then raise exception 'bad actor'; end if;
  if p_choice = 'none' then
    delete from ear_votes where actor = p_actor and visitor = p_visitor;
  else
    v := case p_choice when 'like' then 1 when 'dislike' then -1 when 'neutral' then 0 end;
    if v is null then raise exception 'bad choice'; end if;
    insert into ear_votes (actor, visitor, choice) values (p_actor, p_visitor, v)
    on conflict (actor, visitor) do update set choice = excluded.choice, updated_at = now();
  end if;
  return (select json_build_object(
            'like',    count(*) filter (where choice = 1),
            'dislike', count(*) filter (where choice = -1),
            'neutral', count(*) filter (where choice = 0))
          from ear_votes where actor = p_actor);
end;
$$;

-- Totals for every actor with at least one vote: {"Actor title": [likes, dislikes, neutrals], ...}
create or replace function public.ear_counts()
returns json
language sql stable security definer set search_path = public
as $$
  select coalesce(json_object_agg(actor, json_build_array(l, d, n)), '{}'::json)
  from (select actor,
               count(*) filter (where choice = 1)  as l,
               count(*) filter (where choice = -1) as d,
               count(*) filter (where choice = 0)  as n
        from ear_votes group by actor) t;
$$;

revoke all on function public.ear_record_visit(uuid), public.ear_vote(text, uuid, text), public.ear_counts() from public;
grant execute on function public.ear_record_visit(uuid), public.ear_vote(text, uuid, text), public.ear_counts() to anon, authenticated;
