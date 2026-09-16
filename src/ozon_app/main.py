import asyncio
from itertools import chain
from pathlib import Path

import pandas as pd
from loguru import logger
from rich import print
from typer import Typer

from core.config import get_settings
from ozon_app import draft, supply, report
from ozon_app.base_operations import BaseOperations
from ozon_app.ozon_operations import OzonSupplier
from ozon_app.ozon_seller import OzonApi
from ozon_app.used_types import ROOT_PATH

settings = get_settings()


app = Typer()
app.add_typer(draft.app, name="draft")
app.add_typer(supply.app, name="supply")
app.add_typer(report.app, name="report")


class TemplateGenerator(BaseOperations):
    def run(self) -> None:
        logger.info(f"Генерация файла '{self.template_fn}'")

        df = self.read_product_file()
        df["Артикул"] = df["Артикул"].str.replace("'", "")
        df["количество"] = 0
        df = df.rename(columns={"Артикул": "артикул", "Название товара": "имя (необязательно)"}).astype(
            {
                "артикул": "string",
                "имя (необязательно)": "string",
                "количество": "Int64",
            }
        )
        self.to_excel_with_format(df, self.path / self.template_fn, "Товарный состав", index=False)


class PackageCollector(BaseOperations):
    def get_items_in_clusters(self, all_clusters: list[dict]) -> list[dict]:
        result = []

        products_df = self.read_product_file()
        products_df["Артикул"] = products_df["Артикул"].str.replace("'", "")

        for f in self.path.rglob(self.template_fn):
            try:
                template_df = self.read_template_file(f)
                template_df = template_df.query("количество > 0")
                if not template_df.empty:
                    merged_df = template_df.merge(products_df, left_on="артикул", right_on="Артикул", how="inner")
                    offers = merged_df.to_dict(orient="records")
                    city = f.parent.name.lower()
                    logger.info(f"Обработка города {city}...")
                    for cluster in all_clusters:
                        if cluster_id := cluster.get("macrolocal_cluster_id"):
                            cluster_data = cluster["data"]
                            cluster_name = cluster_data["macrolocal_cluster"]["name"]
                            if city in cluster_name.lower():
                                logger.success(f"Кластер найден {cluster_name}: {cluster_id}")
                                items = [
                                    {
                                        "quantity": offer["количество"],
                                        "offer_id": offer["артикул"],
                                        "sku": offer["SKU"],
                                        "barcode": offer["Штрихкод (Серийный номер / EAN)"],
                                    }
                                    for offer in offers
                                ]
                                result.append({"cluster_id": cluster_id, "cluster_name": cluster_name, "items": items})
                                break
                    else:
                        logger.warning(f"Кластер для города {city} не найден!")
            except Exception as e:
                logger.warning(e)

        return result

    def run(self) -> None:
        products_df = self.read_product_file()
        products_df["Артикул"] = products_df["Артикул"].str.replace("'", "")

        for f in self.path.rglob(self.cargos_template_fn):
            city = f.parent.name.capitalize()
            logger.info(f"Обработка города {city}...")
            df = pd.read_excel(f).astype(self.package_columns)
            if df["Артикул товара"].isna().any():
                template_file = f.parent / self.template_fn
                if template_file.exists():
                    template_df = self.read_template_file(f.parent / self.template_fn).query("количество > 0")

                    collected_df = template_df.merge(products_df, left_on="артикул", right_on="Артикул", how="inner")
                    df["ШК товара"] = collected_df["Штрихкод (Серийный номер / EAN)"]
                    df["Артикул товара"] = collected_df["артикул"]
                    df["Кол-во товаров"] = collected_df["количество"]
                    df = df.astype(self.package_columns)
                    self.to_excel_with_format(df, f, "Состав ГМ поставки")
                else:
                    logger.error(f"Отсутствует файл {template_file}")
            else:
                logger.warning(f"Файл {f} уже содержит данные, пропускаем...")


async def _rename(root_path: Path):
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")
    async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
        supplier = OzonSupplier(root_path, ozon_api=ozon)
        await supplier.initialize()

        template_fn = root_path / supplier.template_fn
        df = pd.read_excel(template_fn).convert_dtypes()
        payload = []
        for row in df.itertuples():
            payload.append({"offer_id": row[2], "new_offer_id": f"{row[1]}_{row[2]}"})

        res = await supplier.rename_articles(payload)
        errors = list(chain(r["errors"] for r in res))
        print(errors)


@app.command()
def rename(root_path: ROOT_PATH):
    """Переименование артикулов"""
    asyncio.run(_rename(root_path))


@app.command()
def template(root_path: ROOT_PATH):
    """Генерировать шаблон"""
    collector = TemplateGenerator(root_path)
    collector.run()


@app.command()
def cargos(root_path: ROOT_PATH):
    """Заполнение грузомест в эксель файлах import-package-units-template*.xlsx"""
    collector = PackageCollector(root_path)
    collector.run()


# async def _main(root_path: Path, draft_id: int | None = None):
#     root_path = Path(root_path).absolute()
#     logger.info(f"Рабочая директория: {root_path}")
#
#     collector = PackageCollector(root_path)
#
#     if draft_id:
#         async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
#             supplier = OzonSupplier(root_path, ozon_api=ozon)
#             await supplier.initialize()
#
#             # await supplier.run(draft_id=draft_id)
#
#     else:
#         collector.run()
#
#         print_pakages = PrintPakages(root_path)
#         print_pakages.gen_print_version_in_sheet()


# @app.command()
# def main(
#     root_path: ROOT_PATH,
#     draft_id: Annotated[int | None, Option(help="Id черновика")] = None,
# ):
#     asyncio.run(_main(root_path=root_path, draft_id=draft_id))


if __name__ == "__main__":
    app()
