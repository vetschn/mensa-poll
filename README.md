# Mensa poll bot

Posts today's menus (student prices) for Unimensa, Platte, Clausiusbar,
Polymensa and Polysnack to Mattermost on weekdays at ~11:15 Zurich time,
plus a `/poll` line to paste.

## Setup
1. Mattermost: create an incoming webhook for the channel.
2. GitHub repo -> Settings -> Secrets and variables -> Actions -> add
   `MATTERMOST_WEBHOOK_URL` (and optionally `MATTERMOST_CHANNEL`). Never
   commit these; logs in public repos are visible to everyone.
3. Actions -> "Mensa poll" -> Run workflow -> `probe` to find the ETH
   ids and grab sample HTML.
4. Fill in `eth_id` / `uzh_url` in `MENSAS`, then run with `dry_run`,
   then `post`.

## Notes
- GitHub disables scheduled workflows in public repos after ~60 days
  without repo activity.
- Cron runs can be delayed; the script only posts when the local hour is
  11.