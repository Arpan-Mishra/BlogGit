-- Add linkedin and medium to the oauth_connections provider constraint.
alter table oauth_connections drop constraint if exists oauth_connections_provider_check;
alter table oauth_connections add constraint oauth_connections_provider_check
  check (provider in ('github', 'notion', 'linkedin', 'medium'));
