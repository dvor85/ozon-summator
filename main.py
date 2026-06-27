import string
import warnings
from argparse import ArgumentParser
from collections.abc import Generator
from pathlib import Path

import pandas as pd
from loguru import logger
from openpyxl.styles import Alignment

warnings.filterwarnings(
    "ignore", message="Workbook contains no default style, apply openpyxl's default"
)


def get_options():
    parser = ArgumentParser(
        prog="ozon",
        description="Подготовка поставок FBO ozon",
    )
    parser.add_argument(
        "root_path",
        help="""Путь к папке с данными. Например: 
        <Товары.xlsx> (Выгрузка товаров из озона), 
        москва -> 
            <Шаблон поставки товаров.xlsx> (подготовленный шаблон для загрузки товаров в озон), 
            [import-package-units-template.xlsx] (выгрузка состава поставки из озона)
        """,
    )
    parser.add_argument(
        "-t",
        "--template",
        help="Сгенерировать шаблон поставки товаров",
        action="store_true",
    )
    return parser.parse_args()


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

    def to_excel_with_format(
        self, df: pd.DataFrame, fn: Path, sheet_name: str, index: bool = False
    ) -> None:
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


class Summator(BaseOperations):
    def __init__(self, path: Path, template: str):
        super().__init__(path)
        self.template = template
        self.type = "факт" if "import-package-units-template" in self.template else "план"

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
        try:
            df = pd.read_excel(filename).astype(self.columns)
            return df[list(self.columns)]
        except Exception as e:
            logger.error(f"Ошибка чтения файла {filename}: {e}")
            raise

    def read_dir(self) -> Generator[pd.DataFrame]:
        for f in self.path.rglob(self.template):
            yield self.read_file(f)

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
            result = result.sort_values(by=sum_col, ascending=False)
            self.to_excel_with_format(result, gen_file, "Сводная")
            logger.success(f"{gen_file} успешно создан")
        except Exception as e:
            logger.warning(f"Нет файлов сооветствующих шаблону '{self.template}': {e}")


class PrintPakages(BaseOperations):
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

                        df.to_excel(writer, index=False, startrow=startrow, sheet_name="Сводная")
                        startrow += len(df) + 1
                        worksheet = writer.sheets["Сводная"]
                        self.format(worksheet, df)
                    except Exception as e:
                        logger.warning(f"Ошибка при обработке города {city}: {e}")
            logger.success(f"{gen_file} успешно создан")
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
                self.format(worksheet, df)


class PackageCollector(BaseOperations):
    def gen_template(self) -> None:
        logger.info(f"Генерация файла '{self.template_fn}'")
        if not (self.products_fn and self.products_fn.exists()):
            logger.error(f"Отсутствует файл с товарами '{self.products_fn}'")
            return

        df = pd.read_excel(self.products_fn, usecols="A,E", skiprows=1).convert_dtypes()
        df["Артикул"] = df["Артикул"].str.replace("'", "")
        df["количество"] = 0
        df = df.rename(
            columns={"Артикул": "артикул", "Название товара": "имя (необязательно)"}
        ).astype(
            {
                "артикул": "string",
                "имя (необязательно)": "string",
                "количество": "Int64",
            }
        )
        self.to_excel_with_format(df, self.path / self.template_fn, "Товарный состав", index=True)

    @staticmethod
    def read_file(filename: Path) -> pd.DataFrame:
        df = pd.read_excel(filename).convert_dtypes()
        return df

    def run(self) -> None:
        if not (self.products_fn and self.products_fn.exists()):
            logger.error(f"Отсутствует файл с товарами {self.products_fn}")
            return

        products_df = pd.read_excel(self.products_fn, usecols="A,D", skiprows=1).convert_dtypes()
        products_df["Артикул"] = products_df["Артикул"].str.replace("'", "")

        for f in self.path.rglob("import-package-units-template*.xlsx"):
            city = f.parent.name.capitalize()
            logger.info(f"Обработка города {city}...")
            df = pd.read_excel(f).convert_dtypes()
            if df["Артикул товара"].isna().any():
                template_file = f.parent / self.template_fn
                if template_file.exists():
                    template_df = pd.read_excel(f.parent / self.template_fn, usecols="A,C").query(
                        "количество > 0"
                    )

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
                    self.to_excel_with_format(df, f, "Состав ГМ поставки")
                else:
                    logger.error(f"Отсутствует файл {template_file}")
            else:
                logger.warning(f"Файл {f} уже содержит данные, пропускаем...")


if __name__ == "__main__":
    options = get_options()
    root_path = Path(options.root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")

    collector = PackageCollector(root_path)
    if options.template:
        collector.gen_template()
    else:
        collector.run()

        fact_summator = Summator(root_path, "import-package-units-template*.xlsx")
        fact_summator.gen_group_version()

        plan_summator = Summator(root_path, "Шаблон поставки товаров*.xlsx")
        plan_summator.gen_group_version()

        print_pakages = PrintPakages(root_path)
        print_pakages.gen_print_version_in_sheet()
