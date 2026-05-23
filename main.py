import sys
from collections.abc import Generator
from pathlib import Path
import pandas as pd


class Summator:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def read_file(filename: Path) -> pd.DataFrame:
        df = pd.read_excel(filename, usecols="A,B,C,F").convert_dtypes()
        return df

    @staticmethod
    def format(worksheet):
        worksheet.column_dimensions["A"].width = 16
        worksheet.column_dimensions["B"].width = 35
        worksheet.column_dimensions["C"].width = 6

    def gen_group_version(self) -> None:
        dfs = self.read_dir()
        result = (
            pd.concat(dfs, ignore_index=True)
            .groupby(["ШК товара", "Артикул товара"], as_index=False, sort=False)[
                "Кол-во товаров"
            ]
            .sum()
        ).query("`Кол-во товаров` > 0")
        with pd.ExcelWriter(self.path / "Итог.xlsx") as writer:
            result.to_excel(
                writer,
                index=False,
                sheet_name="Сводная",
            )
            worksheet = writer.sheets["Сводная"]
            self.format(worksheet)

    def read_dir(self) -> Generator[pd.DataFrame]:
        for f in self.path.rglob("import-package-units-template*.xlsx"):
            yield self.read_file(f)


class PrintPakages:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def read_file(filename: Path) -> pd.DataFrame:
        df = pd.read_excel(filename, usecols="A,B,C,F").convert_dtypes()
        return df

    @staticmethod
    def format(worksheet):
        worksheet.column_dimensions["A"].width = 16
        worksheet.column_dimensions["B"].width = 35
        worksheet.column_dimensions["C"].width = 6
        worksheet.column_dimensions["D"].width = 18

    def gen_print_version_in_sheet(self) -> None:
        with pd.ExcelWriter(self.path / "Грузоместа.xlsx") as writer:
            startrow = 0
            for f in self.path.rglob("import-package-units-template*.xlsx"):
                df = self.read_file(f)
                city = f.parent.name
                # Пишем строку-разделитель (займёт всю ширину таблицы)
                sep_row = pd.DataFrame([[city] + [""] * (len(df.columns) - 1)])
                sep_row.to_excel(
                    writer,
                    sheet_name="Сводная",
                    startrow=startrow,
                    header=False,
                    index=False,
                )
                startrow += 1

                df.to_excel(
                    writer, index=False, startrow=startrow, sheet_name="Сводная"
                )
                startrow += len(df) + 1
                worksheet = writer.sheets["Сводная"]
                self.format(worksheet)

    def gen_print_version_by_sheets(self) -> None:
        with pd.ExcelWriter(self.path / "Грузоместа.xlsx") as writer:
            for f in self.path.rglob("import-package-units-template*.xlsx"):
                df = self.read_file(f)
                city = f.parent.name
                df.to_excel(writer, index=False, sheet_name=city)
                worksheet = writer.sheets[city]
                self.format(worksheet)


if __name__ == "__main__":
    root_path = sys.argv[1] if len(sys.argv) > 1 else None
    root_path = (
        Path(root_path) if root_path else Path.home() / "Документы/Ozon/Озон/2026-05-23"
    )
    summator = Summator(root_path)
    summator.gen_group_version()

    print_pakages = PrintPakages(root_path)
    print_pakages.gen_print_version_in_sheet()
