-- Blog Copilot — initial schema
-- Run this in your Supabase SQL editor or via `supabase db push`.
-- Supabase Auth manages the auth.users table automatically.

-- ── OAuth connections ────────────────────────────────────────────────────────
-- Stores per-user, per-provider OAuth tokens encrypted at rest with Fernet.
create table if not exists oauth_connections (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null references auth.users(id) on delete cascade,
  provider               text not null check (provider in ('github', 'notion')),
  access_token_encrypted bytea not null,
  refresh_token_encrypted bytea,
  expires_at             timestamptz,
  scopes                 text[],
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),
  unique (user_id, provider)
);

alter table oauth_connections enable row level security;

create policy "Users can manage their own OAuth connections"
  on oauth_connections
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ── Sessions ─────────────────────────────────────────────────────────────────
-- One session = one blog-writing conversation.
create table if not exists sessions (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users(id) on delete cascade,
  title      text,
  status     text not null default 'active' check (status in ('active', 'completed', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table sessions enable row level security;

create policy "Users can manage their own sessions"
  on sessions
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ── Messages ──────────────────────────────────────────────────────────────────
-- Full conversation history per session, including tool messages.
create table if not exists messages (
  id         uuid primary key default gen_random_uuid(),
  session_id uuid not null references sessions(id) on delete cascade,
  role       text not null check (role in ('user', 'assistant', 'system', 'tool')),
  content    text not null,
  metadata   jsonb,
  created_at timestamptz not null default now()
);

alter table messages enable row level security;

create policy "Users can manage messages in their own sessions"
  on messages
  for all
  using (
    exists (
      select 1 from sessions s
      where s.id = messages.session_id
        and s.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from sessions s
      where s.id = messages.session_id
        and s.user_id = auth.uid()
    )
  );

-- ── Blog drafts ───────────────────────────────────────────────────────────────
-- One draft per session (upserted as the blog evolves).
create table if not exists blog_drafts (
  id               uuid primary key default gen_random_uuid(),
  session_id       uuid not null unique references sessions(id) on delete cascade,
  repo_url         text,
  repo_summary     jsonb,
  intake_answers   jsonb,
  current_draft    text,
  current_version  int not null default 1,
  notion_page_id   text,
  notion_title     text,
  medium_markdown  text,
  linkedin_post    text,
  outreach_dm      text,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

alter table blog_drafts enable row level security;

create policy "Users can manage drafts in their own sessions"
  on blog_drafts
  for all
  using (
    exists (
      select 1 from sessions s
      where s.id = blog_drafts.session_id
        and s.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from sessions s
      where s.id = blog_drafts.session_id
        and s.user_id = auth.uid()
    )
  );

-- ── Draft revisions ───────────────────────────────────────────────────────────
-- Audit trail of every revision with the user feedback that triggered it.
create table if not exists draft_revisions (
  id            uuid primary key default gen_random_uuid(),
  draft_id      uuid not null references blog_drafts(id) on delete cascade,
  version       int not null,
  prev_content  text,
  new_content   text,
  user_feedback text,
  revision_mode text check (revision_mode in ('section', 'overall', 'full')),
  created_at    timestamptz not null default now(),
  unique (draft_id, version)
);

alter table draft_revisions enable row level security;

create policy "Users can read revisions for their drafts"
  on draft_revisions
  for all
  using (
    exists (
      select 1 from blog_drafts bd
        join sessions s on s.id = bd.session_id
      where bd.id = draft_revisions.draft_id
        and s.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from blog_drafts bd
        join sessions s on s.id = bd.session_id
      where bd.id = draft_revisions.draft_id
        and s.user_id = auth.uid()
    )
  );

-- ── updated_at triggers ───────────────────────────────────────────────────────
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger trg_oauth_connections_updated_at
  before update on oauth_connections
  for each row execute function set_updated_at();

create trigger trg_sessions_updated_at
  before update on sessions
  for each row execute function set_updated_at();

create trigger trg_blog_drafts_updated_at
  before update on blog_drafts
  for each row execute function set_updated_at();
