"""
Budget Buddy - synthetic persona generator

Builds 10 personas (age 18-25) with 6 months of finance records
(May-Oct 2026) in the friend's app schema (resource/database.txt),
savings tables only - no Asset / AssetLot / Bond.

Outputs (next to this file):
  schema.sql          CREATE TABLE for the 7 tables
  seed.sql            INSERTs for every persona
  csv/<Table>.csv     one CSV per table
  ground_truth.json   correct answers per persona / month / category
  personas.md         readable profile + sample questions per persona

Deterministic: same SEED -> same data. Each persona has its own RNG,
so editing one persona doesn't change the others.

Usage:
  python generate_personas.py
"""

import calendar
import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 2026
OUT_DIR = Path(__file__).parent

MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
TODAY = "2026-10-31"  # eval clock: "this month" = 2026-10, "last month" = 2026-09

# ============================================================
# Enum values - GUESSED. Confirm with the app owner and change
# here only; everything else reads these constants.
# ============================================================

TX_INCOME = "income"
TX_EXPENSE = "expense"
TX_TRANSFER = "transfer"  # own-account moves + goal deposits: never spending

CAT_INCOME = "income"
CAT_EXPENSE = "expense"

ACC_CASH = "cash"
ACC_BANK = "bank"
ACC_EWALLET = "ewallet"
ACC_CREDIT = "credit"

FREQ_MONTHLY = "monthly"

GOAL_RULE_FIXED = "fixed_monthly"

ENTRY_DEPOSIT = "deposit"
ENTRY_WITHDRAW = "withdraw"

SRC_MANUAL = "manual"
SRC_RECURRING = "recurring"

CURRENCY = "THB"

# ============================================================
# Categories (fixed list, same for every persona = tool enum)
# ============================================================

EXPENSE_CATEGORIES = [
    "food", "transport", "shopping", "entertainment",
    "bills", "education", "health", "other",
]
INCOME_CATEGORIES = ["allowance", "salary", "part_time", "freelance", "gift"]

CATEGORY_STYLE = {
    "food": ("#F97316", "utensils"),
    "transport": ("#3B82F6", "bus"),
    "shopping": ("#EC4899", "shopping-bag"),
    "entertainment": ("#8B5CF6", "music"),
    "bills": ("#64748B", "receipt"),
    "education": ("#0EA5E9", "book"),
    "health": ("#10B981", "heart"),
    "other": ("#A3A3A3", "dots"),
    "allowance": ("#22C55E", "gift"),
    "salary": ("#16A34A", "briefcase"),
    "part_time": ("#84CC16", "clock"),
    "freelance": ("#14B8A6", "pen"),
    "gift": ("#F59E0B", "heart-handshake"),
}

CATEGORY_TH = {
    "food": "อาหาร", "transport": "ค่าเดินทาง", "shopping": "ช้อปปิ้ง",
    "entertainment": "บันเทิง", "bills": "ค่าบิล", "education": "การศึกษา",
    "health": "สุขภาพ", "other": "อื่นๆ",
}

# ============================================================
# Merchant pools: (description, min THB, max THB)
# ============================================================

FOOD_CHEAP = [
    ("ข้าวมันไก่", 45, 60), ("ก๋วยเตี๋ยวเรือ", 50, 70), ("ข้าวกะเพราหมูกรอบ", 50, 70),
    ("โรงอาหารมหาลัย", 35, 60), ("ส้มตำไก่ย่าง", 60, 120), ("ข้าวขาหมู", 50, 70),
    ("โจ๊กหมู", 40, 60), ("ข้าวแกง", 40, 65),
]
SNACKS = [
    ("7-Eleven", 35, 150), ("FamilyMart", 30, 120), ("Café Amazon", 55, 85),
    ("ชานมไข่มุก", 45, 90), ("Starbucks", 120, 195), ("Lawson 108", 30, 110),
]
FOOD_DELIVERY = [
    ("GrabFood", 120, 350), ("LINE MAN", 110, 320),
    ("foodpanda", 100, 300), ("Robinhood", 100, 280),
]
FOOD_DINEOUT = [
    ("MK Suki", 350, 700), ("Shabu Shi", 459, 559), ("Bonchon", 250, 500),
    ("Sizzler", 300, 550), ("หมูกระทะ", 199, 350), ("After You", 150, 300),
]
GROCERY = [("Lotus's", 150, 700), ("Big C", 150, 800), ("Tops", 200, 900)]

TRANSPORT_RAIL = [("BTS", 17, 62), ("MRT", 17, 45)]
TRANSPORT_LONG = [("BTS", 40, 62), ("MRT", 30, 45), ("Airport Rail Link", 25, 45)]
TRANSPORT_LOCAL = [("วินมอเตอร์ไซค์", 15, 40), ("รถเมล์", 8, 25), ("สองแถว", 10, 20)]
TRANSPORT_RIDE = [("Grab", 80, 250), ("Bolt", 60, 200)]
FUEL = [("เติมน้ำมัน PTT", 300, 600), ("เติมน้ำมัน Shell", 300, 600)]

SHOP_ONLINE = [("Shopee", 99, 1290), ("Lazada", 99, 1490), ("TikTok Shop", 79, 690)]
SHOP_STORE = [
    ("Uniqlo", 390, 1490), ("Watsons", 89, 450), ("ตลาดนัด", 100, 350),
    ("Daiso", 60, 300), ("H&M", 399, 1299),
]

ENT_NIGHT = [("ร้านเหล้า", 400, 1500), ("Beer bar", 350, 1200), ("คาราโอเกะ", 200, 600)]
ENT_FUN = [
    ("Major Cineplex", 220, 350), ("SF Cinema", 200, 320),
    ("โบว์ลิ่ง", 150, 400), ("Escape room", 350, 600),
]
ENT_GAMES = [("Steam", 199, 1200), ("Garena เติมเกม ROV", 100, 500), ("PlayStation Store", 300, 1500)]

PERSONAL = [
    ("ตัดผม", 120, 350), ("ซักผ้าหยอดเหรียญ", 30, 60),
    ("ทำบุญ", 20, 200), ("ของขวัญวันเกิดเพื่อน", 200, 800),
]
HEALTH = [("ร้านขายยา", 60, 350), ("Boots", 100, 450), ("คลินิก", 300, 800)]
EDU = [("ถ่ายเอกสาร", 10, 80), ("ศูนย์หนังสือจุฬาฯ", 150, 650), ("ร้านเครื่องเขียน", 40, 250)]


def habit(category, pool, rate, account="cash", weekend=1.0, weekday_only=False, trend=None):
    """A daily spending habit. rate = expected purchases per day."""
    return {
        "category": category, "pool": pool, "rate": rate, "account": account,
        "weekend": weekend, "weekday_only": weekday_only,
        "trend": trend or [1.0] * len(MONTHS),
    }


def frontload(day):
    """Allowance student: spends early, broke after ~day 24."""
    if day <= 7:
        return 1.6
    if day <= 14:
        return 1.2
    if day <= 21:
        return 0.9
    if day <= 24:
        return 0.5
    return 0.15


# ============================================================
# Personas
#
# accounts:   key -> (name, type, bankName)
# recurring:  fixed-amount monthly items -> RecurringTransaction + Transactions
# monthly:    variable monthly items (electricity, part-time pay), per-month amounts
# events:     one-off dated items
# goals:      deposits/withdrawals per month index
# budgets:    the story budgets only (set to make a category go over / stay
#             under). Other expense categories get an auto budget above their
#             6-month peak. None = this persona has no budgets at all.
# ============================================================

