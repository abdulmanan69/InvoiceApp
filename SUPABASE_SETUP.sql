-- ============================================================================
-- InvoiceApp - Supabase setup (run once, in your Supabase project -> SQL Editor)
-- ----------------------------------------------------------------------------
-- One project holds many shops. Each shop only ever sees its own data because
-- every table has Row-Level Security keyed on membership. Employees are normal
-- Supabase Auth users; the owner adds them from the app (Settings -> Cloud sync -> Team).
-- The app stores each row as JSON in a `data` column, so this schema never has to
-- change when the app adds fields.
-- SAFE TO RE-RUN ANY TIME: it only creates or updates things, it never deletes your data.
-- If anything cloud-related ever errors, re-running this whole file is the first fix to try.
-- ============================================================================

-- ---- control tables -------------------------------------------------------
create table if not exists public.shops (
    id         uuid primary key default gen_random_uuid(),
    name       text not null,
    created_by uuid,
    created_at timestamptz not null default now()
);

create table if not exists public.members (
    user_id uuid not null,
    shop_id uuid not null references public.shops(id) on delete cascade,
    role    text not null default 'employee',
    email   text not null default '',
    created_at timestamptz not null default now(),
    primary key (user_id, shop_id)
);
alter table public.members add column if not exists email text not null default '';

-- helper: the set of shop ids the current user belongs to.
-- SECURITY DEFINER so it reads members WITHOUT re-triggering members' own RLS policies
-- (querying members from inside a members policy would recurse -> "infinite recursion" 500).
create or replace function public.my_shop_ids()
returns setof uuid language sql stable security definer set search_path = public as $$
    select shop_id from public.members where user_id = auth.uid()
$$;

-- helper: the shop ids where the current user is an owner (same recursion-safe reason)
create or replace function public.my_owner_shop_ids()
returns setof uuid language sql stable security definer set search_path = public as $$
    select shop_id from public.members where user_id = auth.uid() and role = 'owner'
$$;

-- ---- one data table per synced entity -------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'customers','vendors','products','documents','document_items','payments',
    'purchases','purchase_items','returns','return_items','stock_movements'
  ] loop
    execute format($f$
      create table if not exists public.%I (
        id         uuid primary key,
        shop_id    uuid not null references public.shops(id) on delete cascade,
        deleted    boolean not null default false,
        updated_at timestamptz not null default now(),
        data       jsonb not null default '{}'::jsonb
      );
    $f$, t);
    execute format('create index if not exists %I on public.%I (shop_id, updated_at);',
                   'idx_'||t||'_shop_updated', t);
  end loop;
end $$;

-- ---- Row-Level Security ---------------------------------------------------
alter table public.shops   enable row level security;
alter table public.members enable row level security;

drop policy if exists shops_member_read on public.shops;
create policy shops_member_read on public.shops for select
    using (id in (select public.my_shop_ids()));
drop policy if exists shops_insert on public.shops;
create policy shops_insert on public.shops for insert
    with check (created_by = auth.uid());
drop policy if exists shops_owner_write on public.shops;
create policy shops_owner_write on public.shops for update
    using (id in (select public.my_owner_shop_ids()));

-- members policies must NOT select from members directly (that recurses); use the definer helpers.
drop policy if exists members_read on public.members;
create policy members_read on public.members for select
    using (user_id = auth.uid() or shop_id in (select public.my_shop_ids()));
drop policy if exists members_self_insert on public.members;
create policy members_self_insert on public.members for insert
    with check (user_id = auth.uid() or shop_id in (select public.my_owner_shop_ids()));
drop policy if exists members_owner_manage on public.members;
create policy members_owner_manage on public.members for delete
    using (shop_id in (select public.my_owner_shop_ids()));
-- upserts hit the UPDATE path when the membership already exists - without this policy that
-- second "Add employee" click failed with 403 (USING expression)
drop policy if exists members_owner_update on public.members;
create policy members_owner_update on public.members for update
    using (user_id = auth.uid() or shop_id in (select public.my_owner_shop_ids()))
    with check (user_id = auth.uid() or shop_id in (select public.my_owner_shop_ids()));

