# Mensa poll bot

Posts today's menus (student prices) for Unimensa, Platte, Clausiusbar,
Polymensa and Polysnack to Mattermost on weekdays at ~11:15 Zurich time,
plus a `/poll` line to paste.

## Status
- ETH (Clausiusbar 3, Polymensa/Polyterrasse 9, Polysnack 10): parser
  written against a real API sample.
- UZH: parser written against the real food2050 weekly pages; paths
  verified for Platte, Obere and Untere Mensa.
- `python test_parsers.py` runs the parser tests (fixtures copied from
  real samples).

## Setup
1. Mattermost: create an incoming webhook for the channel.
2. GitHub repo -> Settings -> Secrets and variables -> Actions -> add
   `MATTERMOST_WEBHOOK_URL` (and optionally `MATTERMOST_CHANNEL`). Never
   commit these; logs in public repos are visible to everyone.
3. Actions -> "Mensa poll" -> Run workflow -> `probe` -> download the
   `probe` artifact.
4. Run `dry_run`, check the output, then `post`.

## Notes
- GitHub disables scheduled workflows in public repos after ~60 days
  without repo activity.
- Cron runs can be delayed; the script only posts when the local hour is
  11.