import sys
import warnings
from collections.abc import Generator
from pathlib import Path
import pandas as pd
from loguru import logger


def usage():
    logger.info(f"{Path(__file__).name} <root_dir>")
    sys.exit(1)


warnings.filterwarnings(
    "ignore", message="Workbook contains no default style, apply openpyxl's default"
)


class Summator:
    def __init__(self, path: Path, template: str):
        self.path = path
        self.template = template
        self.type = (
            "факт" if "import-package-units-template" in self.template else "план"
        )

    @property
    def columns(self) -> dict[str, str]:
        if self.type == "факт":
            return {
                "ШК товара": "string",
                "Артикул товара": "string",
                "Кол-во товаров": "Int64",
            }
        else:
            return {
                "артикул": "string",
                "имя (необязательно)": "string",
                "количество": "Int64",
            }

    def read_file(self, filename: Path) -> pd.DataFrame:
        df = pd.read_excel(filename, usecols="A,B,C").astype(self.columns)
        return df

    @staticmethod
    def format(worksheet):
        worksheet.column_dimensions["A"].width = 20
        worksheet.column_dimensions["B"].width = 50
        worksheet.column_dimensions["C"].width = 6

    def gen_group_version(self) -> None:
        dfs = self.read_dir()
        gen_file = self.path / f"Итог {self.type}.xlsx"
        try:
            sum_col = [k for k, v in self.columns.items() if v == "Int64"][0]
            result = (
                pd.concat(dfs, ignore_index=True)
                .groupby(
                    [k for k, v in self.columns.items() if v == "string"],
                    as_index=False,
                    sort=False,
                )[sum_col]
                .sum()
            ).query(f"`{sum_col}` > 0")
            with pd.ExcelWriter(gen_file) as writer:
                result.to_excel(
                    writer,
                    index=False,
                    sheet_name="Сводная",
                )
                worksheet = writer.sheets["Сводная"]
                self.format(worksheet)
        except Exception as e:
            logger.warning(f"Нет файлов сооветствующих шаблону '{self.template}': {e}")

    def read_dir(self) -> Generator[pd.DataFrame]:
        for f in self.path.rglob(self.template):
            yield self.read_file(f)


class PrintPakages:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def read_file(filename: Path) -> pd.DataFrame:
        df = pd.read_excel(filename, usecols="A,B,C,F").astype(
            {
                "ШК товара": "string",
                "Артикул товара": "string",
                "Кол-во товаров": "Int64",
                "ШК ГМ": "string",
            }
        )
        return df

    @staticmethod
    def format(worksheet):
        worksheet.column_dimensions["A"].width = 16
        worksheet.column_dimensions["B"].width = 35
        worksheet.column_dimensions["C"].width = 6
        worksheet.column_dimensions["D"].width = 18

    def gen_print_version_in_sheet(self) -> None:
        gen_file = self.path / "Грузоместа.xlsx"
        try:
            with pd.ExcelWriter(gen_file) as writer:
                startrow = 0
                for f in self.path.rglob("import-package-units-template*.xlsx"):
                    city = f.parent.name.capitalize()
                    try:
                        df = self.read_file(f)
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
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке города {city}: {e}")
        except Exception as e:
            logger.warning(
                f"Нет файлов сооветствующих шаблону 'import-package-units-template*.xlsx': {e}"
            )
            gen_file.unlink(missing_ok=True)

    def gen_print_version_by_sheets(self) -> None:
        with pd.ExcelWriter(self.path / "Грузоместа.xlsx") as writer:
            for f in self.path.rglob("import-package-units-template*.xlsx"):
                df = self.read_file(f)
                city = f.parent.name.capitalize()
                df.to_excel(writer, index=False, sheet_name=city)
                worksheet = writer.sheets[city]
                self.format(worksheet)


class PackageCollector:
    def __init__(self, path: Path):
        self.path = path
        self.package_units = self.path / "Грузоместа.xlsx"
        self.template_fn = "Шаблон поставки товаров.xlsx"

    @property
    def products_fn(self) -> Path | None:
        for f in self.path.glob("Товары*.xlsx"):
            return f
        return None

    @staticmethod
    def read_file(filename: Path) -> pd.DataFrame:
        df = pd.read_excel(filename).convert_dtypes()
        return df

    @staticmethod
    def format(worksheet):
        worksheet.column_dimensions["A"].width = 16
        worksheet.column_dimensions["B"].width = 35
        worksheet.column_dimensions["C"].width = 6
        worksheet.column_dimensions["D"].width = 18
        worksheet.column_dimensions["E"].width = 18
        worksheet.column_dimensions["F"].width = 18
        worksheet.column_dimensions["G"].width = 18

    def run(self) -> None:
        if not (self.products_fn and self.products_fn.exists()):
            logger.error(f"Отсутствует файл с товарами {self.products_fn}")
            return

        products_df = pd.read_excel(
            self.products_fn, usecols="A,D", skiprows=1
        ).convert_dtypes()
        products_df["Артикул"] = products_df["Артикул"].str.replace("'", "")

        for f in self.path.rglob("import-package-units-template*.xlsx"):
            city = f.parent.name.capitalize()
            logger.info(f"Обработка города {city}...")
            df = pd.read_excel(f).convert_dtypes()
            if df["Артикул товара"].isna().any():
                template_file = f.parent / self.template_fn
                if template_file.exists():
                    template_df = pd.read_excel(
                        f.parent / self.template_fn, usecols="A,C"
                    ).query("количество > 0")

                    collected_df = template_df.merge(
                        products_df, left_on="артикул", right_on="Артикул", how="inner"
                    )
                    df["ШК товара"] = collected_df["Barcode"]
                    df["Артикул товара"] = collected_df["артикул"]
                    df["Кол-во товаров"] = collected_df["количество"]
                    df = df.astype(
                        {
                            "ШК товара": "string",
                            "Артикул товара": "string",
                            "Кол-во товаров": "Int64",
                            "ШК ГМ": "string",
                        }
                    )
                    self.write(df, f)
                else:
                    logger.error(f"Отсутствует файл {template_file}")
            else:
                logger.warning(f"Файл {f} уже содержит данные, пропускаем...")

    def write(self, df: pd.DataFrame, fn: Path) -> None:
        sheet_name = "Состав ГМ поставки"
        with pd.ExcelWriter(fn) as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            worksheet = writer.sheets[sheet_name]
            self.format(worksheet)


if __name__ == "__main__":
    root_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if root_path is None:
        usage()

    collector = PackageCollector(root_path)
    collector.run()

    fact_summator = Summator(root_path, "import-package-units-template*.xlsx")
    fact_summator.gen_group_version()

    plan_summator = Summator(root_path, "Шаблон поставки товаров*.xlsx")
    plan_summator.gen_group_version()

    print_pakages = PrintPakages(root_path)
    print_pakages.gen_print_version_in_sheet()
