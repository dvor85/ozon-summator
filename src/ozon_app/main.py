import asyncio
from collections.abc import Generator
from pathlib import Path
from typing import Annotated

import pandas as pd
from loguru import logger
from typer import Typer, Option, Argument

from core.config import get_settings
from ozon_app import draft, supply
from ozon_app.base_operations import BaseOperations
from ozon_app.ozon_operations import OzonSupplier
from ozon_app.ozon_seller import OzonApi

settings = get_settings()


app = Typer()
app.add_typer(draft.app, name="draft")
app.add_typer(supply.app, name="supply")


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
            logger.warning(f"Нет файлов сооветствующих шаблону 'import-package-units-template*.xlsx': {e}")
            gen_file.unlink(missing_ok=True)


class PackageCollector(BaseOperations):
    def gen_template(self) -> None:
        logger.info(f"Генерация файла '{self.template_fn}'")
        if not (self.products_fn and self.products_fn.exists()):
            logger.error(f"Отсутствует файл с товарами '{self.products_fn}'")
            return

        df = pd.read_excel(self.products_fn, usecols="A,E", skiprows=1).convert_dtypes()
        df["Артикул"] = df["Артикул"].str.replace("'", "")
        df["количество"] = 0
        df = df.rename(columns={"Артикул": "артикул", "Название товара": "имя (необязательно)"}).astype(
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

        products_df = self.read_product_file()
        products_df["Артикул"] = products_df["Артикул"].str.replace("'", "")

        for f in self.path.rglob("import-package-units-template*.xlsx"):
            city = f.parent.name.capitalize()
            logger.info(f"Обработка города {city}...")
            df = pd.read_excel(f).convert_dtypes()
            if df["Артикул товара"].isna().any():
                template_file = f.parent / self.template_fn
                if template_file.exists():
                    template_df = self.read_template_file(f.parent / self.template_fn).query("количество > 0")

                    collected_df = template_df.merge(products_df, left_on="артикул", right_on="Артикул", how="inner")
                    df["ШК товара"] = collected_df["Штрихкод (Серийный номер / EAN)"]
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


async def _main(
    root_path: Annotated[Path, Argument(help="Путь к папке с данными.")],
    template: Annotated[bool, Option("--template", help="Генерировать шаблон")] = False,
    draft_id: Annotated[int | None, Option(help="Id черновика")] = None,
):
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")

    collector = PackageCollector(root_path)

    if template:
        collector.gen_template()
    elif draft_id:
        async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
            supplier = OzonSupplier(root_path, ozon_api=ozon)
            await supplier.run(draft_id=draft_id)

    else:
        collector.run()

        fact_summator = Summator(root_path, "import-package-units-template*.xlsx")
        fact_summator.gen_group_version()

        plan_summator = Summator(root_path, "Шаблон поставки товаров*.xlsx")
        plan_summator.gen_group_version()

        print_pakages = PrintPakages(root_path)
        print_pakages.gen_print_version_in_sheet()


@app.command()
def main(
    root_path: Annotated[Path, Argument(help="Путь к папке с данными.")],
    template: Annotated[bool, Option("--template", help="Генерировать шаблон")] = False,
    draft_id: Annotated[int | None, Option(help="Id черновика")] = None,
):
    asyncio.run(_main(root_path=root_path, template=template, draft_id=draft_id))


if __name__ == "__main__":
    app()
