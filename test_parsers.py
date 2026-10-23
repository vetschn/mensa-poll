"""Run: python test_parsers.py  (fixtures are trimmed copies of real API/HTML samples)"""
import datetime as dt
import mensa_bot as b


def meal(lid, name, desc, prices, classes=(), **extra):
    return {"line-id": lid, "name": name, "description": desc,
            "meal-price-array": [{"price": p, "customer-group-desc": g} for g, p in prices],
            "meal-class-array": [{"desc": c} for c in classes], **extra}


def day(code, lines, name="Pranzo (Lunch)", start="11:30"):
    return {"day-of-week-code": code, "opening-hour-array": [{"meal-time-array": [
        {"name": name, "time-from": start, "line-array": lines}]}]}


P = [("students", 9.9), ("internal", 11.9), ("external", 14.9)]
ETH = {"weekly-rota-array": [{"facility-id": 10, "valid-from": "2026-10-19", "valid-to": "2026-10-25",
  "day-of-week-array": [
    {"day-of-week-code": 1, "opening-hour-array": [{"meal-time-array": [
        {"name": "Pranzo (Lunch)", "time-from": "11:30", "line-array": [
            {"name": "Verde", "meal": meal(1, 'Insalata "California', "Mixed salads with iceberg | corn | bacon",
                                           [("students", 8.9)], ["Meat", "Salad"])},
            {"name": "Pasta", "meal": meal(2, "Pasta aglio e olio", "Garlic oil | parsley", P, ["Pasta", "Vegetarian"])},
            {"name": "Al Forno", "meal": meal(3, "Sold Out", "x", P)}]},
        {"name": "Dinner", "time-from": "18:00", "line-array": [
            {"name": "Evening", "meal": meal(4, "Night dish", "", P)}]}]}]},
    day(5, [{"name": "Pasta", "meal": meal(9, "Pasta with Shrimp and Saffron", "Penne | Saffron",
                                          [("internal & students", 11.9)], ["Fish", "Pasta"])}]),
    {"day-of-week-code": 6}, {"day-of-week-code": 7}]}]}

d = parse = b.parse_eth(ETH, dt.date(2026, 10, 19))
assert [x.name for x in d] == ['Insalata "California', "Pasta aglio e olio"], d  # sold out + dinner dropped
assert d[0].price == "8.90" and d[1].tags == ("vegetarian",) and d[0].category == "Verde"
fri = b.parse_eth(ETH, dt.date(2026, 10, 23))
assert len(fri) == 1 and fri[0].price == "11.90" and fri[0].tags == ()          # "internal & students"
assert b.parse_eth(ETH, dt.date(2026, 10, 24)) == []                              # Saturday: closed
assert b.parse_eth(ETH, dt.date(2026, 10, 27)) == []                              # no rota covers it
try:
    b.parse_eth({"oops": 1}, dt.date(2026, 10, 19)); raise SystemExit("should have raised")
except ValueError:
    pass

# ---- food2050 weekly page: structure copied from the real Platte 14 DOM ----
def a(href, name, desc):
    return (f'<a rating="LOW" href="{href}"><div><p class="WeeklyMenuTableCell__CellText-sc-1">'
            f'<span class="DishName__Name-sc-b190d79-0 x">{name}</span>'
            f'<span class="DishName__Description-sc-b190d79-1 y">{desc}</span></p></div></a>')

