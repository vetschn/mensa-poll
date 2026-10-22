#!/usr/bin/env python3
"""Post today's mensa menus (ETH + UZH, around ETH Zentrum) to Mattermost.

The message is sent through an incoming webhook. Webhooks cannot create
Matterpoll polls, so the message ends with a ready-to-paste /poll command.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Zurich")
POST_HOUR = 11  # local hour in which the scheduled run is allowed to post

ETH_OFFER_DAY = (
    "https://ethz.ch/de/campus/erleben/gastronomie-und-einkaufen/gastronomie/"
    "menueplaene/offerDay.html"
)
ETH_INFO = (
    "https://ethz.ch/en/campus/getting-to-know/cafes-restaurants-shops/gastronomy/"
    "restaurants-and-cafeterias/zentrum"
)
UA = {"User-Agent": "mensa-poll-bot (github actions; lunch poll for a small team)"}


@dataclass
class Dish:
    category: str  # e.g. "Garden", "Wok"
    description: str
    price: str | None = None  # STUDENT price, e.g. "7.50"
    tags: tuple[str, ...] = ()  # e.g. ("vegan",)


@dataclass
class Mensa:
    key: str
    name: str
    source: str  # "eth" or "uzh"
    emoji: str  # Mattermost emoji name
    eth_id: int | None = None  # menu-plan id, found with --probe
    info_url: str | None = None  # link shown in the message
    uzh_url: str | None = None  # menu page, found with --probe-url


# TODO ids/urls: run the workflow with mode=probe, then fill them in.
# Hints: Clausiusbar was id=4 (2022) and id=3 (2025 README); Polysnack was 13 (2020).
MENSAS = [
    Mensa("unimensa", "Unimensa", "uzh", "one"),
    Mensa("platte", "Platte", "uzh", "two"),
    Mensa("clausius", "Clausiusbar", "eth", "three", info_url=f"{ETH_INFO}/clausiusbar.html"),
    Mensa("polymensa", "Polymensa", "eth", "four", info_url=f"{ETH_INFO}.html"),
    Mensa("polysnack", "Polysnack", "eth", "five", info_url=f"{ETH_INFO}/polysnack.html"),
]


# --------------------------------------------------------------------------
# Fetching + parsing (parsers are written once we have real HTML samples)
# --------------------------------------------------------------------------
def eth_params(mensa_id: int, day: dt.date) -> dict:
    return {"language": "en", "date": day.isoformat(), "id": mensa_id}


def parse_eth(html: str) -> list[Dish]:
    raise NotImplementedError("ETH parser needs a real HTML sample (see --probe)")


def parse_uzh(html: str) -> list[Dish]:
    raise NotImplementedError("UZH parser needs a real HTML sample (see --probe-url)")


def fetch_menu(m: Mensa, day: dt.date) -> list[Dish]:
    if m.source == "eth":
        if m.eth_id is None:
            raise LookupError("no eth_id configured")
        r = requests.get(ETH_OFFER_DAY, params=eth_params(m.eth_id, day), headers=UA, timeout=20)
        r.raise_for_status()
        return parse_eth(r.text)
    if m.uzh_url is None:
        raise LookupError("no uzh_url configured")
    r = requests.get(m.uzh_url, headers=UA, timeout=20)
    r.raise_for_status()
    return parse_uzh(r.text)


def safe_fetch(m: Mensa, day: dt.date) -> list[Dish] | None:
    """None = unknown (error / not configured), [] = nothing served today."""
    try:
        return fetch_menu(m, day)
    except Exception as e:  # noqa: BLE001 - keep the run alive, log only the type
        print(f"[warn] {m.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# Message building
# --------------------------------------------------------------------------
def cell(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("|", "/")).strip()


def build_message(day: dt.date, results: dict[str, list[Dish] | None]) -> str:
    out = [f"#### :fork_and_knife: Lunch options, {day:%A %d %B %Y}", ""]
    for m in MENSAS:
        title = f"[{m.name}]({m.info_url})" if m.info_url else m.name
        out.append(f"##### :{m.emoji}: {title}")
        dishes = results[m.key]
        if dishes is None:
            out.append("_Menu unavailable._")
        elif not dishes:
            out.append("_No menu published today (closed?)._")
        else:
            out += ["| Menu | Dish | Student price |", "|---|---|---:|"]
            for d in dishes:
                tags = f" _({', '.join(d.tags)})_" if d.tags else ""
                price = f"CHF {d.price}" if d.price else "–"
                out.append(f"| {cell(d.category)} | {cell(d.description)}{tags} | {price} |")
        out.append("")

    options = [m.name for m in MENSAS if results[m.key] is None or results[m.key]]
    poll = '/poll "Where do we eat today?" ' + " ".join(f'"{o}"' for o in options)
    out += ["Paste this to start the poll:", "```", poll, "```"]
    return "\n".join(out)


def post(webhook_url: str, text: str) -> None:
    payload = {"text": text}
    if os.environ.get("MATTERMOST_CHANNEL"):
        payload["channel"] = os.environ["MATTERMOST_CHANNEL"]
    try:
        r = requests.post(webhook_url, json=payload, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        # Never print the exception text: it contains the webhook URL (logs are public).
        status = getattr(getattr(e, "response", None), "status_code", None)
        sys.exit(f"Posting to Mattermost failed ({type(e).__name__}, status={status})")


# --------------------------------------------------------------------------
# Probe: discover ETH ids and dump raw HTML for writing the parsers
# --------------------------------------------------------------------------
def probe(day: dt.date, extra_urls: list[str]) -> None:
    out = Path("probe")
    out.mkdir(exist_ok=True)
    for i in range(1, 41):
        try:
            r = requests.get(ETH_OFFER_DAY, params=eth_params(i, day), headers=UA, timeout=20)
            (out / f"eth_{i}.html").write_text(r.text, encoding="utf-8")
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text)).strip()
            print(f"eth id={i:>2} status={r.status_code} bytes={len(r.text):>6} | {text[:140]}")
        except requests.RequestException as e:
            print(f"eth id={i:>2} {type(e).__name__}")
        time.sleep(0.3)
    urls = extra_urls or [
        "https://www.mensa.uzh.ch/en.html",
        "https://www.mensa.uzh.ch/en/standorte.html",
    ]
    for n, url in enumerate(urls):
        try:
            r = requests.get(url, headers=UA, timeout=20)
            (out / f"uzh_{n}.html").write_text(r.text, encoding="utf-8")
            print(f"uzh[{n}] {url} status={r.status_code} bytes={len(r.text)}")
        except requests.RequestException as e:
            print(f"uzh[{n}] {url} {type(e).__name__}")


# --------------------------------------------------------------------------
def at_lunch_hour(now: dt.datetime) -> bool:
    """Two UTC crons cover summer/winter time; only the one landing in 11:xx local posts."""
    return now.weekday() < 5 and now.hour == POST_HOUR


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-at-lunch-hour", action="store_true", help="skip unless it is 11:xx in Zurich")
    ap.add_argument("--dry-run", action="store_true", help="print instead of posting")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--probe-url", action="append", default=[])
    ap.add_argument("--date", type=dt.date.fromisoformat)
    args = ap.parse_args()

    now = dt.datetime.now(TZ)
    day = args.date or now.date()

    if args.probe:
        probe(day, args.probe_url)
        return 0
    if args.only_at_lunch_hour and not at_lunch_hour(now):
        print(f"Not posting: local time is {now:%a %H:%M}.")
        return 0

    results = {m.key: safe_fetch(m, day) for m in MENSAS}
    if all(v is None for v in results.values()):
        print("No menu could be loaded for any mensa, not posting.", file=sys.stderr)
        return 1

    text = build_message(day, results)
    if args.dry_run:
        print(text)
        return 0
    url = os.environ.get("MATTERMOST_WEBHOOK_URL")
    if not url:
        sys.exit("MATTERMOST_WEBHOOK_URL is not set")
    post(url, text)
    print("Posted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())