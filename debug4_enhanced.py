import pdfplumber
import re
import csv
import sqlite3

# --- CONFIGURATION ---
FILE_PATH = "cause_list20251230.pdf"
HEADER_GRAY = (0.8, 0.8, 0.8)
WHITE = (1.0, 1.0, 1.0)

HEADERS = [
    "SNO.",
    "CASE NO.",
    "Petitioner / Respondent",
    "Petitioner / Respondent ADVOCATE"
]

TABLE_END_X_TOLERANCE = 15  # px tolerance for "NEW DELHI" near first column

class SupremeCourtParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self._is_parsing_table = False
        self._columns = []

        self._current_session = {
            "date": None,
            "court": None,
            "court_no": None,   # ✅ ADDED
            "justices": []
        }

        self.extracted_rows = []

    # ---------------- HELPERS ---------------- #
    def _date_to_table_suffix(self, date_str):
        """
        Convert DD-MM-YYYY or DD/MM/YYYY → YYYYMMDD
        """
        parts = re.split(r"[-/]", date_str)
        if len(parts) != 3:
            raise ValueError(f"Invalid date format: {date_str}")

        dd, mm, yyyy = parts
        return f"{yyyy}{mm}{dd}"

    def clear_tables_for_date(self, date_str, db_path="cause_list.db"):
        import sqlite3

        suffix = self._date_to_table_suffix(date_str)
        cause_table = f"cause_list_{suffix}"
        map_table = f"cause_list_judges_{suffix}"

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Mapping table first (FK safety)
        cur.execute(f"DELETE FROM {map_table}")
        cur.execute(f"DELETE FROM {cause_table}")

        conn.commit()
        conn.close()

    def create_sqlite_tables_for_date(self, date_str, db_path="cause_list.db"):
        suffix = self._date_to_table_suffix(date_str)
        cause_table = f"cause_list_{suffix}"
        map_table = f"cause_list_judges_{suffix}"

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Cause list table (date-specific)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {cause_table} (
            cause_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sno TEXT NOT NULL,
            case_no TEXT,
            petitioner_respondent TEXT,
            advocate TEXT,
            court_no TEXT,
            page_no TEXT
        )
        """)

        # Judges master table (global)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS judges (
            judge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            judge_name TEXT UNIQUE NOT NULL
        )
        """)

        # Mapping table (date-specific)
        cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {map_table} (
            cause_id INTEGER NOT NULL,
            judge_id INTEGER NOT NULL,
            PRIMARY KEY (cause_id, judge_id),
            FOREIGN KEY (cause_id) REFERENCES {cause_table}(cause_id),
            FOREIGN KEY (judge_id) REFERENCES judges(judge_id)
        )
        """)

        conn.commit()
        conn.close()

    def insert_into_sqlite_for_date(self, db_path="cause_list.db"):
        if not self.extracted_rows:
            return

        # All rows belong to the same date
        date_str = self.extracted_rows[0][7]
        suffix = self._date_to_table_suffix(date_str)

        cause_table = f"cause_list_{suffix}"
        map_table = f"cause_list_judges_{suffix}"

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        for row in self.extracted_rows:
            sno = row[0]
            case_no = row[1]
            petitioner = row[2]
            advocate = row[3]
            judges_str = row[4]
            court_no = row[5]
            page_no = str(row[8])

            # Insert cause row
            cur.execute(f"""
            INSERT INTO {cause_table}
            (sno, case_no, petitioner_respondent, advocate, court_no, page_no)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                sno,
                case_no,
                petitioner,
                advocate,
                court_no,
                page_no
            ))

            cause_id = cur.lastrowid

            judges = [j.strip() for j in judges_str.split("|") if j.strip()]

            for judge in judges:
                cur.execute(
                    "INSERT OR IGNORE INTO judges (judge_name) VALUES (?)",
                    (judge,)
                )

                cur.execute(
                    "SELECT judge_id FROM judges WHERE judge_name = ?",
                    (judge,)
                )
                judge_id = cur.fetchone()[0]

                cur.execute(f"""
                INSERT OR IGNORE INTO {map_table}
                (cause_id, judge_id)
                VALUES (?, ?)
                """, (cause_id, judge_id))

        conn.commit()
        conn.close()

    def normalize_color(self, color):
        if color is None:
            return WHITE
        if isinstance(color, (int, float)):
            color = (color,)
        return tuple(round(float(c), 1) for c in color)

    def get_bg_color(self, word, page):
        mid_x = (word['x0'] + word['x1']) / 2
        mid_y = (word['top'] + word['bottom']) / 2

        for r in page.rects:
            if r['x0'] <= mid_x <= r['x1'] and r['top'] <= mid_y <= r['bottom']:
                return self.normalize_color(r.get('non_stroking_color'))

        return WHITE

    def _normalize_for_match(self, text):
        return text.upper().replace(" ", "").replace("/", "").replace(".", "")

    # ---------------- HEADER EXTRACTION ---------------- #

    def extract_header_definition(self, words_list, page_width):
        all_words = [w for row in words_list for w in row]
        all_words.sort(key=lambda x: (x['x0'], x['top']))

        temp_cols = []
        used_indices = set()

        for target in HEADERS:
            clean_target = self._normalize_for_match(target)
            header_found = False

            i = 0
            while i < len(all_words) and not header_found:
                if i in used_indices:
                    i += 1
                    continue

                buffer = []
                buffer_indices = []

                j = i
                while j < len(all_words):
                    if j in used_indices:
                        break

                    buffer.append(all_words[j])
                    buffer_indices.append(j)

                    combined = "".join(w['text'] for w in buffer)
                    clean_combined = self._normalize_for_match(combined)

                    if clean_combined == clean_target:
                        temp_cols.append({
                            "name": target,
                            "x0": min(w['x0'] for w in buffer)
                        })
                        used_indices.update(buffer_indices)
                        header_found = True
                        break

                    if not clean_target.startswith(clean_combined):
                        break

                    j += 1

                i += 1

        for i in range(len(temp_cols)):
            if i + 1 < len(temp_cols):
                temp_cols[i]['x1'] = temp_cols[i + 1]['x0'] - 2
            else:
                temp_cols[i]['x1'] = page_width - 20

        return temp_cols

    # ---------------- ROW PROCESSING ---------------- #

    def process_line(self, line_words):
        row_data = [""] * len(self._columns)

        for w in line_words:
            for i, col in enumerate(self._columns):
                if col['x0'] <= w['x0'] <= col['x1']:
                    row_data[i] = (row_data[i] + " " + w['text']).strip()
                    break

        return row_data

    def merge_extracted_rows(self):
        """
        Merge continuation rows based on SNO column.
        Handles decimal SNO split across rows.
        Applies strict validation on selected metadata columns,
        with special handling for Page No.
        """

        if not self.extracted_rows:
            return

        header_index = {name: i for i, name in enumerate(HEADERS)}
        sno_index = header_index["SNO."]

        MERGE_COLUMNS = {
            "CASE NO.",
            "Petitioner / Respondent",
            "Petitioner / Respondent ADVOCATE"
        }
        merge_indices = {header_index[h] for h in MERGE_COLUMNS}

        # Metadata column indices (after HEADERS)
        metadata_start = len(HEADERS)
        metadata_names = ["Judges", "Court No", "Court", "Date", "Page No"]

        metadata_index = {
            name: metadata_start + i
            for i, name in enumerate(metadata_names)
        }

        validate_indices = {
            metadata_index["Judges"],
            metadata_index["Court No"],
            metadata_index["Court"],
            metadata_index["Date"],
        }

        page_no_index = metadata_index["Page No"]

        merged_rows = []
        current_row = None
        current_sno = None

        for row_idx, row in enumerate(self.extracted_rows, start=1):
            raw_sno = row[sno_index].strip() if row[sno_index] else ""
            page_no = row[page_no_index]

            # ---------- SNO DECISION ----------
            is_decimal_continuation = raw_sno.startswith(".") and current_row
            is_new_row = raw_sno and not raw_sno.startswith(".")

            if is_new_row:
                if current_row:
                    merged_rows.append(current_row)

                current_row = row.copy()
                current_sno = raw_sno
                continue

            if is_decimal_continuation:
                current_row[sno_index] = current_row[sno_index] + raw_sno
                continue

            # ---------- CONTINUATION ROW ----------
            if not current_row:
                continue

            for i in range(len(row)):
                if not row[i]:
                    continue

                # Merge text columns
                if i in merge_indices:
                    current_row[i] = (
                        (current_row[i] + " " + row[i]).strip()
                        if current_row[i]
                        else row[i]
                    )

                # Validate selected metadata columns
                elif i in validate_indices:
                    if not current_row[i]:
                        current_row[i] = row[i]
                    elif current_row[i] != row[i]:
                        raise ValueError(
                            f"Metadata mismatch while merging rows. "
                            f"SNO: {current_sno}, "
                            f"Row index: {row_idx}, "
                            f"Column index: {i}, "
                            f"Values: '{current_row[i]}' != '{row[i]}'"
                        )

                # Special handling for Page No
                elif i == page_no_index:
                    # Normalize to string
                    current_val = str(current_row[i]) if current_row[i] is not None else ""
                    new_val = str(row[i]) if row[i] is not None else ""

                    if not current_val:
                        current_row[i] = new_val
                    elif new_val and new_val not in current_val.split(", "):
                        current_row[i] = f"{current_val}, {new_val}"

                # All other columns → ignore

        if current_row:
            merged_rows.append(current_row)

        self.extracted_rows = merged_rows

    # ---------------- CSV EXPORT ---------------- #

    def export_to_csv(self, filename="output.csv"):
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                HEADERS + ["Judges", "Court No", "Court", "Date", "Page No"]
            )
            writer.writerows(self.extracted_rows)

    # ---------------- MAIN RUN ---------------- #

    def run(self):
        with pdfplumber.open(self.file_path) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):  # ✅ ADDED

                words = page.extract_words(x_tolerance=2)
                lines = {}

                for w in words:
                    lines.setdefault(round(w["top"], 1), []).append(w)

                possible_header_rows = []
                is_collecting_header = False

                for top in sorted(lines.keys()):
                    line_words = lines[top]
                    line_words.sort(key=lambda w: w['x0'])
                    line_text = " ".join(w["text"] for w in line_words)
                    upper_text = line_text.upper()

                    # ✅ DO NOT PARSE METADATA WHILE TABLE IS ACTIVE
                    parse_metadata = not self._is_parsing_table

                    # ---------- TABLE END DETECTION ----------
                    if (
                        self._is_parsing_table
                        and "NEW DELHI" in upper_text
                        and abs(line_words[0]['x0'] - self._columns[0]['x0']) <= TABLE_END_X_TOLERANCE
                    ):
                        self._is_parsing_table = False
                        self._columns = []
                        # ✅ RESET TABLE-LEVEL METADATA
                        self._current_session["justices"] = []
                        self._current_session["court"] = None
                        self._current_session["date"] = None
                        self._current_session["court_no"] = None

                        if "NEW DELHI" in upper_text:
                            self._current_session["court"] = "NEW DELHI"

                        continue

                    if parse_metadata:

                        first_word = line_words[0]["text"].upper()
                        if first_word.startswith("HON"):
                            self._current_session["justices"].append(line_text.strip())

                        date_match = re.search(
                            r"DAILY\s+CAUSE\s+LIST\s+FOR\s+DATED\s*[:\-]?\s*(\d{2}[-/]\d{2}[-/]\d{4})",
                            line_text,
                            re.IGNORECASE
                        )
                        if date_match:
                            self._current_session["date"] = date_match.group(1)

                        court_no_match = re.search(
                            r"COURT\s*NO\.?\s*[:\-]?\s*(\d+)",
                            line_text,
                            re.IGNORECASE
                        )
                        if court_no_match:
                            self._current_session["court_no"] = court_no_match.group(1)

                        # ---------- HEADER DETECTION ----------
                        is_header_by_text = all(
                            h.replace(".", "") in self._normalize_for_match(upper_text)
                            for h in ["SNO", "CASE"]
                        )

                        is_header_by_color = (
                            self.get_bg_color(line_words[0], page) == HEADER_GRAY
                        )

                        if is_header_by_color or is_header_by_text:
                            is_collecting_header = True
                            possible_header_rows.append(line_words)
                            self._is_parsing_table = False
                            continue

                        if is_collecting_header:
                            self._columns = self.extract_header_definition(
                                possible_header_rows, page.width
                            )
                            self._is_parsing_table = True
                            is_collecting_header = False
                            possible_header_rows = []
                            continue

                    # ---------- DATA ROWS ----------
                    if self._is_parsing_table and self._columns:

                         # ✅ SKIP PAGE HEADERS INSIDE TABLE
                        if (
                            "DAILY CAUSE LIST FOR DATED" in upper_text
                            or "COURT NO" in upper_text
                        ):
                            continue
                        row = self.process_line(line_words)

                        if not any(row):
                            continue

                        self.extracted_rows.append(
                            row
                            + [
                                " | ".join(self._current_session["justices"]),
                                self._current_session["court_no"],  # ✅ ADDED
                                self._current_session["court"],
                                self._current_session["date"],
                                page_no                              # ✅ ADDED
                            ]
                        )

# ---------------- ENTRY POINT ---------------- #

if __name__ == "__main__":
    parser = SupremeCourtParser(FILE_PATH)
    parser.run()
    parser.merge_extracted_rows()

    date_str = parser.extracted_rows[0][7]

    parser.create_sqlite_tables_for_date(date_str, "cause_list.db")

    # ✅ PREVENT DUPLICATE RUNS
    parser.clear_tables_for_date(date_str, "cause_list.db")

    parser.insert_into_sqlite_for_date("cause_list.db")

    parser.export_to_csv("cause_list_results.csv")
