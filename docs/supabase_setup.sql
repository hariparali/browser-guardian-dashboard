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
