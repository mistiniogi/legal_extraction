# row_merger.py

from config import HEADERS


class RowMerger:
    def merge(self, rows):
        if not rows:
            return rows

        header_index = {name: i for i, name in enumerate(HEADERS)}
        sno_index = header_index["SNO."]

        merge_indices = {
            header_index["CASE NO."],
            header_index["Petitioner / Respondent"],
            header_index["Petitioner / Respondent ADVOCATE"],
        }

        metadata_start = len(HEADERS)
        validate_indices = {
            metadata_start,
            metadata_start + 1,
            metadata_start + 2,
            metadata_start + 3,
        }
        page_no_index = metadata_start + 4

        merged = []
        current = None

        for row in rows:
            raw_sno = row[sno_index].strip() if row[sno_index] else ""

            if raw_sno and not raw_sno.startswith("."):
                if current:
                    merged.append(current)
                current = row.copy()
                continue

            if raw_sno.startswith(".") and current:
                current[sno_index] += raw_sno
                continue

            if not current:
                continue

            for i, val in enumerate(row):
                if not val:
                    continue

                if i in merge_indices:
                    current[i] = (current[i] + " " + val).strip()
                elif i in validate_indices:
                    if not current[i]:
                        current[i] = val
                    elif current[i] != val:
                        raise ValueError("Metadata mismatch during merge")
                elif i == page_no_index:
                    cur = str(current[i])
                    if str(val) not in cur:
                        current[i] = f"{cur}, {val}"

        if current:
            merged.append(current)

        return merged
