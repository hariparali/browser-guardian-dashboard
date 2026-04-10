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
