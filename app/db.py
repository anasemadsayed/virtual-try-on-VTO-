import sqlite3
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DB = DATA / "shop.db"
for d in ("uploads", "results", "products"):
    (DATA / d).mkdir(parents=True, exist_ok=True)


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS products(
          id INTEGER PRIMARY KEY, name TEXT, category TEXT DEFAULT 'auto',
          image TEXT, credit TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tryons(
          id INTEGER PRIMARY KEY, visitor TEXT, product_id INTEGER, category TEXT,
          person_img TEXT, result_img TEXT, status TEXT, error TEXT, task_id TEXT,
          seconds REAL, ip TEXT, user_agent TEXT, rating INTEGER, comment TEXT,
          created TEXT DEFAULT CURRENT_TIMESTAMP);
        """)


def q(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def run(sql, args=()):
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid
