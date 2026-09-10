import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any

from cashews import NOT_NONE, cache
from loguru import logger
from rich import print
from rich.prompt import IntPrompt, Prompt
from stamina import retry
from typer import secho

from core.config import get_settings
from ozon_app.base_operations import BaseOperations
from ozon_app.ozon_seller import OzonApi, OzonSellerError

settings = get_settings()


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

    @cache(ttl="1d", condition=NOT_NONE, key="all_clusters")
    async def populate_all_clusters(self) -> list[dict]:
        self.all_clusters = (await self.ozon.get_clusters()).get("result", [])
        return self.all_clusters

    @cache(ttl="1d", condition=NOT_NONE, key="warehouses:{search}")
    async def get_warehouses(self, search: str) -> list[dict]:
        return (await self.ozon.get_dbo_warehouses(search=search)).get("search", [])

    def build_cargoes_payload(self, supply_ids: list[int]): ...

    @cache(ttl="30m", condition=NOT_NONE, key="draft_payload")
    async def build_draft_payload(self) -> dict[str, Any]:
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

    @cache(ttl="30m", condition=NOT_NONE, key="draft_id")
    async def create_draft(self) -> int:
        """Создать черновик."""
        draft_payload = await self.build_draft_payload()
        if draft_payload["clusters_info"]:
            draft_res = await self.ozon.draft_create(data=draft_payload)
            if errors := draft_res.get("errors", []):
                raise OzonSellerError(message=f"Ошибка при создании черновика: {errors}", code=draft_res.get("code"))

            logger.info(f"draft_id={draft_res.get('draft_id')}")
            return draft_res["draft_id"]
        raise OzonSellerError(message="Не заполнены кластеры для черновика")

    async def get_timeslots(self) -> list[dict]:
        selected_clusters = self.draft_info["clusters"]
        timeslot_res = await self.ozon.get_timeslots(selected_clusters=selected_clusters, draft_id=self.draft_id)
        if not timeslot_res["result"]:
            raise OzonSellerError(message=f"Ошибка получения слотов, errors={timeslot_res['error_reason']}")
        timeslots = timeslot_res["result"]["drop_off_warehouse_timeslots"]["days"]
        self.timeslots = sorted(timeslots, key=lambda x: x["date_in_timezone"])
        return self.timeslots

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

            self.selected_timeslot = self.timeslots[timeslot]
            return self.selected_timeslot
        raise OzonSellerError(message="Отсутствуют временные слоты")

    @cache(ttl="30m", condition=NOT_NONE, key="draft_info:{draft_id}")
    @retry(attempts=2, wait_initial=5, on=(OzonSellerError,))
    async def get_draft_info(self, draft_id: int) -> dict:
        self.draft_id = draft_id
        draft_info = await self.ozon.get_draft_info(draft_id=draft_id)

        if draft_info["status"] != "SUCCESS":
            raise OzonSellerError(
                message=f"Проблема с черновиком {draft_id}, status={draft_info['status']} errors={draft_info['errors']}"
            )
        self.draft_info = draft_info
        return draft_info

    def print_draft_info(self):
        if self.draft_info:
            print("Информация о черновике:")
            for cluster in self.draft_info["clusters"]:
                state = cluster["warehouses"][0]["availability_status"]["state"]
                secho(
                    f"{cluster['cluster_name']}: {cluster['macrolocal_cluster_id']} - {state}",
                    color=True,
                    fg="green" if state == "FULL_AVAILABLE" else "red",
                )

    async def create_supply_by_draft(self):
        selected_clusters = self.draft_info["clusters"]
        result = await self.ozon.supply_create_by_draft(
            selected_clusters=selected_clusters,
            draft_id=self.draft_id,
            timeslot=self.selected_timeslot,
        )
        if errors := result.get("error_reasons"):
            raise OzonSellerError(message=f"Проблема при создании поставки {self.draft_id}, errors={errors}")

        logger.success(f"Поставка из черновика {self.draft_id} создана")

    async def get_order_info(self) -> int:
        result = await self.ozon.get_order_info(self.draft_id)
        if errors := result.get("error_reasons"):
            raise OzonSellerError(message=f"Проблема при создании поставки {self.draft_id}, errors={errors}")

        order_id = result["order_id"]

        logger.success(f"Поставка из черновика {order_id} создана, status={result['status']}")
        return order_id

    async def select_warehouse(self) -> int | None:
        for i, wh in enumerate(self.warehouses):
            print(f"{i}: {wh['name']} ({wh['address']})")

        try:
            if warehouse := IntPrompt.ask("Выберите склад", default=0):
                logger.success(f"Выбран склад {self.warehouses[warehouse]['name']}")
                return self.warehouses[warehouse]["warehouse_id"]
        except Exception as e:
            logger.warning(f"Выбран склад по умолчанию, {e}")

    @cache(ttl="30m", condition=NOT_NONE, key="warehouse")
    async def get_warehouse(self) -> int:
        search = Prompt.ask("Введите город для поиска склада", default="димитровград")
        self.warehouses = await self.get_warehouses(search=search)
        return await self.select_warehouse() or self.selected_warehouse_id

    async def run(self, draft_id: int | None = None):
        if not draft_id:
            self.all_clusters = await self.populate_all_clusters()
            self.selected_warehouse_id = await self.get_warehouse()

            self.draft_id = await self.create_draft()
            await asyncio.sleep(5)
        else:
            self.draft_id = draft_id

        self.draft_info = await self.get_draft_info(self.draft_id)
        self.timeslots = await self.get_timeslots()
        self.selected_timeslot = self.select_timeslot_date()
        await self.create_supply_by_draft()
        self.order_id = await self.get_order_info()
