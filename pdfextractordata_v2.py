import pdfplumber
import pandas as pd
import sqlite3
import re

# Configuration
FILE_PATH = "cause_list.pdf"
DB_NAME = "cause_list.db"
TABLE_NAME = "court_matters"

# Vertical boundaries
V_BOUNDARIES = [42.52, 68.03, 170.08, 425.20, 552.76]
HEADER_P1 = 269.30
HEADER_INTERNAL = 80.00 

STOP_KEYWORDS = ["NEW DELHI", "ADDITIONAL REGISTRAR", "SUPREME COURT", "DAILY CAUSE LIST", "COURT NO"]
HEADER_LABELS = ["SNo.", "Case No.", "Petitioner", "Respondent", "Advocate"]

def clean(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', str(text)).strip()

def is_sno_fragment(text):
    t = text.strip()
    return bool(re.match(r'^(\d+|\d*\.\d+|\.\d+)$', t))

def is_termination_text(text):
    t = text.upper()
    if any(stop in t for stop in STOP_KEYWORDS): return True
    if any(label in t for label in [l.upper() for l in HEADER_LABELS]): return True
    if re.search(r'\d{2}-\d{2}-\d{4}', t): return True
    return False

def run_extraction():
    all_data = []
    current_row = None
    page_row_counters = {}
    
    # NEW: State variable for category
    current_category = "GENERAL"

    try:
        with pdfplumber.open(FILE_PATH) as pdf:
            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                h_limit = HEADER_P1 if i == 0 else HEADER_INTERNAL
                table_area = page.crop((0, h_limit, page.width, page.height))
                
                words = table_area.extract_words(x_tolerance=2, y_tolerance=2)
                words.sort(key=lambda w: (w['top'], w['x0']))
                
                for word in words:
                    x_mid = (word['x0'] + word['x1']) / 2
                    text = word['text'].strip()

                    # --- STEP A: CHECK FOR CATEGORY HEADER ---
                    # If text looks like [FRESH...], update state and skip to next word
                    if text.startswith('[') and text.endswith(']') and ('CASES' in text.upper() or '-' in text):
                        current_category = text.strip('[] ')
                        # If a row was being built, finish it before the category shifts
                        if current_row:
                            all_data.append(current_row)
                            current_row = None
                        continue

                    # --- STEP B: IDENTIFY COLUMN ---
                    col_idx = -1
                    for lane in range(len(V_BOUNDARIES) - 1):
                        if V_BOUNDARIES[lane] - 2 <= x_mid <= V_BOUNDARIES[lane+1] + 2:
                            col_idx = lane
                            break
                    if col_idx == -1: continue

                    # --- STEP C: TERMINATION ---
                    if is_termination_text(text):
                        if current_row:
                            all_data.append(current_row)
                            current_row = None
                        continue

                    # --- STEP D: LANE 0 (SNo) ---
                    if col_idx == 0:
                        if is_sno_fragment(text):
                            is_suffix = text.startswith('.')
                            if current_row is not None and (is_suffix or not text[0].isdigit()):
                                current_row[0] = (current_row[0] + text).strip()
                            else:
                                if current_row:
                                    all_data.append(current_row)
                                
                                page_row_counters[page_num] = page_row_counters.get(page_num, 0) + 1
                                # Added current_category as the 7th element (index 6)
                                current_row = [text, "", "", "", page_num, page_row_counters[page_num], current_category]
                        else:
                            if current_row:
                                all_data.append(current_row)
                                current_row = None
                            continue

                    # --- STEP E: DATA LANES (1, 2, 3) ---
                    elif current_row is not None:
                        if any(stop in text.upper() for stop in STOP_KEYWORDS): continue
                        
                        if current_row[col_idx] == "":
                            current_row[col_idx] = text
                        else:
                            if not current_row[col_idx].endswith(text):
                                current_row[col_idx] += " " + text

            if current_row:
                all_data.append(current_row)

        # Build DataFrame - added "case_type"
        columns = ["sno", "case_no", "parties", "advocates", "pdf_page", "row_in_page", "case_type"]
        df = pd.DataFrame(all_data, columns=columns)
        
        for col in ["sno", "case_no", "parties", "advocates", "case_type"]:
            df[col] = df[col].apply(clean)
        
        df = df[df['case_no'].str.len() > 5].drop_duplicates().reset_index(drop=True)

        conn = sqlite3.connect(DB_NAME)
        df.to_sql(TABLE_NAME, conn, if_exists='replace', index=False)
        conn.close()

        print(f"Success! {len(df)} rows saved with category classification.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_extraction()