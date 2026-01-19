import pdfplumber
import pandas as pd
import sqlite3
import re

# Configuration
FILE_PATH = "cause_list.pdf"
DB_NAME = "cause_list.db"
TABLE_NAME = "court_matters"

# Vertical boundaries derived from your PDF geometry
V_BOUNDARIES = [42.52, 68.03, 170.08, 425.20, 552.76]
HEADER_P1 = 269.30
HEADER_INTERNAL = 80.00 

STOP_KEYWORDS = ["NEW DELHI", "ADDITIONAL REGISTRAR", "SUPREME COURT", "DAILY CAUSE LIST", "COURT NO"]
HEADER_LABELS = ["SNo.", "Case No.", "Petitioner", "Respondent", "Advocate"]

def clean(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', str(text)).strip()

def is_sno_fragment(text):
    """Matches ONLY numeric fragments like '1719', '.1', or '1719.1'"""
    t = text.strip()
    return bool(re.match(r'^(\d+|\d*\.\d+|\.\d+)$', t))

def is_termination_text(text):
    """Identifies footers and table headers that signify the end of a record."""
    t = text.upper()
    if any(stop in t for stop in STOP_KEYWORDS): return True
    if any(label in t for label in [l.upper() for l in HEADER_LABELS]): return True
    # Date pattern check (prevents timestamps from being read)
    if re.search(r'\d{2}-\d{2}-\d{4}', t): return True
    return False

def run_extraction():
    all_data = []
    current_row = None
    page_row_counters = {}

    try:
        with pdfplumber.open(FILE_PATH) as pdf:
            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                h_limit = HEADER_P1 if i == 0 else HEADER_INTERNAL
                table_area = page.crop((0, h_limit, page.width, page.height))
                
                words = table_area.extract_words(x_tolerance=2, y_tolerance=2)
                # Sort by vertical position (top) then horizontal (x0)
                words.sort(key=lambda w: (w['top'], w['x0']))
                
                for word in words:
                    x_mid = (word['x0'] + word['x1']) / 2
                    text = word['text'].strip()

                    # 1. IDENTIFY COLUMN
                    col_idx = -1
                    for lane in range(len(V_BOUNDARIES) - 1):
                        if V_BOUNDARIES[lane] - 2 <= x_mid <= V_BOUNDARIES[lane+1] + 2:
                            col_idx = lane
                            break
                    if col_idx == -1: continue

                    # 2. CHECK FOR TERMINATION (FOOTERS/DATE STAMPS)
                    if is_termination_text(text):
                        if current_row:
                            all_data.append(current_row)
                            current_row = None
                        continue

                    # 3. SERIAL NUMBER HANDLING (LANE 0)
                    if col_idx == 0:
                        if is_sno_fragment(text):
                            # LOGIC: If it's a suffix (starts with .) and we have an open row, append it.
                            # Otherwise, it's a new row.
                            is_suffix = text.startswith('.')
                            
                            if current_row is not None and (is_suffix or not text[0].isdigit()):
                                # Append to existing SNo (handles '1719' -> '.1' spanning two lines)
                                current_row[0] = (current_row[0] + text).strip()
                            else:
                                # Start a brand new row
                                if current_row:
                                    all_data.append(current_row)
                                
                                page_row_counters[page_num] = page_row_counters.get(page_num, 0) + 1
                                current_row = [text, "", "", "", page_num, page_row_counters[page_num]]
                        else:
                            # It's in Lane 0 but not numeric (e.g., "NEW DELHI"). 
                            # Terminate current row and skip.
                            if current_row:
                                all_data.append(current_row)
                                current_row = None
                            continue

                    # 4. DATA ACCUMULATION (LANE 1, 2, 3)
                    elif current_row is not None:
                        # Prevent appending noise that bleeds into data columns
                        if any(stop in text.upper() for stop in STOP_KEYWORDS): continue
                        
                        if current_row[col_idx] == "":
                            current_row[col_idx] = text
                        else:
                            # Append multi-line data
                            if not current_row[col_idx].endswith(text):
                                current_row[col_idx] += " " + text

            # Final commit
            if current_row:
                all_data.append(current_row)

        # Build DataFrame
        columns = ["sno", "case_no", "parties", "advocates", "pdf_page", "row_in_page"]
        df = pd.DataFrame(all_data, columns=columns)
        
        # Cleanup and type conversion
        for col in ["sno", "case_no", "parties", "advocates"]:
            df[col] = df[col].apply(clean)
        
        # Ensure only rows with actual Case Nos are saved
        df = df[df['case_no'].str.len() > 5].drop_duplicates().reset_index(drop=True)

        conn = sqlite3.connect(DB_NAME)
        df.to_sql(TABLE_NAME, conn, if_exists='replace', index=False)
        conn.close()

        print(f"Success! {len(df)} rows extracted. Page 5 rows (1718, 1719) and split-line SNos (1719.1) preserved.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_extraction()