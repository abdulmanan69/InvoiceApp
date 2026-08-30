-- ============================================================================
-- InvoiceApp - Supabase setup (run once, in your Supabase project -> SQL Editor)
-- ----------------------------------------------------------------------------
-- One project holds many shops. Each shop only ever sees its own data because
-- every table has Row-Level Security keyed on membership. Employees are normal
-- Supabase Auth users; the owner adds them from the app (Settings -> Cloud sync -> Team).
-- The app stores each row as JSON in a `data` column, so this schema never has to
-- change when the app adds fields.
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
    created_at timestamptz not null default now(),
    primary key (user_id, shop_id)
);

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
    insert into public.members(user_id, shop_id, role) values (auth.uid(), s.id, 'owner')
        on conflict (user_id, shop_id) do update set role = 'owner';
    return s;
end $$;
grant execute on function public.create_shop(text) to authenticated;

-- Done. In the app: Settings -> Cloud sync -> paste Project URL + anon key,
-- sign in, create your shop, then add employees under Team.
