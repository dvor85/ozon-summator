import string
import warnings
from asyncio.log import logger
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment

warnings.filterwarnings("ignore", message="Workbook contains no default style, apply openpyxl's default")


class BaseOperations:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.package_units = self.path / "Грузоместа.xlsx"
        self.template_fn = "Шаблон поставки товаров.xlsx"

    @property
    def template_columns(self) -> dict[str, str]:
        return {
            "артикул": "string",
            "имя (необязательно)": "string",
            "количество": "Int64",
        }

    @property
    def product_columns(self) -> dict[str, str]:
        return {
            "Артикул": "string",
            "SKU": "string",
            "Штрихкод (Серийный номер / EAN)": "string",
        }

    @property
    def products_fn(self) -> Path | None:
        for f in self.path.glob("Товары*.xlsx"):
            return f
        return None

    def read_template_file(self, filename: Path) -> pd.DataFrame:
        try:
            df = pd.read_excel(filename).astype(self.template_columns)
            return df[list(self.template_columns)]
        except Exception as e:
            logger.error(f"Ошибка чтения файла {filename}: {e}")
            raise

    def read_product_file(self) -> pd.DataFrame:
        try:
            filename = self.products_fn
            df = pd.read_excel(filename, skiprows=1).astype(self.product_columns)
            return df[list(self.product_columns)]
        except Exception as e:
            logger.error(f"Ошибка чтения файла {filename}: {e}")
            raise

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
