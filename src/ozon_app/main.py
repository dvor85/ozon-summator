import time
import warnings
from argparse import ArgumentParser
from collections import defaultdict
from collections.abc import Generator
from pathlib import Path
from typing import Annotated

import pandas as pd
from core.config import get_settings
from loguru import logger
from ozon_app.base_operations import BaseOperations
from ozon_app.ozon_seller import OzonApi, OzonSellerError
from rich import print
from rich.prompt import IntPrompt
from typer import Typer, Option

settings = get_settings()

warnings.filterwarnings("ignore", message="Workbook contains no default style, apply openpyxl's default")

app = Typer()


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
    parser.add_argument(
        "-d",
        "--draft-id",
        help="ID черновика поставки",
        type=int,
    )
    return parser.parse_args()


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


class OzonSupplier(BaseOperations):
    def __init__(self, path: Path, ozon_api: OzonApi):
        super().__init__(path)
        self.ozon = ozon_api
        self.supply_info: dict = {}
        self.all_clusters: list[dict] = []
        self.timeslots: list[dict] = []
        self.selected_timeslot: dict = {}
        self.draft_id: int = 0
        self.order_id: int = 0
        self.draft_info: dict = {}
        self.warehouses: list[dict] = []
        self.selected_warehouse_id: int = settings.ozon.warehouse_id

    def get_all_clusters(self):
        return self.ozon.get_clusters().get("result", [])

    def get_warehouses(self, search: str) -> list[dict]:
        return self.ozon.get_dbo_warehouses(search=search).get("search", [])

    def build_cargoes_payload(self, supply_ids: list[int]): ...

    def build_draft_payload(self) -> dict:
        clusters_info = defaultdict(list)
        result = {}
        if not (self.products_fn and self.products_fn.exists()):
            logger.error(f"Отсутствует файл с товарами {self.products_fn}")
            raise ValueError(f"Отсутствует файл с товарами {self.products_fn}")

        # products_df = pd.read_excel(self.products_fn, usecols="A,C", skiprows=1).convert_dtypes()
        products_df = self.read_product_file()
        products_df["Артикул"] = products_df["Артикул"].str.replace("'", "")

        for f in self.path.rglob(self.template_fn):
            try:
                template_df = self.read_template_file(f)
                template_df = template_df.query("количество > 0")
                if not template_df.empty:
                    merged_df = template_df.merge(products_df, left_on="артикул", right_on="Артикул", how="inner")
                    city = f.parent.name.lower()
                    logger.info(f"Обработка города {city}...")
                    for cluster in self.all_clusters:
                        if cluster_id := cluster.get("macrolocal_cluster_id"):
                            cluster_data = cluster["data"]
                            cluster_name = cluster_data["macrolocal_cluster"]["name"].lower()
                            if city in cluster_name:
                                logger.success(f"Кластер найден {cluster_name}: {cluster_id}")
                                for offer in merged_df.to_dict(orient="records"):
                                    clusters_info[cluster_id].append(
                                        {"quantity": offer["количество"], "sku": offer["SKU"]}
                                    )
            except Exception as e:
                logger.warning(e)

        result["clusters_info"] = [
            {"macrolocal_cluster_id": cluster_id, "items": items} for cluster_id, items in clusters_info.items()
        ]
        result["deletion_sku_mode"] = "PARTIAL"
        result["delivery_info"] = {
            "drop_off_warehouse": {
                "warehouse_id": self.selected_warehouse_id,
                "warehouse_type": "CROSS_DOCK",
            },
            "type": "DROPOFF",
        }
        return result

    def create_draft(self) -> int:
        draft_payload = self.build_draft_payload()
        if draft_payload["clusters_info"]:
            draft_res = self.ozon.draft_create(data=draft_payload)
            if errors := draft_res.get("errors", []):
                raise OzonSellerError(message=f"Ошибка при создании черновика: {errors}", code=draft_res.get("code"))

            logger.info(f"draft_id={draft_res.get('draft_id')}")
            return draft_res["draft_id"]
        raise OzonSellerError(message="Не заполнены кластеры для черновика")

    def get_timeslots(self) -> list[dict]:
        selected_clusters = self.draft_info["clusters"]
        timeslot_res = self.ozon.get_timeslots(selected_clusters=selected_clusters, draft_id=self.draft_id)
        if not timeslot_res["result"]:
            raise OzonSellerError(message=f"Ошибка получения слотов, errors={timeslot_res['error_reason']}")
        timeslots = timeslot_res["result"]["drop_off_warehouse_timeslots"]["days"]
        return sorted(timeslots, key=lambda x: x["date_in_timezone"])

    def select_timeslot_date(self) -> dict:
        if self.timeslots:
            for i, ts in enumerate(self.timeslots):
                print(f"{i}: {ts['date_in_timezone']}")
            try:
                if timeslot := IntPrompt.ask("Выберите дату (по умолчанию ближайшая)", default=0):
                    logger.success(f"Выбрана дата {self.timeslots[timeslot]['date_in_timezone']}")
                    return self.timeslots[timeslot]
            except Exception as e:
                timeslot = 0
                logger.warning(
                    f"Выбрана ближайшая дата {self.timeslots[timeslot]['date_in_timezone']} по умолчанию, {e}"
                )

            return self.timeslots[timeslot]
        raise OzonSellerError(message="Отсутствуют временные слоты")

    def get_draft_info(self, draft_id: int) -> dict:
        draft_info = self.ozon.get_draft_info(draft_id=draft_id)

        if draft_info["status"] != "SUCCESS":
            raise OzonSellerError(
                message=f"Проблема с черновиком {draft_id}, status={draft_info['status']} errors={draft_info['errors']}"
            )
        return draft_info

    def create_supply_by_draft(self):
        selected_clusters = self.draft_info["clusters"]
        result = self.ozon.supply_create_by_draft(
            selected_clusters=selected_clusters,
            draft_id=self.draft_id,
            timeslot=self.selected_timeslot,
        )
        if errors := result.get("error_reasons"):
            raise OzonSellerError(message=f"Проблема при создании поставки {self.draft_id}, errors={errors}")

        logger.success(f"Поставка из черновика {self.draft_id} создана")

    def get_order_info(self) -> int:
        result = self.ozon.get_order_info(self.draft_id)
        if errors := result.get("error_reasons"):
            raise OzonSellerError(message=f"Проблема при создании поставки {self.draft_id}, errors={errors}")

        order_id = result["order_id"]

        logger.success(f"Поставка из черновика {order_id} создана, status={result['status']}")
        return order_id

    def select_warehouse(self) -> int | None:
        for i, wh in enumerate(self.warehouses):
            print(f"{i}: {wh['name']} ({wh['address']})")

        try:
            if warehouse := IntPrompt.ask("Выберите склад", default=0):
                logger.success(f"Выбран склад {self.warehouses[warehouse]['name']}")
                return self.warehouses[warehouse]["warehouse_id"]
        except Exception as e:
            logger.warning(f"Выбран склад по умолчанию, {e}")

    def run(self, draft_id: int | None = None):
        if not draft_id:
            self.all_clusters = self.get_all_clusters()
            search = input("Введите город для поиска склада (по умолчанию 'димитровград'): ") or "димитровград"
            self.warehouses = self.get_warehouses(search=search)
            if selected_warehouse := self.select_warehouse():
                self.selected_warehouse_id = selected_warehouse

            self.draft_id = self.create_draft()
            time.sleep(5)
        else:
            self.draft_id = draft_id

        self.draft_info = self.get_draft_info(self.draft_id)
        self.timeslots = self.get_timeslots()
        self.selected_timeslot = self.select_timeslot_date()
        self.create_supply_by_draft()
        self.order_id = self.get_order_info()


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


@app.command()
def test():

    print("asdfasdfasdf")
    a = IntPrompt.ask(
        "select",
    )


@app.command()
def main(
    root_path: Path,
    template: Annotated[bool, Option(help="Генерировать шаблон")] = False,
    draft_id: Annotated[int | None, Option(help="Id черновика")] = None,
):
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")

    collector = PackageCollector(root_path)

    if template:
        collector.gen_template()
    elif draft_id:
        with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
            supplier = OzonSupplier(root_path, ozon_api=ozon)
            supplier.run(draft_id=draft_id)

    else:
        collector.run()

        fact_summator = Summator(root_path, "import-package-units-template*.xlsx")
        fact_summator.gen_group_version()

        plan_summator = Summator(root_path, "Шаблон поставки товаров*.xlsx")
        plan_summator.gen_group_version()

        print_pakages = PrintPakages(root_path)
        print_pakages.gen_print_version_in_sheet()
