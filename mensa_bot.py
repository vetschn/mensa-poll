#!/usr/bin/env python3
"""Post today's mensa menus (ETH + UZH, around ETH Zentrum) to Mattermost.

The message is sent through an incoming webhook. Webhooks cannot create
Matterpoll polls, so the message ends with a ready-to-paste /poll command.

Sources
- ETH: the "cookpit" API that powers the ethz.ch menu pages (JSON, facility ids).
- UZH: the food2050 app that zfv.ch embeds for the UZH mensas (server-rendered HTML).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Europe/Zurich")
POST_HOUR = 11  # local hour in which the scheduled run is allowed to post

ETH_API = "https://idapps.ethz.ch/cookpit-pub-services/v1"
ETH_OFFER_DAY = (
    "https://ethz.ch/de/campus/erleben/gastronomie-und-einkaufen/gastronomie/"
    "menueplaene/offerDay.html"
)
FOOD2050 = "https://app.food2050.ch/de/zfv"
ZFV_BASE = "https://www.zfv.ch/de/essen-gehen"
UA = {"User-Agent": "mensa-poll-bot (github actions; lunch poll for a small team)"}
SOLD_OUT = {"sold out", "ausverkauft", "esaurito"}


@dataclass
class Dish:
    category: str  # serving line, e.g. "Pasta", "Yin"
    name: str
    description: str = ""
    price: str | None = None  # STUDENT price, e.g. "7.50"
    tags: tuple[str, ...] = ()  # "vegan" / "vegetarian"


@dataclass
class Mensa:
    key: str
    name: str
    source: str  # "eth" or "uzh"
    emoji: str  # Mattermost emoji name
    eth_id: int | None = None  # ETH facility id (same as id= on the ethz.ch menu page)
    food2050: str | None = None  # food2050 path: <org>/<facility>/<meal-service>
    info_url: str | None = None  # fallback link


# ETH ids verified against the facility list: 3 Clausiusbar, 9 Mensa Polyterrasse, 10 Polysnack.
# UZH: only Platte's food2050 path is verified. The Obere/Untere paths are GUESSES following the
# same pattern; run mode=probe (it prints the real food2050 urls found on the zfv.ch pages).
MENSAS = [
    Mensa("obere", "Obere Mensa", "uzh", "one",
          food2050="universitat-zurich,obere-mensa-uzh/obere-mensa-uzh/mittagsverpflegung",
          info_url=f"{ZFV_BASE}/obere-mensa-uzh#menu"),
    Mensa("untere", "Untere Mensa", "uzh", "two",
          food2050="universitat-zurich,untere-mensa-uzh/untere-mensa-uzh/mittagsverpflegung",
          info_url=f"{ZFV_BASE}/untere-mensa-uzh#menu"),
    Mensa("platte", "Platte", "uzh", "three",
          food2050="universitat-zurich,platte-14/platte-14/mittagsverpflegung",
          info_url=f"{ZFV_BASE}/platte-14#menu"),
    Mensa("clausius", "Clausiusbar", "eth", "four", eth_id=3),
    Mensa("polymensa", "Polymensa", "eth", "five", eth_id=9),
    Mensa("polysnack", "Polysnack", "eth", "six", eth_id=10),
]


def menu_link(m: Mensa, day: dt.date) -> str | None:
    if m.source == "eth" and m.eth_id is not None:
        return f"{ETH_OFFER_DAY}?date={day.isoformat()}&id={m.eth_id}"
    return m.info_url


# --------------------------------------------------------------------------
# ETH
# --------------------------------------------------------------------------
def week_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=7)


def eth_rota_params(facility: int, day: dt.date, lang: str = "en") -> dict:
    after, before = week_bounds(day)
    return {
        "client-id": "ethz-wcms", "lang": lang, "rs-first": 0, "rs-size": 50,
        "valid-after": after.isoformat(), "valid-before": before.isoformat(), "facility": facility,
    }


def _is_lunch(meal_time: dict) -> bool:
    name = (meal_time.get("name") or "").lower()
    if any(w in name for w in ("dinner", "abend", "cena")):
        return False
    start = meal_time.get("time-from")
    return not (start and start >= "15:00")


def _student_price(meal: dict) -> str | None:
    for p in meal.get("meal-price-array") or []:
        if "student" in (p.get("customer-group-desc") or "").lower() and p.get("price") is not None:
            return f"{float(p['price']):.2f}"
    return None


def _eth_tags(meal: dict) -> tuple[str, ...]:
    classes = [(c.get("desc") or "").lower() for c in meal.get("meal-class-array") or []]
    if any("vegan" in c for c in classes):
        return ("vegan",)
    if any("vegetarian" in c for c in classes):
        return ("vegetarian",)
    return ()


def parse_eth(data: dict, day: dt.date) -> list[Dish]:
    """[] = nothing served that day (closed / no menu published)."""
    if not isinstance(data, dict) or "weekly-rota-array" not in data:
        raise ValueError("unexpected ETH response shape")
    dishes: list[Dish] = []
    seen: set[object] = set()
    for rota in data["weekly-rota-array"]:
        vf, vt = rota.get("valid-from"), rota.get("valid-to")
        if vf and vt and not (vf <= day.isoformat() <= vt):
            continue
        for d in rota.get("day-of-week-array") or []:
            if d.get("day-of-week-code") != day.isoweekday():
                continue
            for hours in d.get("opening-hour-array") or []:
                for mt in hours.get("meal-time-array") or []:
                    if not _is_lunch(mt):
                        continue
                    for line in mt.get("line-array") or []:
                        meal = line.get("meal")
                        for ml in meal if isinstance(meal, list) else [meal] if meal else []:
                            name = (ml.get("name") or "").strip()
                            if not name or name.lower() in SOLD_OUT or ml.get("line-id") in seen:
                                continue
                            seen.add(ml.get("line-id"))
                            dishes.append(Dish(
                                (line.get("name") or "").strip(), name,
                                (ml.get("description") or "").strip(), _student_price(ml), _eth_tags(ml),
                            ))
    return dishes


# --------------------------------------------------------------------------
# UZH (food2050)
# --------------------------------------------------------------------------
def parse_zfv_week(html: str, day: dt.date) -> list[dict]:
    """Dishes of one day from the food2050 weekly page. Class names are hashed, so match prefixes."""
    soup = BeautifulSoup(html, "html.parser")
    date_href = re.compile(r"/\d{4}-\d{2}-\d{2}/?$")
    cells = [a for a in soup.find_all("a", href=date_href) if a.find(class_=re.compile("DishName__Name"))]
    if not cells:
        raise ValueError("no dish cells found: page layout changed or not server-rendered")
    out, seen = [], set()
    for a in cells:
        href = a["href"]
        if not href.rstrip("/").endswith(day.isoformat()) or href in seen:
            continue
        seen.add(href)
        line = a.find_previous("p", class_=re.compile("ItemDisplayName"))
        name = a.find(class_=re.compile("DishName__Name")).get_text(" ", strip=True)
        desc = a.find(class_=re.compile("DishName__Description"))
        out.append({
            "line": line.get_text(strip=True) if line else "",
            "name": name.title() if name.isupper() else name,
            "description": desc.get_text(" ", strip=True) if desc else "",
            "href": href,
        })
    return out


def parse_zfv_dish(html: str, name: str) -> tuple[str | None, tuple[str, ...]]:
    """Student price + diet tag from a food2050 dish page."""
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    m = re.search(r"(\d+(?:\.\d+)?)\s*CHF\s*Studierende", text)
    price = f"{float(m.group(1)):.2f}" if m else None
    idx = text.lower().find(name.lower())
    before = text[:idx].lower() if idx > 0 else text[:200].lower()
    tags = ("vegan",) if "vegan" in before else ("vegetarian",) if "vegetarisch" in before else ()
    return price, tags


def fetch_zfv(m: Mensa, day: dt.date) -> list[Dish]:
    if not m.food2050:
        raise LookupError("no food2050 path configured")
    iso = day.isocalendar()
    r = requests.get(f"{FOOD2050}/{m.food2050}/menu/weekly", headers=UA, timeout=20,
                     params={"week": iso.week, "year": iso.year, "day": iso.weekday})
    r.raise_for_status()
    dishes = []
    for e in parse_zfv_week(r.text, day):
        price, tags = None, ()
        try:  # prices live on the dish page; a failure only costs the price
            d = requests.get(e["href"], headers=UA, timeout=20)
            d.raise_for_status()
            price, tags = parse_zfv_dish(d.text, e["name"])
        except requests.RequestException as ex:
            print(f"[warn] {m.name}: price lookup failed ({type(ex).__name__})", file=sys.stderr)
        dishes.append(Dish(e["line"], e["name"], e["description"], price, tags))
    return dishes


# --------------------------------------------------------------------------
def fetch_menu(m: Mensa, day: dt.date) -> list[Dish]:
    if m.source == "eth":
        r = requests.get(f"{ETH_API}/weeklyrotas", params=eth_rota_params(m.eth_id, day),
                         headers=UA, timeout=20)
        r.raise_for_status()
        return parse_eth(r.json(), day)
    return fetch_zfv(m, day)


def safe_fetch(m: Mensa, day: dt.date) -> list[Dish] | None:
    """None = unknown (error), [] = nothing served today."""
    try:
        return fetch_menu(m, day)
    except Exception as e:  # noqa: BLE001 - keep the run alive
        print(f"[warn] {m.name}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# Message building
# --------------------------------------------------------------------------
def cell(text: str) -> str:
    text = text.replace(" | ", ", ").replace("|", "/")
    return re.sub(r"\s+", " ", text).strip()


def build_message(day: dt.date, results: dict[str, list[Dish] | None]) -> str:
    out = [f"#### :fork_and_knife: Lunch options, {day:%A %d %B %Y}", ""]
    for m in MENSAS:
        link = menu_link(m, day)
        out.append(f"##### :{m.emoji}: " + (f"[{m.name}]({link})" if link else m.name))
        dishes = results[m.key]
        if dishes is None:
            out.append("_Menu unavailable._")
        elif not dishes:
            out.append("_No menu published today (closed?)._")
        else:
            out += ["| Menu | Dish | Student price |", "|---|---|---:|"]
            for d in dishes:
                tags = f" _({', '.join(d.tags)})_" if d.tags else ""
                desc = f": {cell(d.description)}" if d.description else ""
                price = f"CHF {d.price}" if d.price else "–"
                out.append(f"| {cell(d.category)} | **{cell(d.name)}**{desc}{tags} | {price} |")
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
# Probe: find the real food2050 paths of the UZH mensas
# --------------------------------------------------------------------------
def probe(day: dt.date) -> None:
    out = Path("probe")
    out.mkdir(exist_ok=True)
    for m in MENSAS:
        if m.source != "uzh":
            continue
        slug = (m.info_url or "").split("/")[-1].split("#")[0]
        try:
            r = requests.get(f"{ZFV_BASE}/{slug}", headers=UA, timeout=20)
            (out / f"zfv_{slug}.html").write_text(r.text, encoding="utf-8")
            urls = sorted(set(re.findall(r"https?://app\.food2050\.ch/[^\"'\s<>\\]+", r.text)))
            print(f"zfv {slug}: status={r.status_code} bytes={len(r.text)} food2050 urls: {urls[:5]}")
        except requests.RequestException as e:
            print(f"zfv {slug}: {type(e).__name__}")
        if m.food2050:
            iso = day.isocalendar()
            try:
                r = requests.get(f"{FOOD2050}/{m.food2050}/menu/weekly", headers=UA, timeout=20,
                                 params={"week": iso.week, "year": iso.year, "day": iso.weekday})
                (out / f"food2050_{m.key}.html").write_text(r.text, encoding="utf-8")
                print(f"food2050 {m.key}: status={r.status_code} bytes={len(r.text)}")
            except requests.RequestException as e:
                print(f"food2050 {m.key}: {type(e).__name__}")


# --------------------------------------------------------------------------
def at_lunch_hour(now: dt.datetime) -> bool:
    """Two UTC crons cover summer/winter time; only the one landing in 11:xx local posts."""
    return now.weekday() < 5 and now.hour == POST_HOUR


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-at-lunch-hour", action="store_true", help="skip unless it is 11:xx in Zurich")
    ap.add_argument("--dry-run", action="store_true", help="print instead of posting")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--date", type=dt.date.fromisoformat)
    args = ap.parse_args()

    now = dt.datetime.now(TZ)
    day = args.date or now.date()

    if args.probe:
        probe(day)
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