# pipeline.py

import csv
from pdf_parser import PDFTableParser
from row_merger import RowMerger
from sqlite_repository import SQLiteCauseListRepository
from config import HEADERS


class CauseListPipeline:
    def __init__(self, pdf_path, db_path):
        self.pdf_path = pdf_path
        self.db_path = db_path

    def run(self):
        parser = PDFTableParser(self.pdf_path)
        rows = parser.run()

        rows = RowMerger().merge(rows)

        repo = SQLiteCauseListRepository(self.db_path)
        repo.prepare_tables(rows[0][7])
        repo.insert(rows)

        self.export_csv(rows)

    def export_csv(self, rows):
        with open("cause_list_results.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS + ["Judges", "Court No", "Court", "Date", "Page No"])
            writer.writerows(rows)
