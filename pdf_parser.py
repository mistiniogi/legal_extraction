# pdf_parser.py

import pdfplumber
import re
from config import HEADERS, HEADER_GRAY, WHITE, TABLE_END_X_TOLERANCE


class PDFTableParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self._is_parsing_table = False
        self._columns = []

        self._current_session = {
            "date": None,
            "court": None,
            "court_no": None,
            "justices": []
        }

        self.extracted_rows = []

    # ---------- helpers ----------

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

    # ---------- header extraction ----------

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

    # ---------- row processing ----------

    def process_line(self, line_words):
        row_data = [""] * len(self._columns)

        for w in line_words:
            for i, col in enumerate(self._columns):
                if col['x0'] <= w['x0'] <= col['x1']:
                    row_data[i] = (row_data[i] + " " + w['text']).strip()
                    break

        return row_data

    # ---------- main run ----------

    def run(self):
        with pdfplumber.open(self.file_path) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(x_tolerance=2)
                lines = {}

                for w in words:
                    lines.setdefault(round(w["top"], 1), []).append(w)

                possible_header_rows = []
                is_collecting_header = False

                for top in sorted(lines.keys()):
                    line_words = sorted(lines[top], key=lambda w: w['x0'])
                    line_text = " ".join(w["text"] for w in line_words)
                    upper_text = line_text.upper()

                    parse_metadata = not self._is_parsing_table

                    # table end
                    if (
                        self._is_parsing_table
                        and "NEW DELHI" in upper_text
                        and abs(line_words[0]['x0'] - self._columns[0]['x0']) <= TABLE_END_X_TOLERANCE
                    ):
                        self._is_parsing_table = False
                        self._columns = []
                        self._current_session = {
                            "date": None,
                            "court": "NEW DELHI",
                            "court_no": None,
                            "justices": []
                        }
                        continue

                    if parse_metadata:
                        if line_words[0]["text"].upper().startswith("HON"):
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

                    if self._is_parsing_table and self._columns:
                        if "DAILY CAUSE LIST FOR DATED" in upper_text or "COURT NO" in upper_text:
                            continue

                        row = self.process_line(line_words)
                        if not any(row):
                            continue

                        self.extracted_rows.append(
                            row + [
                                " | ".join(self._current_session["justices"]),
                                self._current_session["court_no"],
                                self._current_session["court"],
                                self._current_session["date"],
                                page_no
                            ]
                        )

        return self.extracted_rows
