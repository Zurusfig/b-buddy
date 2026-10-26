"""Generate mock data for "Private budget coach" (seeded, no LLM).

    ../../.venv/bin/python gen_data.py

Writes transactions.csv, budget.csv, persona.json next to this file.
Persona: one university student in Bangkok, income ~12,000 THB/month, Apr-Sep 2026.

Planted patterns (asserted at the end):
  1. food spend rises every month
  2. shopping over budget in 2026-07 only
  3. duplicate Netflix subscription from 2026-07 (two spellings, same plan)
  4. a Shopee refund (negative amount) in 2026-08
  5. one large one-off: phone screen repair in 2026-05 (category other)
"""
from __future__ import annotations

import calendar
import csv
import json
import random
from pathlib import Path

SEED = 42
HERE = Path(__file__).resolve().parent
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
INCOME = 12000

BUDGET = {"food": 4500, "transport": 1200, "shopping": 1500, "subscriptions": 300,
          "education": 800, "entertainment": 800, "other": 1000}

# Monthly food totals (THB), strictly rising. Amounts are random, then rescaled to hit these.
FOOD_TARGET = [3200, 3450, 3700, 3950, 4250, 4600]

# merchant spellings (inconsistent on purpose), amount range, payment methods
FOOD = [
    (["7-Eleven", "7-11", "เซเว่น อีเลฟเว่น"], (25, 120), ["cash", "truemoney"]),
    (["GrabFood", "GRAB FOOD", "Grab Food"], (90, 220), ["credit_card"]),
    (["MK", "MK Restaurants", "เอ็มเค สุกี้"], (250, 450), ["credit_card", "promptpay"]),
    (["ร้านข้าวมันไก่", "ข้าวมันไก่ป้าแดง"], (45, 70), ["cash", "promptpay"]),
    (["LINE MAN", "Lineman"], (80, 200), ["truemoney", "credit_card"]),
    (["โรงอาหารมหาวิทยาลัย"], (35, 60), ["cash"]),
]
TRANSPORT = [
    (["BTS", "BTS Skytrain", "รถไฟฟ้า BTS"], (17, 62), ["rabbit_card"]),
    (["MRT"], (17, 45), ["credit_card"]),
    (["Grab", "GRAB TAXI"], (60, 160), ["credit_card"]),
    (["วินมอเตอร์ไซค์"], (15, 40), ["cash"]),
]
SHOPPING = [
    (["Shopee", "SHOPEE TH", "ช้อปปี้"], (99, 450), ["promptpay", "credit_card"]),
    (["Lazada", "LAZADA"], (120, 400), ["credit_card"]),
    (["Uniqlo"], (290, 490), ["credit_card"]),
]
EDUCATION = [
    (["SE-ED Book", "ซีเอ็ดบุ๊คเซ็นเตอร์"], (180, 350), ["credit_card"]),
    (["ร้านถ่ายเอกสาร"], (20, 80), ["cash"]),
]
ENTERTAINMENT = [
    (["SF Cinema", "SF CINEMA"], (160, 240), ["credit_card"]),
    (["Major Cineplex"], (160, 260), ["credit_card"]),
    (["Steam", "STEAM PURCHASE"], (99, 350), ["credit_card"]),
]
OTHER = [
    (["Boots", "Watsons", "วัตสัน"], (60, 250), ["cash", "credit_card"]),
    (["ร้านตัดผม"], (100, 150), ["cash"]),
]
SUBSCRIPTIONS = [("Netflix", 169, 3), ("Spotify", 69, 8), ("iCloud+", 35, 12)]  # name, THB, day

# per-month transaction counts (food is the bulk)
COUNTS = {"food": 36, "transport": 16, "shopping": 3, "education": 2, "entertainment": 3,
          "other": 2}
POOLS = {"food": FOOD, "transport": TRANSPORT, "shopping": SHOPPING, "education": EDUCATION,
         "entertainment": ENTERTAINMENT, "other": OTHER}