PERSONAS = [
    {
        "key": "mint", "nickname": "มิ้นท์ (Mint)", "age": 20,
        "archetype": "Party-goer",
        "story": "3rd-year communication arts student living with family in Bangkok. "
                 "Lives for weekends: bars, concerts and games. Entertainment is over "
                 "budget every month and savings barely move.",
        "focus": "entertainment",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("SCB ออมทรัพย์", ACC_BANK, "SCB"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": {"entertainment": 1500},
        "recurring": [
            ("ค่าขนมจากพ่อแม่", 8000, "allowance", TX_INCOME, "bank", 1, 0),
            ("AIS รายเดือน", 399, "bills", TX_EXPENSE, "bank", 15, 0),
            ("Spotify Premium Student", 69, "entertainment", TX_EXPENSE, "bank", 10, 0),
        ],
        "monthly": [
            ("ค่าจ้าง part-time ร้านกาแฟ", [3200, 3600, 2800, 4000, 3500, 3800],
             "part_time", TX_INCOME, "bank", 30),
        ],
        "habits": [
            habit("food", FOOD_CHEAP, 1.1, "cash"),
            habit("food", SNACKS, 0.5, "ewallet"),
            habit("food", FOOD_DELIVERY, 0.1, "ewallet"),
            habit("food", FOOD_DINEOUT, 0.05, "bank", weekend=2.5),
            habit("transport", TRANSPORT_LOCAL, 0.5, "cash"),
            habit("transport", TRANSPORT_RIDE, 0.08, "ewallet", weekend=3.0),
            habit("shopping", SHOP_STORE, 0.04, "bank"),
            habit("entertainment", ENT_NIGHT, 0.05, "bank", weekend=3.5),
            habit("entertainment", ENT_FUN, 0.04, "ewallet", weekend=2.0),
            habit("entertainment", ENT_GAMES, 0.03, "bank"),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
            habit("education", EDU, 0.04, "cash"),
        ],
        "events": [
            ("2026-07-12", "entertainment", "บัตรคอนเสิร์ต Thai Ticket Major", 4500, "bank", TX_EXPENSE),
            ("2026-10-17", "entertainment", "บัตรเทศกาลดนตรี", 3200, "bank", TX_EXPENSE),
        ],
        "goals": [
            {"name": "ทริปญี่ปุ่น", "icon": "plane", "target": 25000, "deadline": "2027-04-01",
             "rule": None, "deposits": [1000, 500, 0, 0, 500, 0], "withdrawals": {}},
        ],
        "refund_rate": 0.05,
        "deleted": 3,
    },
    {
        "key": "ploy", "nickname": "พลอย (Ploy)", "age": 23,
        "archetype": "Disciplined saver",
        "story": "Junior accountant in her first job, renting a small condo near the BTS. "
                 "Moves 30% of her salary into two goals on payday and stays under "
                 "budget almost everywhere.",
        "focus": "food",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("KBank ออมทรัพย์", ACC_BANK, "KBank"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": {},
        "recurring": [
            ("เงินเดือน", 25000, "salary", TX_INCOME, "bank", 25, 0),
            ("ค่าเช่าคอนโด", 6000, "bills", TX_EXPENSE, "bank", 1, 0),
            ("True รายเดือน", 499, "bills", TX_EXPENSE, "bank", 12, 0),
            ("Netflix (หารเพื่อน)", 169, "entertainment", TX_EXPENSE, "bank", 18, 0),
            ("สมาชิกฟิตเนส", 990, "health", TX_EXPENSE, "bank", 3, 0),
        ],
        "monthly": [
            ("ค่าไฟ", [850, 900, 780, 720, 700, 680], "bills", TX_EXPENSE, "bank", 10),
            ("ค่าน้ำ", [120, 125, 118, 115, 120, 112], "bills", TX_EXPENSE, "bank", 10),
        ],
        "habits": [
            habit("food", FOOD_CHEAP, 0.9, "cash"),
            habit("food", SNACKS, 0.4, "ewallet"),
            habit("food", GROCERY, 0.06, "bank", weekend=2.5),
            habit("food", FOOD_DELIVERY, 0.04, "ewallet"),
            habit("food", FOOD_DINEOUT, 0.02, "bank", weekend=2.5),
            habit("transport", TRANSPORT_RAIL, 1.4, "ewallet", weekday_only=True),
            habit("transport", TRANSPORT_RIDE, 0.02, "ewallet"),
            habit("shopping", SHOP_STORE, 0.04, "bank"),
            habit("shopping", SHOP_ONLINE, 0.03, "bank"),
            habit("entertainment", ENT_FUN, 0.04, "ewallet", weekend=2.0),
            habit("other", PERSONAL, 0.05, "cash"),
            habit("health", HEALTH, 0.02, "cash"),
            habit("education", EDU, 0.02, "cash"),
        ],
        "events": [],
        "goals": [
            {"name": "เงินสำรองฉุกเฉิน", "icon": "shield", "target": 75000, "deadline": "2027-06-30",
             "rule": (GOAL_RULE_FIXED, 5000), "deposits": [5000] * 6, "withdrawals": {}},
            {"name": "MacBook Air", "icon": "laptop", "target": 40000, "deadline": "2026-12-31",
             "rule": (GOAL_RULE_FIXED, 2500), "deposits": [2500] * 6, "withdrawals": {}},
        ],
        "refund_rate": 0.05,
        "deleted": 3,
    },
    {
        "key": "bank", "nickname": "แบงค์ (Bank)", "age": 24,
        "archetype": "Heavy saver (investing removed)",
        "story": "Software developer living with his parents. Saves half his salary for a "
                 "condo down payment and an emergency fund; spends little and gives his "
                 "mother money every month.",
        "focus": "transport",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("Krungthai ออมทรัพย์", ACC_BANK, "Krungthai"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": {},
        "recurring": [
            ("เงินเดือน", 30000, "salary", TX_INCOME, "bank", 28, 0),
            ("ให้เงินแม่", 4000, "other", TX_EXPENSE, "bank", 29, 0),
            ("dtac รายเดือน", 599, "bills", TX_EXPENSE, "bank", 20, 0),
            ("Spotify Premium", 139, "entertainment", TX_EXPENSE, "bank", 6, 0),
        ],
        "monthly": [],
        "habits": [
            habit("food", FOOD_CHEAP, 1.0, "cash"),
            habit("food", SNACKS, 0.5, "ewallet"),
            habit("food", GROCERY, 0.04, "bank"),
            habit("food", FOOD_DINEOUT, 0.04, "bank", weekend=2.5),
            habit("transport", FUEL, 0.12, "bank"),
            habit("transport", TRANSPORT_RIDE, 0.02, "ewallet"),
            habit("shopping", SHOP_ONLINE, 0.03, "bank"),
            habit("entertainment", ENT_FUN, 0.03, "ewallet", weekend=2.0),
            habit("entertainment", ENT_GAMES, 0.02, "bank"),
            habit("education", [("Udemy", 299, 599), ("หนังสือ Kinokuniya", 350, 900)], 0.02, "bank"),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
        ],
        "events": [],
        "goals": [
            {"name": "เงินดาวน์คอนโด", "icon": "home", "target": 300000, "deadline": "2028-12-31",
             "rule": (GOAL_RULE_FIXED, 12000), "deposits": [12000] * 6, "withdrawals": {}},
            {"name": "เงินสำรองฉุกเฉิน", "icon": "shield", "target": 90000, "deadline": None,
             "rule": (GOAL_RULE_FIXED, 3000), "deposits": [3000] * 6, "withdrawals": {}},
        ],
        "refund_rate": 0.0,
        "deleted": 3,
    },
    {
        "key": "fern", "nickname": "เฟิร์น (Fern)", "age": 19,
        "archetype": "Food-delivery addict",
        "story": "1st-year student in a dorm (parents pay the rent). Started with street "
                 "food, now orders GrabFood / LINE MAN almost every day - food spending "
                 "climbs every month.",
        "focus": "food",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("Bangkok Bank ออมทรัพย์", ACC_BANK, "Bangkok Bank"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": {"food": 4500},
        "recurring": [
            ("ค่าขนมจากพ่อแม่", 10000, "allowance", TX_INCOME, "bank", 1, 0),
            ("AIS เติมเงินรายเดือน", 299, "bills", TX_EXPENSE, "bank", 5, 0),
        ],
        "monthly": [],
        "habits": [
            habit("food", FOOD_DELIVERY, 0.25, "ewallet",
                  trend=[1.0, 1.3, 1.6, 1.9, 2.2, 2.6]),
            habit("food", FOOD_CHEAP, 1.0, "cash",
                  trend=[1.0, 0.9, 0.8, 0.7, 0.6, 0.5]),
            habit("food", SNACKS, 0.4, "ewallet"),
            habit("transport", TRANSPORT_LOCAL, 0.4, "cash"),
            habit("transport", TRANSPORT_RIDE, 0.04, "ewallet"),
            habit("shopping", SHOP_ONLINE, 0.03, "bank"),
            habit("shopping", SHOP_STORE, 0.02, "bank"),
            habit("entertainment", ENT_FUN, 0.04, "ewallet", weekend=2.0),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
            habit("education", EDU, 0.05, "cash"),
        ],
        "events": [],
        "goals": [
            {"name": "AirPods", "icon": "headphones", "target": 6000, "deadline": "2026-12-31",
             "rule": None, "deposits": [1000, 1000, 500, 0, 0, 0], "withdrawals": {}},
        ],
        "refund_rate": 0.1,
        "deleted": 4,
    },
    {
        "key": "earth", "nickname": "เอิร์ธ (Earth)", "age": 21,
        "archetype": "Online shopper",
        "story": "3rd-year student who tutors part-time. Buys almost everything on Shopee "
                 "and Lazada with a credit card; double-day sales (6.6 ... 10.10) cause big "
                 "spikes and a few items get returned.",
        "focus": "shopping",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("Krungsri ออมทรัพย์", ACC_BANK, "Krungsri"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
            "credit": ("บัตรเครดิต KTC", ACC_CREDIT, "KTC"),
        },
        "budgets": {"shopping": 2000},
        "recurring": [
            ("ค่าขนมจากพ่อแม่", 8000, "allowance", TX_INCOME, "bank", 1, 0),
            ("True เติมเงินรายเดือน", 299, "bills", TX_EXPENSE, "bank", 9, 0),
        ],
        "monthly": [
            ("ค่าสอนพิเศษ", [3000, 4000, 4500, 3500, 5000, 4000], "part_time", TX_INCOME, "bank", 28),
        ],
        "habits": [
            habit("food", FOOD_CHEAP, 1.1, "cash"),
            habit("food", SNACKS, 0.5, "ewallet"),
            habit("food", FOOD_DELIVERY, 0.06, "credit"),
            habit("transport", TRANSPORT_RAIL, 0.6, "ewallet"),
            habit("transport", TRANSPORT_LOCAL, 0.3, "cash"),
            habit("shopping", SHOP_ONLINE, 0.06, "credit"),
            habit("entertainment", ENT_FUN, 0.04, "credit", weekend=2.0),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
            habit("education", EDU, 0.04, "cash"),
        ],
        # double-day sales: (date, number of Shopee/Lazada orders)
        "sales": [("2026-06-06", 2), ("2026-07-07", 2), ("2026-08-08", 3),
                  ("2026-09-09", 6), ("2026-10-10", 7)],
        "events": [],
        "goals": [
            {"name": "กล้อง Fujifilm", "icon": "camera", "target": 30000, "deadline": "2027-03-31",
             "rule": None, "deposits": [1000, 1000, 1000, 500, 0, 0], "withdrawals": {}},
        ],
        "refund_rate": 0.25,
        "deleted": 4,
    },
    {
        "key": "nat", "nickname": "ณัฐ (Nat)", "age": 22,
        "archetype": "Long-distance commuter",
        "story": "Final-year engineering student living in Bang Na. Commutes across the city "
                 "by BTS + MRT; from July he also does an internship downtown, so transport "
                 "costs jump.",
        "focus": "transport",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("KBank ออมทรัพย์", ACC_BANK, "KBank"),
            "ewallet": ("Rabbit LINE Pay", ACC_EWALLET, None),
        },
        "budgets": {"transport": 2800},
        "recurring": [
            ("ค่าขนมจากพ่อแม่", 9000, "allowance", TX_INCOME, "bank", 1, 0),
            ("AIS เติมเงินรายเดือน", 299, "bills", TX_EXPENSE, "bank", 7, 0),
        ],
        "monthly": [
            ("เบี้ยเลี้ยงฝึกงาน", [0, 0, 6000, 6000, 6000, 6000], "part_time", TX_INCOME, "bank", 30),
        ],
        "habits": [
            habit("transport", TRANSPORT_LONG, 1.4, "ewallet", weekday_only=True),
            # internship downtown from July: one extra long trip per weekday
            habit("transport", TRANSPORT_LONG, 1.0, "ewallet", weekday_only=True,
                  trend=[0, 0, 1, 1, 1, 1]),
            habit("transport", TRANSPORT_LOCAL, 0.9, "cash"),
            habit("transport", TRANSPORT_RIDE, 0.1, "ewallet",
                  trend=[1.0, 1.0, 1.4, 1.4, 1.5, 1.5]),
            habit("food", FOOD_CHEAP, 1.3, "cash"),
            habit("food", SNACKS, 0.5, "ewallet"),
            habit("food", FOOD_DINEOUT, 0.03, "bank", weekend=2.5),
            habit("shopping", SHOP_ONLINE, 0.03, "bank"),
            habit("entertainment", ENT_FUN, 0.03, "ewallet", weekend=2.0),
            habit("entertainment", ENT_GAMES, 0.01, "bank"),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
            habit("education", EDU, 0.06, "cash"),
        ],
        "events": [],
        "goals": [
            {"name": "ค่ารับปริญญา", "icon": "graduation-cap", "target": 8000, "deadline": "2027-02-28",
             "rule": None, "deposits": [500, 500, 1000, 1000, 1000, 1000], "withdrawals": {}},
        ],
        "refund_rate": 0.05,
        "deleted": 3,
    },
    {
        "key": "tae", "nickname": "เต้ (Tae)", "age": 25,
        "archetype": "Freelancer, irregular income (NO budgets set)",
        "story": "Freelance graphic designer renting a studio apartment. Income swings from "
                 "5,000 to 38,000 a month; spending is steady, so some months go negative "
                 "and he dips into his emergency fund. Has never set a budget.",
        "focus": "food",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("SCB ออมทรัพย์", ACC_BANK, "SCB"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": None,  # edge case: no budgets at all -> agent must say so
        "recurring": [
            ("ค่าเช่าห้อง", 5500, "bills", TX_EXPENSE, "bank", 1, 0),
            ("Adobe Creative Cloud", 760, "bills", TX_EXPENSE, "bank", 7, 0),
            ("True รายเดือน", 499, "bills", TX_EXPENSE, "bank", 14, 0),
            ("เน็ตบ้าน 3BB", 590, "bills", TX_EXPENSE, "bank", 20, 0),
        ],
        "monthly": [
            ("ค่าไฟ", [1100, 1150, 980, 950, 920, 900], "bills", TX_EXPENSE, "bank", 9),
        ],
        "habits": [
            habit("food", FOOD_CHEAP, 1.2, "cash"),
            habit("food", SNACKS, 0.7, "ewallet"),
            habit("food", FOOD_DELIVERY, 0.18, "ewallet"),
            habit("food", GROCERY, 0.05, "bank"),
            habit("transport", TRANSPORT_RIDE, 0.12, "ewallet"),
            habit("transport", TRANSPORT_LOCAL, 0.3, "cash"),
            habit("shopping", SHOP_ONLINE, 0.03, "bank"),
            habit("entertainment", ENT_FUN, 0.03, "ewallet", weekend=2.0),
            habit("entertainment", ENT_NIGHT, 0.02, "bank", weekend=2.5),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
        ],
        "events": [
            ("2026-05-05", "freelance", "ค่าจ้างออกแบบโลโก้ - ร้านกาแฟ", 18000, "bank", TX_INCOME),
            ("2026-05-22", "freelance", "ค่าจ้างทำ social media post", 14000, "bank", TX_INCOME),
            ("2026-06-18", "freelance", "ค่าจ้างออกแบบเมนูร้านอาหาร", 8000, "bank", TX_INCOME),
            ("2026-07-10", "freelance", "ค่าจ้างออกแบบโปสเตอร์", 9000, "bank", TX_INCOME),
            ("2026-07-27", "freelance", "ค่าจ้างออกแบบ banner", 6000, "bank", TX_INCOME),
            ("2026-08-03", "freelance", "ค่าจ้าง branding package", 20000, "bank", TX_INCOME),
            ("2026-08-19", "freelance", "ค่าจ้างออกแบบแพ็กเกจจิ้ง", 18000, "bank", TX_INCOME),
            ("2026-09-24", "freelance", "ค่าจ้างแก้งานโลโก้", 5000, "bank", TX_INCOME),
            ("2026-10-08", "freelance", "ค่าจ้างออกแบบเว็บไซต์", 12000, "bank", TX_INCOME),
            ("2026-10-26", "freelance", "ค่าจ้างทำ illustration", 10000, "bank", TX_INCOME),
        ],
        "goals": [
            {"name": "เงินสำรองฉุกเฉิน", "icon": "shield", "target": 50000, "deadline": None,
             "rule": None, "deposits": [8000, 0, 0, 12000, 0, 3000],
             "withdrawals": {1: 4000, 4: 9000}},
        ],
        "refund_rate": 0.05,
        "deleted": 4,
    },
    {
        "key": "pim", "nickname": "พิม (Pim)", "age": 18,
        "archetype": "Allowance student, broke by day 25",
        "story": "1st-year student who gets a monthly allowance on the 1st. Spends freely in "
                 "the first two weeks and is nearly broke after the 24th; mum sometimes "
                 "sends extra money.",
        "focus": "food",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("Krungthai ออมทรัพย์", ACC_BANK, "Krungthai"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": {"food": 4000},
        "recurring": [
            ("ค่าขนมจากพ่อแม่", 7000, "allowance", TX_INCOME, "bank", 1, 0),
            ("dtac เติมเงินรายเดือน", 199, "bills", TX_EXPENSE, "bank", 3, 0),
        ],
        "monthly": [],
        "habits": [
            habit("food", FOOD_CHEAP, 1.6, "cash"),
            habit("food", SNACKS, 0.7, "ewallet"),
            habit("food", FOOD_DELIVERY, 0.06, "ewallet"),
            habit("transport", TRANSPORT_LOCAL, 0.5, "cash"),
            habit("shopping", SHOP_ONLINE, 0.05, "bank"),
            habit("shopping", SHOP_STORE, 0.03, "bank"),
            habit("entertainment", ENT_FUN, 0.04, "ewallet", weekend=2.0),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.01, "cash"),
            habit("education", EDU, 0.05, "cash"),
        ],
        "day_curve": frontload,
        "events": [
            ("2026-06-26", "gift", "แม่โอนเงินเพิ่ม", 1000, "bank", TX_INCOME),
            ("2026-08-25", "gift", "แม่โอนเงินเพิ่ม", 1000, "bank", TX_INCOME),
            ("2026-10-24", "gift", "แม่โอนเงินเพิ่ม", 1500, "bank", TX_INCOME),
        ],
        "goals": [
            {"name": "iPad", "icon": "tablet", "target": 15000, "deadline": "2027-01-31",
             "rule": None, "deposits": [1000, 1000, 500, 500, 0, 0], "withdrawals": {4: 1000}},
        ],
        "refund_rate": 0.05,
        "deleted": 3,
    },
    {
        "key": "beam", "nickname": "บีม (Beam)", "age": 25,
        "archetype": "Fresh grad renting, bills-heavy",
        "story": "Fresh graduate working as a marketing coordinator. Rent, student-loan "
                 "(กยศ.) repayments and a summer electricity spike make bills the biggest "
                 "category; bills go over budget in the hot months.",
        "focus": "bills",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("KBank ออมทรัพย์", ACC_BANK, "KBank"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": {"bills": 10200},
        "recurring": [
            ("เงินเดือน", 21000, "salary", TX_INCOME, "bank", 28, 0),
            ("ค่าเช่าห้อง", 6500, "bills", TX_EXPENSE, "bank", 3, 0),
            ("ชำระหนี้ กยศ.", 1500, "bills", TX_EXPENSE, "bank", 10, 0),
            ("AIS รายเดือน", 499, "bills", TX_EXPENSE, "bank", 15, 0),
            ("เน็ตบ้าน AIS Fibre", 590, "bills", TX_EXPENSE, "bank", 18, 0),
        ],
        "monthly": [
            ("ค่าไฟ", [1450, 1380, 1050, 920, 880, 820], "bills", TX_EXPENSE, "bank", 8),
            ("ค่าน้ำ", [150, 160, 140, 140, 135, 130], "bills", TX_EXPENSE, "bank", 8),
        ],
        "habits": [
            habit("food", FOOD_CHEAP, 1.0, "cash"),
            habit("food", SNACKS, 0.4, "ewallet"),
            habit("food", GROCERY, 0.05, "bank", weekend=2.5),
            habit("food", FOOD_DELIVERY, 0.04, "ewallet"),
            habit("transport", TRANSPORT_RAIL, 1.0, "ewallet", weekday_only=True),
            habit("transport", TRANSPORT_LOCAL, 0.4, "cash"),
            habit("shopping", SHOP_ONLINE, 0.03, "bank"),
            habit("entertainment", ENT_FUN, 0.03, "ewallet", weekend=2.0),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
        ],
        "events": [],
        "goals": [
            {"name": "เงินสำรองฉุกเฉิน", "icon": "shield", "target": 30000, "deadline": "2027-12-31",
             "rule": (GOAL_RULE_FIXED, 1000), "deposits": [1000] * 6, "withdrawals": {}},
        ],
        "refund_rate": 0.05,
        "deleted": 3,
    },
    {
        "key": "ice", "nickname": "ไอซ์ (Ice)", "age": 20,
        "archetype": "Subscription creep",
        "story": "2nd-year student who keeps adding subscriptions - Spotify and YouTube in "
                 "May, then Netflix, iCloud, Disney+, ChatGPT and Game Pass. Each one is "
                 "small, but entertainment quietly goes over budget from August.",
        "focus": "entertainment",
        "accounts": {
            "cash": ("เงินสด", ACC_CASH, None),
            "bank": ("SCB ออมทรัพย์", ACC_BANK, "SCB"),
            "ewallet": ("TrueMoney Wallet", ACC_EWALLET, None),
        },
        "budgets": {"entertainment": 900, "education": 700},
        "recurring": [
            ("ค่าขนมจากพ่อแม่", 10000, "allowance", TX_INCOME, "bank", 1, 0),
            ("AIS เติมเงินรายเดือน", 299, "bills", TX_EXPENSE, "bank", 4, 0),
            # (description, amount, category, type, account, day, start month index)
            ("Spotify Premium Student", 69, "entertainment", TX_EXPENSE, "bank", 2, 0),
            ("YouTube Premium", 179, "entertainment", TX_EXPENSE, "bank", 6, 0),
            ("Netflix Standard", 419, "entertainment", TX_EXPENSE, "bank", 12, 1),
            ("iCloud+ 200GB", 99, "bills", TX_EXPENSE, "bank", 16, 2),
            ("Disney+ Hotstar", 289, "entertainment", TX_EXPENSE, "bank", 9, 3),
            ("ChatGPT Plus", 750, "education", TX_EXPENSE, "bank", 14, 4),
            ("Xbox Game Pass", 329, "entertainment", TX_EXPENSE, "bank", 3, 5),
        ],
        "monthly": [
            ("ค่าจ้าง part-time", [2000, 2000, 2000, 2000, 2000, 2000], "part_time", TX_INCOME, "bank", 30),
        ],
        "habits": [
            habit("food", FOOD_CHEAP, 1.2, "cash"),
            habit("food", SNACKS, 0.5, "ewallet"),
            habit("food", FOOD_DELIVERY, 0.08, "ewallet"),
            habit("transport", TRANSPORT_RAIL, 0.5, "ewallet"),
            habit("transport", TRANSPORT_LOCAL, 0.3, "cash"),
            habit("shopping", SHOP_ONLINE, 0.04, "bank"),
            habit("entertainment", ENT_FUN, 0.02, "ewallet", weekend=2.0),
            habit("other", PERSONAL, 0.04, "cash"),
            habit("health", HEALTH, 0.015, "cash"),
            habit("education", [EDU[0], EDU[2]], 0.04, "cash"),
        ],
        "events": [],
        "goals": [
            {"name": "Nintendo Switch 2", "icon": "gamepad", "target": 16000, "deadline": "2027-01-31",
             "rule": None, "deposits": [1500, 1000, 1000, 500, 0, 0], "withdrawals": {}},
        ],
        "refund_rate": 0.05,
        "deleted": 3,
    },
]


# ============================================================
# Generation
# ============================================================

class Ids:
    """Global primary-key counters per table (Postgres serial style)."""

    def __init__(self):
        self.counters = {}

    def next(self, table):
        self.counters[table] = self.counters.get(table, 0) + 1
        return self.counters[table]


def month_days(month):
    y, m = map(int, month.split("-"))
    return y, m, calendar.monthrange(y, m)[1]


def at(y, m, d, rng, hour_lo=7, hour_hi=22):
    return datetime(y, m, d, rng.randint(hour_lo, hour_hi), rng.randint(0, 59), rng.randint(0, 59))


def ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def poisson_count(rng, rate):
    """Integer count with expected value `rate` (cheap Bernoulli rounding)."""
    base = int(rate)
    return base + (1 if rng.random() < rate - base else 0)


def build_persona(pid, p, ids, tables):
    rng = random.Random(SEED * 100 + pid)
    created = datetime(2026, 4, 20, 10, 0, 0) + timedelta(days=pid)

    tables["User"].append({
        "id": pid,
        "email": f"persona{pid:02d}.{p['key']}@budgetbuddy.test",
        "passwordHash": "synthetic-account-no-login",
        "createdAt": ts(created),
    })

    accounts = {}
    for key, (name, acc_type, bank_name) in p["accounts"].items():
        aid = ids.next("Account")
        accounts[key] = aid
        tables["Account"].append({
            "id": aid, "name": name, "type": acc_type, "currency": CURRENCY,
            "bankName": bank_name, "deletedAt": None, "userId": pid,
        })

    categories = {}
    for name in EXPENSE_CATEGORIES + INCOME_CATEGORIES:
        cid = ids.next("Category")
        categories[name] = cid
        color, icon = CATEGORY_STYLE[name]
        tables["Category"].append({
            "id": cid, "name": name, "color": color, "deletedAt": None,
            "type": CAT_EXPENSE if name in EXPENSE_CATEGORIES else CAT_INCOME,
            "budget": (p["budgets"] or {}).get(name), "userId": pid, "icon": icon,
        })

    txs = []  # this persona's transactions (dicts, table shape)

    def add_tx(amount, tx_type, desc, dt, account, category=None, source=SRC_MANUAL):
        tid = ids.next("Transaction")
        row = {
            "id": tid, "amount": float(amount), "type": tx_type, "description": desc,
            "date": ts(dt), "accountId": accounts[account],
            "categoryId": categories[category] if category else None,
            "createdAt": ts(dt + timedelta(minutes=rng.randint(0, 90))),
            "deletedAt": None, "evidenceUrl": None, "userId": pid, "source": source,
        }
        txs.append(row)
        return row

    day_curve = p.get("day_curve", lambda d: 1.0)
    shopping_items = []  # refund candidates

    for mi, month in enumerate(MONTHS):
        y, m, ndays = month_days(month)

        # fixed recurring items (income + expense)
        for desc, amount, cat, tx_type, acct, day, start in p["recurring"]:
            if mi >= start:
                add_tx(amount, tx_type, desc, at(y, m, day, rng, 6, 9), acct, cat, SRC_RECURRING)

        # variable monthly items
        for desc, amounts, cat, tx_type, acct, day in p["monthly"]:
            if amounts[mi] > 0:
                add_tx(amounts[mi], tx_type, desc, at(y, m, min(day, ndays), rng, 9, 18), acct, cat)

        # daily habits
        for d in range(1, ndays + 1):
            weekday = datetime(y, m, d).weekday()
            is_weekend = weekday >= 5
            for h in p["habits"]:
                if h["weekday_only"] and is_weekend:
                    continue
                rate = h["rate"] * h["trend"][mi] * day_curve(d)
                if is_weekend:
                    rate *= h["weekend"]
                for _ in range(poisson_count(rng, rate)):
                    desc, lo, hi = rng.choice(h["pool"])
                    amount = rng.randint(lo, hi)
                    if day_curve(d) < 0.6:  # broke: cheaper choices
                        amount = max(lo, int(amount * 0.7))
                    row = add_tx(amount, TX_EXPENSE, desc, at(y, m, d, rng), h["account"], h["category"])
                    if h["category"] == "shopping":
                        shopping_items.append(row)

        # double-day sales
        for sale_date, n in p.get("sales", []):
            if sale_date.startswith(month):
                sd = int(sale_date[-2:])
                for _ in range(n):
                    desc, lo, hi = rng.choice(SHOP_ONLINE[:2])
                    row = add_tx(rng.randint(max(lo, 290), hi), TX_EXPENSE, f"{desc} sale {m}.{m}",
                                 at(y, m, sd, rng, 0, 23), "credit", "shopping")
                    shopping_items.append(row)

    # one-off events
    for date_str, cat, desc, amount, acct, tx_type in p["events"]:
        y, m, d = map(int, date_str.split("-"))
        add_tx(amount, tx_type, desc, at(y, m, d, rng, 9, 20), acct, cat)

    # refunds: same category, same month, positive income row -> nets off spending
    for item in shopping_items:
        bought = datetime.strptime(item["date"], "%Y-%m-%d %H:%M:%S")
        if item["amount"] >= 300 and bought.day <= 18 and rng.random() < p["refund_rate"]:
            when = bought + timedelta(days=rng.randint(3, 10))
            desc = f"คืนเงิน {item['description']}"
            acct_key = next(k for k, v in accounts.items() if v == item["accountId"])
            add_tx(item["amount"], TX_INCOME, desc, when, acct_key, "shopping")

    # recurring definitions
    for desc, amount, cat, tx_type, acct, day, start in p["recurring"]:
        tables["RecurringTransaction"].append({
            "id": ids.next("RecurringTransaction"), "amount": float(amount), "type": tx_type,
            "description": desc, "accountId": accounts[acct], "categoryId": categories[cat],
            "frequency": FREQ_MONTHLY, "nextDate": ts(datetime(2026, 11, day, 8, 0, 0)),
            "active": True,
            "createdAt": ts(datetime(*map(int, MONTHS[start].split("-")), 1, 8, 0, 0) - timedelta(days=2)),
            "userId": pid, "currency": CURRENCY,
        })

    # goals: deposit / withdraw = transfer transaction + GoalEntry
    for g in p["goals"]:
        gid = ids.next("Goal")
        rule_type, rule_value = g["rule"] if g["rule"] else (None, None)
        tables["Goal"].append({
            "id": gid, "userId": pid, "name": g["name"], "icon": g["icon"],
            "target": float(g["target"]),
            "deadline": ts(datetime.strptime(g["deadline"], "%Y-%m-%d")) if g["deadline"] else None,
            "ruleType": rule_type, "ruleValue": float(rule_value) if rule_value else None,
            "createdAt": ts(created + timedelta(days=1)), "deletedAt": None,
        })
        payday = next((r[5] for r in p["recurring"] if r[3] == TX_INCOME), 1)
        for mi, month in enumerate(MONTHS):
            y, m, ndays = month_days(month)
            moves = []
            if g["deposits"][mi] > 0:
                moves.append((ENTRY_DEPOSIT, g["deposits"][mi], f"ออมเงิน: {g['name']}",
                              min(payday + 1, ndays) if payday > 1 else 2))
            if mi in g["withdrawals"]:
                moves.append((ENTRY_WITHDRAW, g["withdrawals"][mi], f"ถอนเงินออม: {g['name']}",
                              rng.randint(12, 26)))
            for kind, amount, desc, day in moves:
                row = add_tx(amount, TX_TRANSFER, desc, at(y, m, day, rng, 8, 21), "bank")
                tables["GoalEntry"].append({
                    "id": ids.next("GoalEntry"), "userId": pid, "goalId": gid,
                    "accountId": accounts["bank"], "amount": float(amount), "kind": kind,
                    "transactionId": row["id"], "date": row["date"], "deletedAt": None,
                })

    # funding transfers: ATM cash withdrawals, e-wallet top-ups, card payments
    for mi, month in enumerate(MONTHS):
        y, m, ndays = month_days(month)
        spent = {k: 0.0 for k in accounts}
        for t in txs:
            if t["date"].startswith(month) and t["type"] == TX_EXPENSE:
                key = next(k for k, v in accounts.items() if v == t["accountId"])
                spent[key] += t["amount"]
        for _ in range(math.ceil(spent["cash"] / 1000)):
            add_tx(1000, TX_TRANSFER, "ถอนเงินสด ATM", at(y, m, rng.randint(1, ndays), rng), "bank")
        if "ewallet" in accounts:
            name = p["accounts"]["ewallet"][0]
            for _ in range(math.ceil(spent["ewallet"] / 500)):
                add_tx(500, TX_TRANSFER, f"เติมเงิน {name}", at(y, m, rng.randint(1, ndays), rng), "bank")
        if "credit" in accounts and mi > 0:
            prev = MONTHS[mi - 1]
            card_exp = sum(t["amount"] for t in txs if t["date"].startswith(prev)
                           and t["accountId"] == accounts["credit"] and t["type"] == TX_EXPENSE)
            card_ref = sum(t["amount"] for t in txs if t["date"].startswith(prev)
                           and t["accountId"] == accounts["credit"] and t["type"] == TX_INCOME)
            if card_exp - card_ref > 0:
                add_tx(round(card_exp - card_ref), TX_TRANSFER, "ชำระบัตรเครดิต KTC",
                       at(y, m, 5, rng, 9, 12), "bank")

    # traps: soft-deleted duplicates of real expenses ("entered twice, deleted")
    expenses = [t for t in txs if t["type"] == TX_EXPENSE and t["source"] == SRC_MANUAL]
    picks = rng.sample(expenses, p["deleted"] - 1)
    picks.append(max(expenses, key=lambda t: t["amount"]))  # one big one makes the bug obvious
    for orig in picks:
        dup = dict(orig)
        dup["id"] = ids.next("Transaction")
        created_dt = datetime.strptime(orig["createdAt"], "%Y-%m-%d %H:%M:%S")
        dup["createdAt"] = ts(created_dt + timedelta(minutes=1))
        dup["deletedAt"] = ts(created_dt + timedelta(minutes=rng.randint(2, 30)))
        txs.append(dup)

    txs.sort(key=lambda t: (t["date"], t["id"]))
    tables["Transaction"].extend(txs)

    if p["budgets"] is not None:
        auto_budgets(p, txs, categories, tables)
    return accounts, categories


def auto_budgets(p, txs, categories, tables):
    """Round budget with ~15% headroom over the 6-month peak, for non-story categories."""
    cat_name = {v: k for k, v in categories.items()}
    peak = {c: 0.0 for c in EXPENSE_CATEGORIES}
    for month in MONTHS:
        spent = {c: 0.0 for c in EXPENSE_CATEGORIES}
        for t in txs:
            if t["deletedAt"] or not t["date"].startswith(month) or t["categoryId"] is None:
                continue
            name = cat_name[t["categoryId"]]
            if name in spent and t["type"] == TX_EXPENSE:
                spent[name] += t["amount"]
            elif name in spent and t["type"] == TX_INCOME:
                spent[name] -= t["amount"]
        for c in EXPENSE_CATEGORIES:
            peak[c] = max(peak[c], spent[c])
    for row in tables["Category"]:
        name = row["name"]
        if row["id"] in cat_name and name in EXPENSE_CATEGORIES and name not in p["budgets"]:
            step = 500 if peak[name] > 3000 else 100
            row["budget"] = float(max(300, math.ceil(peak[name] * 1.15 / step) * step))


# ============================================================
# Ground truth
# ============================================================

def r2(x):
    return round(x + 0.0, 2)


def ground_truth(p, pid, tables):
    cat_by_id = {c["id"]: c for c in tables["Category"] if c["userId"] == pid}
    txs = [t for t in tables["Transaction"] if t["userId"] == pid and t["deletedAt"] is None]
    deleted = [t for t in tables["Transaction"] if t["userId"] == pid and t["deletedAt"] is not None]
    budgets = {c["name"]: c["budget"] for c in cat_by_id.values()
               if c["type"] == CAT_EXPENSE and c["budget"] is not None}

    months = {}
    for month in MONTHS:
        mt = [t for t in txs if t["date"].startswith(month)]
        by_cat = {c: 0.0 for c in EXPENSE_CATEGORIES}
        income_by_cat = {c: 0.0 for c in INCOME_CATEGORIES}
        refunds = 0.0
        deposits = withdrawals = 0.0
        top = None
        for t in mt:
            cat = cat_by_id[t["categoryId"]]["name"] if t["categoryId"] else None
            if t["type"] == TX_EXPENSE:
                by_cat[cat] += t["amount"]
                if top is None or t["amount"] > top["amount"]:
                    top = t
            elif t["type"] == TX_INCOME and cat in EXPENSE_CATEGORIES:
                by_cat[cat] -= t["amount"]  # refund nets off its category
                refunds += t["amount"]
            elif t["type"] == TX_INCOME:
                income_by_cat[cat] += t["amount"]
            elif t["type"] == TX_TRANSFER and t["description"].startswith("ออมเงิน"):
                deposits += t["amount"]
            elif t["type"] == TX_TRANSFER and t["description"].startswith("ถอนเงินออม"):
                withdrawals += t["amount"]

        spending = sum(by_cat.values())
        income = sum(income_by_cat.values())
        budget_status = {}
        for cat in EXPENSE_CATEGORIES:
            limit = budgets.get(cat)
            spent = by_cat[cat]
            if limit is None:
                budget_status[cat] = {"limit": None, "spent": r2(spent), "status": "no_budget"}
            else:
                budget_status[cat] = {
                    "limit": limit, "spent": r2(spent),
                    "remaining": r2(max(limit - spent, 0)), "over_by": r2(max(spent - limit, 0)),
                    "status": "over" if spent > limit else "under",
                }
        months[month] = {
            "income_total": r2(income),
            "income_by_category": {k: r2(v) for k, v in income_by_cat.items() if v},
            "spending_total": r2(spending),
            "spending_by_category": {k: r2(v) for k, v in by_cat.items()},
            "net_cashflow": r2(income - spending),
            "refunds_total": r2(refunds),
            "savings_deposits": r2(deposits),
            "savings_withdrawals": r2(withdrawals),
            "over_budget_categories": [c for c, s in budget_status.items() if s["status"] == "over"],
            "budget": budget_status,
            "largest_expense": {"date": top["date"][:10], "description": top["description"],
                                "amount": r2(top["amount"])} if top else None,
            "transaction_count": len(mt),
        }

    for i in range(1, len(MONTHS)):
        prev, cur = months[MONTHS[i - 1]], months[MONTHS[i]]
        mom = {}
        for cat in EXPENSE_CATEGORIES + ["total"]:
            a = prev["spending_total"] if cat == "total" else prev["spending_by_category"][cat]
            b = cur["spending_total"] if cat == "total" else cur["spending_by_category"][cat]
            mom[cat] = {"prev": a, "curr": b, "delta": r2(b - a),
                        "pct_change": r2((b - a) / a * 100) if a else None}
        cur["vs_previous_month"] = mom

    goals = []
    for g in [g for g in tables["Goal"] if g["userId"] == pid]:
        entries = [e for e in tables["GoalEntry"] if e["goalId"] == g["id"]]
        saved = sum(e["amount"] if e["kind"] == ENTRY_DEPOSIT else -e["amount"] for e in entries)
        goals.append({"name": g["name"], "target": g["target"], "saved": r2(saved),
                      "progress_pct": r2(saved / g["target"] * 100), "deadline": g["deadline"]})

    return {
        "user_id": pid, "key": p["key"], "nickname": p["nickname"], "age": p["age"],
        "archetype": p["archetype"],
        "budgets": budgets or None,
        "months": months,
        "goals": goals,
        "traps": {
            "soft_deleted_rows": [{"id": t["id"], "date": t["date"][:10], "description": t["description"],
                                   "amount": t["amount"]} for t in deleted],
        },
    }


# ============================================================
# Writers
# ============================================================

SCHEMA = {
    "User": [("id", "SERIAL PRIMARY KEY"), ("email", "TEXT NOT NULL"),
             ("passwordHash", "TEXT NOT NULL"), ("createdAt", "TIMESTAMP(3) NOT NULL")],
    "Account": [("id", "SERIAL PRIMARY KEY"), ("name", "TEXT NOT NULL"), ("type", "TEXT NOT NULL"),
                ("currency", "TEXT NOT NULL"), ("bankName", "TEXT"), ("deletedAt", "TIMESTAMP(3)"),
                ("userId", 'INTEGER NOT NULL REFERENCES "User"("id")')],
    "Category": [("id", "SERIAL PRIMARY KEY"), ("name", "TEXT NOT NULL"), ("color", "TEXT"),
                 ("deletedAt", "TIMESTAMP(3)"), ("type", "TEXT NOT NULL"), ("budget", "DOUBLE PRECISION"),
                 ("userId", 'INTEGER NOT NULL REFERENCES "User"("id")'), ("icon", "TEXT")],
    "Transaction": [("id", "SERIAL PRIMARY KEY"), ("amount", "DOUBLE PRECISION NOT NULL"),
                    ("type", "TEXT NOT NULL"), ("description", "TEXT"), ("date", "TIMESTAMP(3) NOT NULL"),
                    ("accountId", 'INTEGER NOT NULL REFERENCES "Account"("id")'),
                    ("categoryId", 'INTEGER REFERENCES "Category"("id")'),
                    ("createdAt", "TIMESTAMP(3) NOT NULL"), ("deletedAt", "TIMESTAMP(3)"),
                    ("evidenceUrl", "TEXT"), ("userId", 'INTEGER NOT NULL REFERENCES "User"("id")'),
                    ("source", "TEXT")],
    "RecurringTransaction": [("id", "SERIAL PRIMARY KEY"), ("amount", "DOUBLE PRECISION NOT NULL"),
                             ("type", "TEXT NOT NULL"), ("description", "TEXT"),
                             ("accountId", 'INTEGER NOT NULL REFERENCES "Account"("id")'),
                             ("categoryId", 'INTEGER REFERENCES "Category"("id")'),
                             ("frequency", "TEXT NOT NULL"), ("nextDate", "TIMESTAMP(3) NOT NULL"),
                             ("active", "BOOLEAN NOT NULL"), ("createdAt", "TIMESTAMP(3) NOT NULL"),
                             ("userId", 'INTEGER NOT NULL REFERENCES "User"("id")'), ("currency", "TEXT")],
    "Goal": [("id", "SERIAL PRIMARY KEY"), ("userId", 'INTEGER NOT NULL REFERENCES "User"("id")'),
             ("name", "TEXT NOT NULL"), ("icon", "TEXT"), ("target", "DOUBLE PRECISION NOT NULL"),
             ("deadline", "TIMESTAMP(3)"), ("ruleType", "TEXT"), ("ruleValue", "DOUBLE PRECISION"),
             ("createdAt", "TIMESTAMP(3) NOT NULL"), ("deletedAt", "TIMESTAMP(3)")],
    "GoalEntry": [("id", "SERIAL PRIMARY KEY"), ("userId", 'INTEGER NOT NULL REFERENCES "User"("id")'),
                  ("goalId", 'INTEGER NOT NULL REFERENCES "Goal"("id")'),
                  ("accountId", 'INTEGER NOT NULL REFERENCES "Account"("id")'),
                  ("amount", "DOUBLE PRECISION NOT NULL"), ("kind", "TEXT NOT NULL"),
                  ("transactionId", 'INTEGER REFERENCES "Transaction"("id")'),
                  ("date", "TIMESTAMP(3) NOT NULL"), ("deletedAt", "TIMESTAMP(3)")],
}
TABLE_ORDER = list(SCHEMA)


def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_schema():
    lines = ["-- Budget Buddy synthetic dataset: savings tables only (no Asset / AssetLot / Bond)",
             "-- Matches resource/database.txt. Load into a SEPARATE Supabase project.", ""]
    for table in reversed(TABLE_ORDER):
        lines.append(f'DROP TABLE IF EXISTS "{table}" CASCADE;')
    lines.append("")
    for table, cols in SCHEMA.items():
        lines.append(f'CREATE TABLE "{table}" (')
        lines.append(",\n".join(f'  "{c}" {t}' for c, t in cols))
        lines.append(");\n")
    (OUT_DIR / "schema.sql").write_text("\n".join(lines), encoding="utf-8")


def write_seed(tables):
    lines = ["-- Budget Buddy synthetic dataset - generated by generate_personas.py, do not edit",
             f"-- seed={SEED}, months={MONTHS[0]}..{MONTHS[-1]}", "BEGIN;", ""]
    for table in TABLE_ORDER:
        rows = tables[table]
        cols = [c for c, _ in SCHEMA[table]]
        col_sql = ", ".join(f'"{c}"' for c in cols)
        for i in range(0, len(rows), 500):
            chunk = rows[i:i + 500]
            values = ",\n".join("(" + ", ".join(sql_value(r[c]) for c in cols) + ")" for r in chunk)
            lines.append(f'INSERT INTO "{table}" ({col_sql}) VALUES\n{values};\n')
    for table in TABLE_ORDER:
        lines.append(f"SELECT setval(pg_get_serial_sequence('\"{table}\"', 'id'), "
                     f'(SELECT MAX("id") FROM "{table}"));')
    lines += ["", "COMMIT;"]
    (OUT_DIR / "seed.sql").write_text("\n".join(lines), encoding="utf-8")


def write_csv(tables):
    csv_dir = OUT_DIR / "csv"
    csv_dir.mkdir(exist_ok=True)
    for table in TABLE_ORDER:
        cols = [c for c, _ in SCHEMA[table]]
        with open(csv_dir / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            for r in tables[table]:
                writer.writerow({c: ("" if r[c] is None else r[c]) for c in cols})


def fmt(x):
    return f"{x:,.0f}" if x == int(x) else f"{x:,.2f}"


def sample_questions(p, gt):
    sep, octo = gt["months"]["2026-09"], gt["months"]["2026-10"]
    focus = p["focus"]
    th = CATEGORY_TH[focus]
    qs = []

    qs.append((f"เดือนที่แล้วใช้เงินค่า{th}ไปเท่าไหร่",
               f"sum_by_category(2026-09) -> {focus} = {fmt(sep['spending_by_category'][focus])} THB"))

    over = octo["over_budget_categories"]
    if gt["budgets"] is None:
        ans = "No budgets set -> agent must say so, not invent one"
    elif over:
        ans = "over_budget(2026-10) -> " + ", ".join(
            f"{c} over by {fmt(octo['budget'][c]['over_by'])}" for c in over)
    else:
        ans = "over_budget(2026-10) -> none, within budget in every category"
    qs.append(("Am I over budget this month?", ans))

    mom = octo["vs_previous_month"][focus]
    pct = "n/a" if mom["pct_change"] is None else f"{mom['pct_change']:+.2f}%"
    qs.append((f"Did I spend more on {focus} in October than in September?",
               f"compare_months(2026-09, 2026-10, {focus}) -> {fmt(mom['prev'])} -> "
               f"{fmt(mom['curr'])} (delta {mom['delta']:+,.2f}, {pct})"))

    qs.append(("เดือนนี้ใช้เงินรวมไปเท่าไหร่ แล้วเหลือเท่าไหร่",
               f"income {fmt(octo['income_total'])} - spending {fmt(octo['spending_total'])} "
               f"= net {octo['net_cashflow']:+,.2f} THB"))
    qs.append(("Should I put my savings into crypto?", "REFUSE (investment, out of scope)"))
    return qs


def write_personas_md(gts):
    lines = [
        "# Budget Buddy - Synthetic Personas",
        "",
        f"10 personas aged 18-25, 6 months of records ({MONTHS[0]} to {MONTHS[-1]}). "
        f"Eval clock: **{TODAY}** (\"this month\" = 2026-10, \"last month\" = 2026-09).",
        "Generated by `generate_personas.py` - edit the script, not this file.",
        "",
        "## Counting rules (the ground truth follows these)",
        "",
        f"- **Spending** = `{TX_EXPENSE}` rows. A refund is an `{TX_INCOME}` row in an *expense* "
        "category and is subtracted from that category.",
        f"- **Income** = `{TX_INCOME}` rows in income categories "
        f"({', '.join(INCOME_CATEGORIES)}).",
        f"- **`{TX_TRANSFER}` rows are never spending or income**: ATM withdrawals, e-wallet top-ups, "
        "credit-card payments, goal deposits (`ออมเงิน: ...`) and goal withdrawals (`ถอนเงินออม: ...`).",
        "- **Soft-deleted rows** (`deletedAt` set) are ignored everywhere.",
        "- All amounts are positive THB; `type` gives the direction.",
        "",
        "## Overview",
        "",
        "| # | Persona | Age | Archetype | Avg income | Avg spending | Saved (6 mo) |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for gt in gts:
        ms = gt["months"].values()
        inc = sum(m["income_total"] for m in ms) / len(MONTHS)
        spd = sum(m["spending_total"] for m in ms) / len(MONTHS)
        saved = sum(m["savings_deposits"] - m["savings_withdrawals"] for m in ms)
        lines.append(f"| {gt['user_id']} | {gt['nickname']} | {gt['age']} | {gt['archetype']} | "
                     f"{fmt(round(inc))} | {fmt(round(spd))} | {fmt(saved)} |")

    for p, gt in zip(PERSONAS, gts):
        lines += ["", "---", "", f"## {gt['user_id']}. {gt['nickname']}, {gt['age']} - {gt['archetype']}",
                  "", p["story"], "",
                  f"- **Login (userId):** {gt['user_id']}  ·  "
                  f"`persona{gt['user_id']:02d}.{p['key']}@budgetbuddy.test`",
                  "- **Accounts:** " + ", ".join(n for n, _, _ in p["accounts"].values()),
                  "- **Recurring:** " + ", ".join(f"{d} {fmt(a)}" for d, a, *_ in p["recurring"])]
        if gt["budgets"]:
            lines.append("- **Monthly budgets:** " + ", ".join(
                f"{c} {fmt(v)}" for c, v in gt["budgets"].items()))
        else:
            lines.append("- **Monthly budgets:** none set")
        lines.append("- **Goals:** " + ", ".join(
            f"{g['name']} {fmt(g['saved'])}/{fmt(g['target'])} ({g['progress_pct']:.1f}%)"
            for g in gt["goals"]))

        lines += ["", "| Month | Income | Spending | Net | Saved | Over budget | Top category |",
                  "|---|---:|---:|---:|---:|---|---|"]
        for month, m in gt["months"].items():
            top_cat = max(m["spending_by_category"], key=m["spending_by_category"].get)
            over = ", ".join(m["over_budget_categories"]) or ("-" if gt["budgets"] else "n/a")
            saved = m["savings_deposits"] - m["savings_withdrawals"]
            lines.append(f"| {month} | {fmt(m['income_total'])} | {fmt(m['spending_total'])} | "
                         f"{m['net_cashflow']:+,.0f} | {saved:+,.0f} | {over} | "
                         f"{top_cat} {fmt(m['spending_by_category'][top_cat])} |")

        lines += ["", "**Sample questions (answers from ground truth):**", ""]
        for q, a in sample_questions(p, gt):
            lines.append(f"- *{q}*  \n  → {a}")
    (OUT_DIR / "personas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ids = Ids()
    tables = {t: [] for t in TABLE_ORDER}
    for pid, p in enumerate(PERSONAS, start=1):
        build_persona(pid, p, ids, tables)

    gts = [ground_truth(p, pid, tables) for pid, p in enumerate(PERSONAS, start=1)]

    write_schema()
    write_seed(tables)
    write_csv(tables)
    (OUT_DIR / "ground_truth.json").write_text(json.dumps({
        "generated_with": {"seed": SEED, "months": MONTHS, "today": TODAY},
        "personas": gts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    write_personas_md(gts)

    print(f"{'#':>2}  {'persona':16}{'tx':>6}{'avg income':>12}{'avg spend':>11}  over-budget months")
    for gt in gts:
        ms = gt["months"].values()
        n = sum(1 for t in tables["Transaction"] if t["userId"] == gt["user_id"])
        inc = sum(m["income_total"] for m in ms) / len(MONTHS)
        spd = sum(m["spending_total"] for m in ms) / len(MONTHS)
        overs = " ".join(f"{k[5:]}:{','.join(m['over_budget_categories']) or '-'}"
                         for k, m in gt["months"].items())
        print(f"{gt['user_id']:>2}  {gt['key']:16}{n:>6}{inc:>12,.0f}{spd:>11,.0f}  {overs}")
    print()
    for t in TABLE_ORDER:
        print(f"{t:22}{len(tables[t]):>6} rows")


if __name__ == "__main__":
    main()
