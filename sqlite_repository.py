# sqlite_repository.py

import sqlite3
import re


class SQLiteCauseListRepository:
    def __init__(self, db_path):
        self.db_path = db_path

    def _date_suffix(self, date):
        dd, mm, yyyy = re.split(r"[-/]", date)
        return f"{yyyy}{mm}{dd}"

    def prepare_tables(self, date):
        suffix = self._date_suffix(date)
        cause = f"cause_list_{suffix}"
        mapping = f"cause_list_judges_{suffix}"

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {cause} (
            cause_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sno TEXT, case_no TEXT,
            petitioner_respondent TEXT,
            advocate TEXT, court_no TEXT, page_no TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS judges (
            judge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            judge_name TEXT UNIQUE
        )
        """)

        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {mapping} (
            cause_id INTEGER,
            judge_id INTEGER,
            PRIMARY KEY (cause_id, judge_id)
        )
        """)

        cur.execute(f"DELETE FROM {mapping}")
        cur.execute(f"DELETE FROM {cause}")

        conn.commit()
        conn.close()

    def insert(self, rows):
        if not rows:
            return

        date = rows[0][7]
        suffix = self._date_suffix(date)
        cause = f"cause_list_{suffix}"
        mapping = f"cause_list_judges_{suffix}"

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        for r in rows:
            cur.execute(
                f"""
                INSERT INTO {cause}
                (sno, case_no, petitioner_respondent, advocate, court_no, page_no)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (r[0], r[1], r[2], r[3], r[5], str(r[8]))
            )

            cause_id = cur.lastrowid

            for j in r[4].split("|"):
                j = j.strip()
                if not j:
                    continue

                cur.execute("INSERT OR IGNORE INTO judges (judge_name) VALUES (?)", (j,))
                cur.execute("SELECT judge_id FROM judges WHERE judge_name = ?", (j,))
                judge_id = cur.fetchone()[0]

                cur.execute(
                    f"INSERT OR IGNORE INTO {mapping} VALUES (?, ?)",
                    (cause_id, judge_id)
                )

        conn.commit()
        conn.close()