U = "https://app.food2050.ch/de/zfv/universitat-zurich,platte-14/platte-14/mittagsverpflegung,hauptspeisen"
HTML = f"""<div class="WeeklyMenuTableLargeScreen__Base">
<div class="WeeklyMenuTableLargeScreen__BodyRow-sc-b7ecf598-3"><div><p class="shared__ItemDisplayName-sc-508a2185-1">Yin</p></div>
<div>{a(U+',ying/2026-10-22', 'MASSAMAN TOFU CURRY', 'Erdnüsse')}</div>
<div>{a(U+',ying/2026-10-23', 'TAJINE', 'Auberginen, Karotten, Kichererbsen &amp; Aprikosen, Couscous')}</div></div>
<div class="WeeklyMenuTableLargeScreen__BodyRow-sc-b7ecf598-3"><div><p class="shared__ItemDisplayName-sc-508a2185-1">Yang</p></div>
<div>{a(U+',yang/2026-10-22', 'RINDS PAD KRA PAO', 'Bohnen')}</div>
<div>{a(U+',yang/2026-10-23', 'CHICKEN PANEER CURRY', 'Jasmin Reis, Erbsen')}</div></div></div>
<div class="WeeklyMenuTableSmallScreen__Base"><div class="WeeklyMenuTableSmallScreen__CellContainer">
<p class="shared__ItemDisplayName-sc-508a2185-1">Yin</p>{a(U+',ying/2026-10-23', 'TAJINE', 'Auberginen, Karotten, Kichererbsen &amp; Aprikosen, Couscous')}</div>
<div class="WeeklyMenuTableSmallScreen__CellContainer"><p class="shared__ItemDisplayName-sc-508a2185-1">Yang</p>
{a(U+',yang/2026-10-23', 'CHICKEN PANEER CURRY', 'Jasmin Reis, Erbsen')}</div></div>"""
w = b.parse_zfv_week(HTML, dt.date(2026, 10, 23))
assert [(x["line"], x["name"]) for x in w] == [("Yin", "Tajine"), ("Yang", "Chicken Paneer Curry")], w
assert w[0]["description"].endswith("Aprikosen, Couscous") and w[0]["href"].endswith("2026-10-23")
assert b.parse_zfv_week(HTML, dt.date(2026, 10, 24)) == []                        # weekend: nothing today
try:
    b.parse_zfv_week("<html></html>", dt.date(2026, 10, 23)); raise SystemExit("should have raised")
except ValueError:
    pass

DISH = ('<div><span>Vegan</span></div><h1>TAJINE<span>Auberginen</span></h1><p>6.90 CHF</p><p>Studierende</p>'
        '<p>9.00 CHF</p><p>Mitarbeitende</p><p>13.50 CHF</p><p>Externe</p>')
assert b.parse_zfv_dish(DISH, "Tajine") == ("6.90", ("vegan",))
assert b.parse_zfv_dish("<h1>CURRY</h1><p>no prices</p>", "Curry") == (None, ())

# ---- Obere Mensa: real structure (lines "Menu 1..4", path universitat-zurich,campus-zentrum/obere-mensa/lunch) ----
O = "https://app.food2050.ch/de/zfv/universitat-zurich,campus-zentrum/obere-mensa/lunch"
def row(label, items):
    cells = "".join(f"<div>{a(f'{O},{label.lower().replace(chr(32), chr(45))}/{d}', n, ds)}</div>" for d, n, ds in items)
    return f'<div class="WeeklyMenuTableLargeScreen__BodyRow-sc-b7ecf598-3"><div><p class="shared__ItemDisplayName-sc-508a2185-1">{label}</p></div>{cells}</div>'
OBERE = "<div>" + row("Menu 1", [("2026-10-22", "ROTES POULET CURRY", "Broccoli, Karotten"),
                                  ("2026-10-23", "WALDPILZRISOTTO", "Spinat, Mandeln, Reibkäse, Menüsalat / Apfelmus")]) \
      + row("Menu 3", [("2026-10-23", "GHACKETS &amp; HÖRNLI", "Rindshackfleisch, Reibkäse")]) \
      + row("Menu 4", [("2026-10-23", "PANIERTES SCHNITZEL", "Pommes frites")]) + "</div>"
o = b.parse_zfv_week(OBERE, dt.date(2026, 10, 23))
assert [(x["line"], x["name"]) for x in o] == [("Menu 1", "Waldpilzrisotto"), ("Menu 3", "Ghackets & Hörnli"),
                                                ("Menu 4", "Paniertes Schnitzel")], o
assert next(m for m in b.MENSAS if m.key == "obere").food2050 == "universitat-zurich,campus-zentrum/obere-mensa/lunch"

# ---- message ----
res = {m.key: None for m in b.MENSAS}
res["polysnack"] = d
res["platte"] = [b.Dish(x["line"], x["name"], x["description"], "6.90") for x in w]
res["obere"] = []
msg = b.build_message(dt.date(2026, 10, 23), res)
assert "Mixed salads with iceberg, corn, bacon" in msg and "| Yin | **Tajine**" in msg
assert '"Obere Mensa"' not in msg.split("```")[1] and '"Platte"' in msg
print(msg)
print("\nALL TESTS PASSED")