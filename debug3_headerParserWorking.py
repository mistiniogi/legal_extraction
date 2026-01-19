import pdfplumber
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict

# --- CONSTANTS ---
# Place your file path here
FILE_PATH = "cause_list.pdf"

# --- CONSTANTS ---
HEADER_GRAY_COLOR = "(0.8, 0.8, 0.8)"
LANE_SNO_MAX_X = 65
LANE_CASE_MAX_X = 180
LANE_PARTY_MAX_X = 400

@dataclass
class ColumnBoundary:
    name: str
    start_x: float
    end_x: float

@dataclass
class SessionContext:
    date: str = "Unknown"
    court_no: str = "Unknown"
    justice: str = "Unknown"

class CauselistParser:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.context = SessionContext()
        self.columns: Dict[int, ColumnBoundary] = {}
        
    def is_header_row(self, line_words: List[Dict], rects: List[Dict]) -> bool:
        """Determines if a line is a table header based on background color and text."""
        if not line_words: return False
        
        # Check background of the first word
        first_w = line_words[0]
        mid_x = (first_w['x0'] + first_w['x1']) / 2
        mid_y = (first_w['top'] + first_w['bottom']) / 2
        
        has_gray_bg = any(
            (r['x0'] <= mid_x <= r['x1']) and (r['top'] <= mid_y <= r['bottom']) 
            and str(r.get('non_stroking_color')) == HEADER_GRAY_COLOR 
            for r in rects
        )
        
        line_text = " ".join([w['text'] for w in line_words]).upper()
        return has_gray_bg and "SNO." in line_text

    def update_metadata(self, line_text: str):
        """Regex-based metadata extraction."""
        # Date Pattern
        date_match = re.search(r"DATED\s*:\s*(\d{2}-\d{2}-\d{4})", line_text, re.I)
        if date_match: self.context.date = date_match.group(1)

        # Court Pattern
        court_match = re.search(r"COURT\s*NO\.\s*:\s*(\d+)", line_text, re.I)
        if court_match: self.context.court_no = court_match.group(1)

        # Justice Pattern
        if "JUSTICE" in line_text.upper() and "HON'BLE" in line_text.upper():
            name = re.sub(r"(?i)HON'BLE\s*(MR\.|MS\.)?\s*JUSTICE\s*", "", line_text).strip()
            self.context.justice = name

    def learn_column_geometry(self, page, top_y: float):
        """Defines column boundaries dynamically from the header row."""
        # Capture the header zone (allowing for multi-line text like 'Advocate')
        header_bbox = (0, top_y - 5, page.width, top_y + 15)
        words = page.within_bbox(header_bbox).extract_words(y_tolerance=10)
        
        temp_lanes = {0: [], 1: [], 2: [], 3: []}
        for w in words:
            x = w['x0']
            if x < LANE_SNO_MAX_X: idx = 0
            elif x < LANE_CASE_MAX_X: idx = 1
            elif x < LANE_PARTY_MAX_X: idx = 2
            else: idx = 3
            temp_lanes[idx].append(w)

        for i, lane_words in temp_lanes.items():
            if lane_words:
                sorted_w = sorted(lane_words, key=lambda x: x['top'])
                name = " ".join([w['text'] for w in sorted_w])
                self.columns[i] = ColumnBoundary(
                    name=name,
                    start_x=min(w['x0'] for w in lane_words),
                    end_x=max(w['x1'] for w in lane_words)
                )

    def process_page(self, page):
        """Main page processing loop."""
        words = page.extract_words(x_tolerance=2, y_tolerance=2)
        rects = page.rects
        
        # Group into lines
        lines = {}
        for w in words:
            top = round(w['top'], 1)
            lines.setdefault(top, []).append(w)
        
        for top in sorted(lines.keys()):
            line_words = lines[top]
            line_text = " ".join([w['text'] for w in line_words])
            
            # Step 1: Metadata Check
            self.update_metadata(line_text)
            
            # Step 2: Header Check
            if self.is_header_row(line_words, rects):
                self.learn_column_geometry(page, top)
                self.print_summary(page.page_number)

    def print_summary(self, page_num: int):
        print(f"\n[Page {page_num}] SESSION: {self.context.date} | Court {self.context.court_no} | {self.context.justice}")
        print(f"{'ID':<10} | {'COL NAME':<35} | {'X-RANGE'}")
        print("-" * 70)
        for idx, col in self.columns.items():
            print(f"Col {idx+1:<7} | {col.name:<35} | {round(col.start_x,1)} - {round(col.end_x,1)}")

    def run(self):
        with pdfplumber.open(self.file_path) as pdf:
            for page in pdf.pages:
                self.process_page(page)

# --- EXECUTION ---
if __name__ == "__main__":
    parser = CauselistParser(FILE_PATH)
    parser.run()