# main.py

from config import FILE_PATH, DB_PATH
from pipeline import CauseListPipeline


if __name__ == "__main__":
    pipeline = CauseListPipeline(FILE_PATH, DB_PATH)
    pipeline.run()
