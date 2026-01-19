import pdfplumber
import re

# --- CONFIGURATION & CONSTANTS ---
FILE_PATH = "cause_list.pdf"
HEADER_GRAY = (0.8, 0.8, 0.8)
WHITE = (1.0, 1.0, 1.0)
HEADERS = ["SNO.", "CASE NO.", "Petitioner / Respondent", "Petitioner / Respondent ADVOCATE"]

class SupremeCourtParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self._is_parsing_table = False
        self._columns = []  # List of dicts: {name, x0, x1, top, bottom}
        self._current_session = {"date": None, "court": None, "justice": None}

    # --- PROPERTIES ---
    @property
    def session_info(self):
        """Returns the current metadata context (Justice, Date, Court)."""
        return self._current_session

    @property
    def column_definitions(self):
        """Returns the detected table column boundaries."""
        return self._columns

    # --- HELPER: COLOR & TEXT ---
    def normalize_color(self, color):
        """Standardizes PDF colors for consistent comparison."""
        if color is None: return WHITE
        if isinstance(color, (int, float)): color = (color,)
        return tuple(round(float(c), 1) for c in color)

    def get_bg_color(self, word, page):
        """Returns the background color at the word's position."""
        mid_x = (word['x0'] + word['x1']) / 2
        mid_y = (word['top'] + word['bottom']) / 2
        
        top_color = WHITE
        for r in page.rects:
            if (r['x0'] <= mid_x <= r['x1']) and (r['top'] <= mid_y <= r['bottom']):
                top_color = self.normalize_color(r.get('non_stroking_color'))
        return top_color

    def clean_text(self, text):
        """Standardizes whitespace and welds broken letter fragments."""
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'(?<=\b\w)\s(?=\w\b)', '', text)
        return text.strip()

    def _normalize_for_match(self, text):
        """Removes spaces and slashes for robust header matching."""
        return text.upper().replace(" ", "").replace("/", "")

    # --- CORE LOGIC: HEADER EXTRACTION ---
    def extract_header_definition(self, words_list):
        """
        Groups words into columns based on HEADERS array.
        Uses a 'Lock-in' mechanism: once a header is matched, those words 
        are skipped for subsequent searches.
        """
        # Flatten multi-row header words and sort by horizontal position (x0)
        all_words = [w for row in words_list for w in row]
        if not all_words: return []
        all_words.sort(key=lambda x: (x['x0'], x['top']))

        detected_cols = []
        word_idx = 0
        total_words = len(all_words)

        for target in HEADERS:
            clean_target = self._normalize_for_match(target)
            buffer = []
            found = False

            while word_idx < total_words:
                word = all_words[word_idx]
                buffer.append(word)
                
                combined = "".join([w['text'] for w in buffer])
                clean_combined = self._normalize_for_match(combined)

                if clean_combined == clean_target:
                    # MATCH: Define boundaries and lock these words
                    detected_cols.append({
                        "name": target,
                        "x0": min(w['x0'] for w in buffer),
                        "x1": max(w['x1'] for w in buffer)
                    })
                    word_idx += 1 
                    found = True
                    break
                elif clean_target.startswith(clean_combined):
                    # PARTIAL: Keep adding words in order
                    word_idx += 1
                else:
                    # NO MATCH: Backtrack if buffer was multi-word, or move on
                    if len(buffer) > 1:
                        word_idx = word_idx - (len(buffer) - 1)
                    else:
                        word_idx += 1
                    buffer = []

            if not found:
                print(f"  [!] Missing Header: {target}")

        return detected_cols

    # --- DATA PROCESSING ---
    def process_line(self, line_words):
        """Assigns words to columns based on geometric midpoints."""
        row_data = [""] * len(self._columns)
        
        for w in line_words:
            mid_x = (w['x0'] + w['x1']) / 2
            for i, col in enumerate(self._columns):
                # Use a small 2px tolerance for italics/kerning
                if (col['x0'] - 2) <= mid_x <= (col['x1'] + 2):
                    row_data[i] = (row_data[i] + " " + w['text']).strip()
                    break
        return row_data

    def update_metadata(self, text):
        """Parses the text for session context like Date or Justice names."""
        date_m = re.search(r"DATED\s*:\s*(\d{2}-\d{2}-\d{4})", text, re.I)
        if date_m: self._current_session["date"] = date_m.group(1)
        
        court_m = re.search(r"COURT\s*NO\.\s*:\s*(\d+)", text, re.I)
        if court_m: self._current_session["court"] = court_m.group(1)
        
        if "JUSTICE" in text.upper() and "HON'BLE" in text.upper():
            self._current_session["justice"] = self.clean_text(text)

    # --- MAIN RUNNER ---
    def run(self):
        possible_header_rows = []
        is_collecting_header = False

        with pdfplumber.open(self.file_path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=2, y_tolerance=2)
                
                # Group words into physical lines
                lines = {}
                for w in words:
                    lines.setdefault(round(w['top'], 1), []).append(w)
                
                for top in sorted(lines.keys()):
                    line_words = lines[top]
                    line_text = " ".join([w['text'] for w in line_words])

                    # 1. Update Context
                    self.update_metadata(line_text)

                    # 2. Exit Condition (End of Table)
                    if "NEW DELHI" in line_text.upper() and line_words[0]['x0'] < 100:
                        self._is_parsing_table = False
                        continue

                    # 3. Header Detection Logic
                    first_word_color = self.get_bg_color(line_words[0], page)
                    
                    if first_word_color == HEADER_GRAY:
                        is_collecting_header = True
                        possible_header_rows.append(line_words)
                        continue
                    elif is_collecting_header:
                        # Transition from Grey Header to White Data rows
                        self._columns = self.extract_header_definition(possible_header_rows)
                        self._is_parsing_table = True
                        is_collecting_header = False
                        possible_header_rows = [] # Reset for next potential table
                        print(f"\n[PAGE {page.page_number}] TABLE START")
                        continue

                    # 4. Data Extraction
                    if self._is_parsing_table and self._columns:
                        row = self.process_line(line_words)
                        if any(row):
                            label = "DATA ->" if row[0].isdigit() else "INFO ->"
                            print(f"{label} {row}")

if __name__ == "__main__":
    parser = SupremeCourtParser(FILE_PATH)
    parser.run()