do $$
declare t text;
begin
  foreach t in array array[
    'customers','vendors','products','documents','document_items','payments',
    'purchases','purchase_items','returns','return_items','stock_movements'
  ] loop
    execute format('alter table public.%I enable row level security;', t);
    execute format('drop policy if exists %I on public.%I;', t||'_rw', t);
    execute format($p$
      create policy %I on public.%I for all
        using (shop_id in (select public.my_shop_ids()))
        with check (shop_id in (select public.my_shop_ids()));
    $p$, t||'_rw', t);
  end loop;
end $$;

-- ---- keep updated_at server-authoritative --------------------------------
-- Stamp updated_at = now() on every insert/update so the app's "pull rows newer than X"
-- ordering is reliable regardless of each PC's clock.
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end $$;

do $$
declare t text;
begin
  foreach t in array array[
    'customers','vendors','products','documents','document_items','payments',
    'purchases','purchase_items','returns','return_items','stock_movements'
  ] loop
    execute format('drop trigger if exists trg_%I_updated on public.%I;', t, t);
    execute format('create trigger trg_%I_updated before insert or update on public.%I '
                   'for each row execute function public.set_updated_at();', t, t);
  end loop;
end $$;

-- ---- create-shop helper (used by the app's "Create shop" button) ----------
-- Runs as a trusted function so it can make the shop AND the owner membership in
-- one step, avoiding the RLS chicken-and-egg on first insert.
create or replace function public.create_shop(p_name text)
returns public.shops language plpgsql security definer set search_path = public as $$
declare s public.shops;
begin
    if auth.uid() is null then
        raise exception 'not signed in';
    end if;
    insert into public.shops(name, created_by) values (p_name, auth.uid()) returning * into s;
    insert into public.members(user_id, shop_id, role, email)
        values (auth.uid(), s.id, 'owner', coalesce(auth.jwt() ->> 'email', ''))
        on conflict (user_id, shop_id) do update set role = 'owner';
    return s;
end $$;
grant execute on function public.create_shop(text) to authenticated;

-- ---- invite codes: employees join with ONE code, no keys, no owner service key ----
-- The code secret lives in shop_codes, which has RLS enabled and NO policies, so the API can
-- never read it directly; only these SECURITY DEFINER functions touch it.
create table if not exists public.shop_codes (
    shop_id uuid primary key references public.shops(id) on delete cascade,
    code    text not null
);
alter table public.shop_codes enable row level security;

-- owner asks for the shop's invite secret (created on first use)
create or replace function public.get_invite(p_shop uuid)
returns text language plpgsql security definer set search_path = public as $$
declare c text;
begin
    if not exists (select 1 from public.members
                   where user_id = auth.uid() and shop_id = p_shop and role = 'owner') then
        raise exception 'only the shop owner can get the invite code';
    end if;
    select code into c from public.shop_codes where shop_id = p_shop;
    if c is null then
        -- built-in randomness only (gen_random_bytes needs the pgcrypto extension, which is not
        -- always on the search path in Supabase projects)
        c := substr(md5(random()::text || clock_timestamp()::text), 1, 18);
        insert into public.shop_codes(shop_id, code) values (p_shop, c)
            on conflict (shop_id) do update set code = excluded.code;
    end if;
    return c;
end $$;
grant execute on function public.get_invite(uuid) to authenticated;

-- a signed-in user presents the code and becomes an employee of that shop
create or replace function public.join_shop(p_shop uuid, p_code text)
returns text language plpgsql security definer set search_path = public as $$
declare r text;
begin
    if auth.uid() is null then
        raise exception 'not signed in';
    end if;
    if not exists (select 1 from public.shop_codes where shop_id = p_shop and code = p_code) then
        raise exception 'invalid invite code - ask the owner to copy it again';
    end if;
    insert into public.members(user_id, shop_id, role, email)
        values (auth.uid(), p_shop, 'employee', coalesce(auth.jwt() ->> 'email', ''))
        on conflict (user_id, shop_id) do update set email = excluded.email
        returning role into r;
    return r;
end $$;
grant execute on function public.join_shop(uuid, text) to authenticated;

-- ---- tell the API layer to pick up the new tables/functions RIGHT NOW ------
-- Without this, PostgREST can keep serving its cached schema for a while and the app
-- would see "404 function does not exist" even though the SQL ran fine.
notify pgrst, 'reload schema';

-- Done. In the app: Settings -> Cloud sync -> press Connect & check,
-- sign in (your shop is created automatically), then Copy invite code for employees.
