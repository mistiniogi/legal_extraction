import pdfplumber
import re

FILE_PATH = "cause_list.pdf"

# The geometric lanes we verified via debugging
LANE_BOUNDARIES = [
    (40, 68, "SNo."),
    (68, 180, "Case No."),
    (180, 400, "Petitioner / Respondent"),
    (400, 600, "Petitioner / Respondent Advocate")
]

def interpret_header(words):
    """
    Groups words into the 4 logical columns based on their X-coordinates.
    """
    columns = {0: [], 1: [], 2: [], 3: []}
    
    for w in words:
        x = w['x0']
        # Assign word to lane based on X-coordinate
        for i, (start, end, label) in enumerate(LANE_BOUNDARIES):
            if start <= x < end:
                columns[i].append(w['text'])
                break
    
    # Join fragments (e.g., ['Petitioner', '/', 'Respondent'] -> 'Petitioner / Respondent')
    return [ " ".join(columns[i]) for i in range(4) ]

def scan_for_headers():
    print(f"--- Human-Style Header Detection Started ---")
    
    with pdfplumber.open(FILE_PATH) as pdf:
        for page in pdf.pages:
            page_num = page.page_number
            
            # We don't crop; we look at the whole page to find the 'Anchor'
            words = page.extract_words(x_tolerance=2, y_tolerance=2)
            
            # Group into lines
            lines = {}
            for w in words:
                top = round(w['top'], 1)
                lines.setdefault(top, []).append(w)
            
            sorted_tops = sorted(lines.keys())
            
            for i, top in enumerate(sorted_tops):
                line_text = " ".join([w['text'] for w in lines[top]]).upper()
                
                # DETECTION LOGIC: 
                # A table header is present if we see SNo and Case No on the same line
                if "SNO." in line_text and "CASE NO." in line_text:
                    
                    # 1. Define the Header Zone (Current line + the line immediately below for 'Advocate')
                    # We look ~10 points down to capture the 'Advocate' and shifted 'Petitioner' text
                    zone_bbox = (0, top - 2, page.width, top + 12)
                    header_words = page.within_bbox(zone_bbox).extract_words(y_tolerance=10)
                    
                    # 2. Interpret the 4 columns using our Lane Logic
                    interpreted_cols = interpret_header(header_words)
                    
                    # 3. Validation: Ensure we actually found a 4-column structure
                    if len(interpreted_cols[0]) > 0 and len(interpreted_cols[1]) > 0:
                        print(f"\n[!] TABLE HEADER DETECTED")
                        print(f"    Page Number: {page_num}")
                        print(f"    Y-Coordinate: {top}")
                        print(f"    Column 1: {interpreted_cols[0]}")
                        print(f"    Column 2: {interpreted_cols[1]}")
                        print(f"    Column 3: {interpreted_cols[2]}")
                        print(f"    Column 4: {interpreted_cols[3]}")
                        print("-" * 50)
                    
                    # Once a header is found on a page, we usually don't need to look for another
                    # on the same page (unless there are multiple distinct tables)
                    break 

if __name__ == "__main__":
    scan_for_headers()