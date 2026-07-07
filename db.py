import sqlite3
import time

from config import DB_PATH

# ---  DB (history + freshness)  ---

def db_init() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                action_name TEXT    NOT NULL,
                output      TEXT    NOT NULL,
                ts          INTEGER NOT NULL
            )
            """
        )

def db_log(action_name: str, output: str) -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO history (action_name, output, ts) VALUES (?, ?, ?)",
            (action_name, output, int(time.time())),
        )

def db_fresh(action_name: str, freshness: int) -> str | None:
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT output, ts FROM history "
            "WHERE action_name = ? ORDER BY ts DESC LIMIT 1",
            (action_name,),
        ).fetchone()

    if row is None:
        return None
    output, ts = row
    if int(time.time()) - ts <= freshness:
        return output
    return None
