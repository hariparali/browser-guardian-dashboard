-- Browser Guardian — Remote Control Tables
-- Run this in Supabase: Dashboard → SQL Editor → New query → paste → Run

-- 1. Device status (desktop app upserts every 5s)
create table if not exists device_status (
  device_id              text primary key,
  device_name            text,
  browser_state          text default 'idle',
  browser_remaining_secs integer default 0,
  roblox_state           text default 'idle',
  roblox_remaining_secs  integer default 0,
  last_updated           timestamptz default now()
);

alter table device_status enable row level security;

drop policy if exists "anon_all_device_status" on device_status;
create policy "anon_all_device_status"
  on device_status for all
  using (true)
  with check (true);

-- 2. Remote commands (dashboard writes, desktop app reads + executes)
create table if not exists remote_commands (
  id         bigserial primary key,
  device_id  text not null,
  command    text not null,        -- 'extend_browser' | 'extend_roblox'
  params     jsonb default '{}',   -- e.g. {"minutes": 30}
  status     text default 'pending', -- 'pending' | 'executed'
  created_at timestamptz default now()
);

alter table remote_commands enable row level security;

drop policy if exists "anon_all_remote_commands" on remote_commands;
create policy "anon_all_remote_commands"
  on remote_commands for all
  using (true)
  with check (true);

-- 3. Blocked attempts (desktop app writes when adult content is blocked)
create table if not exists blocked_attempts (
  id         bigserial primary key,
  device_id  text not null,
  domain     text not null,
  url        text,
  reason     text,
  timestamp  timestamptz default now()
);

alter table blocked_attempts enable row level security;

drop policy if exists "anon_all_blocked_attempts" on blocked_attempts;
create policy "anon_all_blocked_attempts"
  on blocked_attempts for all
  using (true)
  with check (true);

-- 4. Device logs (desktop app mirrors its local log file here every ~10s,
--    so logs can be checked remotely without RDP/physical access to the PC)
create table if not exists device_logs (
  id         bigserial primary key,
  device_id  text not null,
  ts         timestamptz not null default now(),
  level      text not null,
  message    text not null
);

create index if not exists device_logs_device_ts_idx
  on device_logs (device_id, ts desc);

alter table device_logs enable row level security;

drop policy if exists "anon_all_device_logs" on device_logs;
create policy "anon_all_device_logs"
  on device_logs for all
  using (true)
  with check (true);

-- 5. Email alerts on adult-site blocks (trigger -> pg_net -> Resend email API)
--    Supabase cannot send arbitrary email itself, so a Postgres trigger on
--    blocked_attempts calls the Resend API asynchronously via pg_net.
--
--    BEFORE running this section:
--      1. Create a free account at https://resend.com  (sign up WITH the
--         address you want alerts sent to, e.g. hariparali@gmail.com — without
--         a verified domain, Resend only delivers to your own account email,
--         which is exactly what we want here).
--      2. Resend dashboard -> API Keys -> create key -> copy it (re_...).
--      3. Replace re_YOUR_RESEND_API_KEY below with that key.
--      4. Replace the 'to' address below if different from hariparali@gmail.com.

create extension if not exists pg_net;

create or replace function notify_blocked_attempt()
returns trigger
language plpgsql
security definer
as $$
declare
  recent_count int;
begin
  -- Throttle: skip the email if the SAME device+domain was already logged in
  -- the last 10 minutes (stops inbox flooding when a page is retried repeatedly).
  select count(*) into recent_count
  from blocked_attempts
  where device_id = NEW.device_id
    and domain    = NEW.domain
    and id       <> NEW.id
    and timestamp > (NEW.timestamp - interval '10 minutes');

  if recent_count > 0 then
    return NEW;
  end if;

  perform net.http_post(
    url     := 'https://api.resend.com/emails',
    headers := jsonb_build_object(
      'Content-Type',  'application/json',
      'Authorization', 'Bearer re_YOUR_RESEND_API_KEY'
    ),
    body := jsonb_build_object(
      'from',    'BrowserGuardian <onboarding@resend.dev>',
      'to',      'hariparali@gmail.com',
      'subject', 'Adult site blocked on ' || NEW.device_id,
      'html',
        '<h2>Adult content blocked</h2>' ||
        '<p><b>Device:</b> ' || coalesce(NEW.device_id, '') || '</p>' ||
        '<p><b>Domain:</b> ' || coalesce(NEW.domain, '')    || '</p>' ||
        '<p><b>URL:</b> '    || coalesce(NEW.url, '')        || '</p>' ||
        '<p><b>Reason:</b> ' || coalesce(NEW.reason, '')     || '</p>' ||
        '<p><b>Time (UTC):</b> ' || NEW.timestamp || '</p>'
    )
  );
  return NEW;
end;
$$;

drop trigger if exists on_blocked_attempt_insert on blocked_attempts;
create trigger on_blocked_attempt_insert
  after insert on blocked_attempts
  for each row execute function notify_blocked_attempt();


-- ============================================================================
-- 6. App usage tracking + per-app limits  (added 2026-10-03)
-- ============================================================================
-- Lets the dashboard show which programs the child actually runs (with minutes
-- used today) and set a daily limit or an outright block per app, instead of
-- hardcoding each game in the desktop code the way Roblox is today.

-- 6a. Daily per-app usage. One row per (device, app, day); the desktop app
--     re-upserts the running total every ~60s, so a dropped upload self-heals
--     on the next cycle rather than losing minutes.
create table if not exists app_usage (
  device_id    text not null,
  exe_name     text not null,          -- e.g. 'minecraft.windows.exe' (lowercase)
  display_name text,                   -- friendly name for the dashboard
  usage_date   date not null,
  seconds_used integer not null default 0,
  first_seen   timestamptz default now(),
  last_seen    timestamptz default now(),
  primary key (device_id, exe_name, usage_date)
);

create index if not exists app_usage_device_date_idx
  on app_usage (device_id, usage_date desc, seconds_used desc);

alter table app_usage enable row level security;
drop policy if exists "anon_all_app_usage" on app_usage;
create policy "anon_all_app_usage" on app_usage for all using (true) with check (true);


-- 6b. Catalogue of every app ever seen on a device. Drives the "new app"
--     email alert and gives the dashboard a stable list to attach rules to.
create table if not exists known_apps (
  device_id    text not null,
  exe_name     text not null,
  display_name text,
  exe_path     text,
  first_seen   timestamptz default now(),
  last_seen    timestamptz default now(),
  is_store_app boolean default false,   -- Microsoft Store / UWP packaged app
  primary key (device_id, exe_name)
);

alter table known_apps enable row level security;
drop policy if exists "anon_all_known_apps" on known_apps;
create policy "anon_all_known_apps" on known_apps for all using (true) with check (true);


-- 6c. Per-app rules set from the dashboard. The desktop app polls these every
--     ~60s and caches them locally, so limits still apply when the child's
--     internet drops.
--       action = 'allow'  → no restriction (default for anything with no row)
--       action = 'limit'  → allowed daily_limit_mins per day, then warn+close
--       action = 'block'  → closed immediately, no warning
create table if not exists app_rules (
  device_id        text not null,
  exe_name         text not null,
  action           text not null default 'allow',
  daily_limit_mins integer,
  is_game          boolean default false,
  updated_at       timestamptz default now(),
  primary key (device_id, exe_name),
  constraint app_rules_action_chk check (action in ('allow', 'limit', 'block'))
);

alter table app_rules enable row level security;
drop policy if exists "anon_all_app_rules" on app_rules;
create policy "anon_all_app_rules" on app_rules for all using (true) with check (true);


-- 6d. Safety net: never allow a rule on a critical Windows process, even if the
--     dashboard is mis-clicked. Blocking explorer.exe or winlogon.exe would
--     make the PC unusable. The desktop app enforces the same list locally.
create or replace function reject_system_app_rule()
returns trigger
language plpgsql
as $$
begin
  if lower(NEW.exe_name) in (
    'explorer.exe','winlogon.exe','csrss.exe','services.exe','lsass.exe',
    'smss.exe','wininit.exe','svchost.exe','dwm.exe','taskhostw.exe',
    'ctfmon.exe','sihost.exe','fontdrvhost.exe','runtimebroker.exe',
    'searchhost.exe','startmenuexperiencehost.exe','shellexperiencehost.exe',
    'applicationframehost.exe','systemsettings.exe','userinit.exe',
    'browserguardian.exe','wscript.exe','system','registry','memory compression'
  ) then
    raise exception 'Refusing to create a rule for protected system process: %', NEW.exe_name;
  end if;
  return NEW;
end;
$$;

drop trigger if exists app_rules_protect_system on app_rules;
create trigger app_rules_protect_system
  before insert or update on app_rules
  for each row execute function reject_system_app_rule();


-- 6e. Email alert when a brand-new app appears on a device (same Resend
--     pipeline as the adult-site alerts). Replace the API key placeholder with
--     your real Resend key — it is NOT stored in this repo.
create or replace function notify_new_app()
returns trigger
language plpgsql
security definer
as $$
begin
  perform net.http_post(
    url     := 'https://api.resend.com/emails',
    headers := jsonb_build_object(
      'Content-Type',  'application/json',
      'Authorization', 'Bearer re_YOUR_RESEND_API_KEY'
    ),
    body := jsonb_build_object(
      'from',    'BrowserGuardian <onboarding@resend.dev>',
      'to',      'hariparali@gmail.com',
      'subject', 'New app used on ' || NEW.device_id || ': ' || coalesce(NEW.display_name, NEW.exe_name),
      'html',
        '<h2>New application detected</h2>' ||
        '<p><b>Device:</b> ' || coalesce(NEW.device_id, '')    || '</p>' ||
        '<p><b>App:</b> '    || coalesce(NEW.display_name, '') || '</p>' ||
        '<p><b>Program:</b> '|| coalesce(NEW.exe_name, '')     || '</p>' ||
        '<p><b>Path:</b> '   || coalesce(NEW.exe_path, '')     || '</p>' ||
        '<p>Set a daily limit or block it from the dashboard.</p>'
    )
  );
  return NEW;
end;
$$;

drop trigger if exists on_known_app_insert on known_apps;
create trigger on_known_app_insert
  after insert on known_apps
  for each row execute function notify_new_app();
