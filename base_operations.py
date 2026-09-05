import string
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment


class BaseOperations:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.package_units = self.path / "Грузоместа.xlsx"
        self.template_fn = "Шаблон поставки товаров.xlsx"

    @property
    def products_fn(self) -> Path | None:
        for f in self.path.glob("Товары*.xlsx"):
            return f
        return None

    def to_excel_with_format(self, df: pd.DataFrame, fn: Path, sheet_name: str, index: bool = False) -> None:
        with pd.ExcelWriter(fn) as writer:
            df.to_excel(writer, index=index, sheet_name=sheet_name)
            worksheet = writer.sheets[sheet_name]
            self.format(worksheet, df, index)

    @staticmethod
    def format(worksheet, df: pd.DataFrame, index: bool = False):
        left_align = Alignment(horizontal="left")
        excel_cols = string.ascii_uppercase
        if index:
            worksheet.column_dimensions["A"].width = 4
            worksheet.column_dimensions["A"].alignment = left_align
            excel_cols = excel_cols[1:]
        cols = dict(zip(df.columns, excel_cols, strict=False))

        for k, v in cols.items():
            if "артикул" in k.lower():
                worksheet.column_dimensions[v].width = 29
            elif "имя" in k.lower():
                worksheet.column_dimensions[v].width = 39
            elif "кол" in k.lower():
                worksheet.column_dimensions[v].width = 5
            elif "шк" in k.lower():
                worksheet.column_dimensions[v].width = 17
            else:
                worksheet.column_dimensions[v].width = 10