def day_in(rng, month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{month}-{rng.randint(1, calendar.monthrange(y, m)[1]):02d}"


def pick(rng, pool):
    names, (lo, hi), methods = rng.choice(pool)
    return rng.choice(names), rng.randint(lo, hi), rng.choice(methods)


def rescale(rows, target):
    """Scale amounts so they sum to exactly `target` (integer THB)."""
    total = sum(r["amount"] for r in rows)
    for r in rows:
        r["amount"] = max(10, round(r["amount"] * target / total))
    rows[-1]["amount"] += target - sum(r["amount"] for r in rows)


def generate():
    rng = random.Random(SEED)
    tx = []
    for mi, month in enumerate(MONTHS):
        for cat, n in COUNTS.items():
            rows = []
            for _ in range(n):
                merchant, amount, method = pick(rng, POOLS[cat])
                rows.append(dict(date=day_in(rng, month), merchant=merchant, amount=amount,
                                 category=cat, payment_method=method))
            if cat == "food":
                rescale(rows, FOOD_TARGET[mi])
            tx += rows

        for name, price, day in SUBSCRIPTIONS:
            tx.append(dict(date=f"{month}-{day:02d}", merchant=name, amount=price,
                           category="subscriptions", payment_method="credit_card"))

        # 3. duplicate subscription: a second Netflix account from July on
        if month >= "2026-07":
            tx.append(dict(date=f"{month}-17", merchant="NETFLIX.COM", amount=169,
                           category="subscriptions", payment_method="truemoney"))

        # 2. shopping over budget in July (11.11-style sale binge)
        if month == "2026-07":
            for merchant, amount in [("Shopee", 1290), ("SHOPEE TH", 459), ("Lazada", 690)]:
                tx.append(dict(date=day_in(rng, month), merchant=merchant, amount=amount,
                               category="shopping", payment_method="credit_card"))

        # 4. refund of the July Shopee item, posted in August
        if month == "2026-08":
            tx.append(dict(date="2026-08-05", merchant="Shopee (refund)", amount=-459,
                           category="shopping", payment_method="credit_card"))

        # 5. large one-off
        if month == "2026-05":
            tx.append(dict(date="2026-05-14", merchant="ร้านซ่อมมือถือ MBK", amount=4900,
                           category="other", payment_method="promptpay"))

    tx.sort(key=lambda r: (r["date"], r["merchant"]))
    return tx


def main():
    tx = generate()
    fields = ["date", "merchant", "amount", "category", "payment_method"]
    with open(HERE / "transactions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(tx)
    with open(HERE / "budget.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "monthly_limit"])
        w.writerows(BUDGET.items())
    (HERE / "persona.json").write_text(json.dumps(
        {"persona": "university student, Bangkok", "monthly_income": INCOME, "currency": "THB",
         "months": MONTHS, "reference_month": MONTHS[-1]}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # ---- summary + pattern checks, computed through tools.py (re-reads the CSVs)
    import tools
    cats = list(BUDGET)
    print(f"transactions.csv: {len(tx)} rows | budget.csv: {len(BUDGET)} rows | seed={SEED}")
    print(f"\n{'month':8} " + " ".join(f"{c[:8]:>8}" for c in cats) + f" {'TOTAL':>8}")
    for m in MONTHS:
        vals = [tools.sum_by_category(m, c) for c in cats]
        print(f"{m:8} " + " ".join(f"{v:>8.0f}" for v in vals) + f" {sum(vals):>8.0f}")
    print(f"{'budget':8} " + " ".join(f"{BUDGET[c]:>8}" for c in cats) + f" {sum(BUDGET.values()):>8}")

    food = [tools.sum_by_category(m, "food") for m in MONTHS]
    assert all(a < b for a, b in zip(food, food[1:])), food
    shop_over = [m for m in MONTHS if any(o["category"] == "shopping" for o in tools.over_budget(m))]
    assert shop_over == ["2026-07"], shop_over
    netflix = [r for r in tx if r["category"] == "subscriptions" and "netflix" in r["merchant"].lower()]
    dup_months = sorted({r["date"][:7] for r in netflix if r["merchant"] == "NETFLIX.COM"})
    refunds = [r for r in tx if r["amount"] < 0]
    assert len(refunds) == 1
    print("\nPlanted patterns (all asserted):")
    print(f"  1. food rising: {' -> '.join(f'{v:.0f}' for v in food)}")
    print(f"  2. shopping over budget only in {shop_over[0]}: "
          f"{tools.sum_by_category('2026-07', 'shopping'):.0f} > {BUDGET['shopping']}")
    print(f"  3. duplicate Netflix ('Netflix' + 'NETFLIX.COM', 169 each) in {', '.join(dup_months)}")
    print(f"  4. refund: {refunds[0]['date']} {refunds[0]['merchant']} {refunds[0]['amount']}")
    print("  5. one-off: 2026-05-14 ร้านซ่อมมือถือ MBK 4900 (other)")
    print("\nover_budget() by month:")
    for m in MONTHS:
        print(f"  {m}: {[(o['category'], o['over_by']) for o in tools.over_budget(m)] or 'none'}")


if __name__ == "__main__":
    main()
