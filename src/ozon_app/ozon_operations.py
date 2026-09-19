import asyncio
from collections import defaultdict
from itertools import batched
from pathlib import Path
from typing import Any

from cashews import NOT_NONE, cache
from loguru import logger
from rich.prompt import IntPrompt, Prompt
from stamina import retry
from typer import secho

from core.config import get_settings
from ozon_app.base_operations import ExcelOperations
from ozon_app.ozon_seller import OzonApi, OzonSellerError

settings = get_settings()


class OzonSupplier(ExcelOperations):
    def __init__(self, path: Path, ozon_api: OzonApi):
        super().__init__(path)
        self.ozon = ozon_api
        self.supply_info: dict = {}
        self.draft_payload: dict = {}
        self.all_clusters: list[dict] = []
        self.timeslots: list[dict] = []
        self.selected_timeslot: dict = {}
        self.draft_id: int = 0
        self.order_id: int = 0
        self.orders: list[dict] = []
        self.draft_info: dict = {}
        self.warehouses: list[dict] = []
        self.selected_warehouse_id: int = settings.ozon.warehouse_id

    async def initialize(self):
        self.all_clusters = await cache.get("all_clusters", [])
        self.selected_warehouse_id = await cache.get("warehouse", settings.ozon.warehouse_id)
        self.draft_id = await cache.get("draft_id", 0)
        self.order_id = await cache.get("order_id", 0)
        self.draft_info = await cache.get(f"draft_info:{self.draft_id}", {})
        self.draft_payload = await cache.get("draft_payload", {})
        self.orders = await cache.get("orders", [])

    @property
    def cluster_map(self) -> dict:
        result = {}
        for cluster in self.all_clusters:
            if cluster_id := cluster.get("macrolocal_cluster_id"):
                cluster_data = cluster["data"]
                cluster_name = cluster_data["macrolocal_cluster"]["name"]
                result[cluster_id] = cluster_name
        return result

    @cache(ttl="3d", condition=NOT_NONE, key="all_clusters")
    async def populate_all_clusters(self) -> list[dict]:
        self.all_clusters = (await self.ozon.get_clusters()).get("result", [])
        return self.all_clusters

    @cache(ttl="3d", condition=NOT_NONE, key="warehouses:{search}")
    async def get_warehouses(self, search: str) -> list[dict]:
        return (await self.ozon.get_dbo_warehouses(search=search)).get("search", [])

    def build_cargoes_payload(self, supply_ids: list[int]): ...

    @cache(ttl="3d", condition=NOT_NONE, key="draft_payload")
    async def build_draft_payload(self) -> dict[str, Any]:
        clusters_info = defaultdict(list)
        result = {}

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
                    for cluster in self.all_clusters:
                        if cluster_id := cluster.get("macrolocal_cluster_id"):
                            cluster_data = cluster["data"]
                            cluster_name = cluster_data["macrolocal_cluster"]["name"]
                            if city in cluster_name.lower():
                                logger.success(f"Кластер найден {cluster_name}: {cluster_id}")
                                for offer in offers:
                                    clusters_info[cluster_id].append(
                                        {
                                            "quantity": offer["количество"],
                                            "offer_id": offer["артикул"],
                                            "sku": offer["SKU"],
                                            "barcode": offer["Штрихкод (Серийный номер / EAN)"],
                                        }
                                    )
                                break
                    else:
                        logger.warning(f"Кластер для города {city} не найден!")
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
        self.draft_payload = result
        return result

    async def rename_articles(self, update_offers: list[dict]) -> list[dict]:
        results = []
        for offers in batched(update_offers, 25):
            data = {"update_offer_id": offers}
            results.append(await self.ozon.rename_articles(data=data))
            await asyncio.sleep(1)
        return results

    @cache(ttl="3d", condition=NOT_NONE, key="draft_id")
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

    async def populate_timeslots(self) -> list[dict]:
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
                secho(f"{i}: {ts['date_in_timezone']}", color=True, fg="cyan")
            try:
                timeslot = IntPrompt.ask("Выберите дату (по умолчанию ближайшая)", default=0)
                secho(f"Выбрана дата {self.timeslots[timeslot]['date_in_timezone']}", color=True, fg="green")
            except Exception as e:
                timeslot = 0
                secho(
                    f"Выбрана ближайшая дата {self.timeslots[timeslot]['date_in_timezone']} по умолчанию, {e}",
                    color=True,
                    fg="yellow",
                )

            return self.timeslots[timeslot]
        raise OzonSellerError(message="Отсутствуют временные слоты")

    def select_timeslot_time(self, selected_date: dict) -> dict:
        if selected_date:
            timeslots = selected_date["timeslots"]
            for i, ts in enumerate(timeslots):
                secho(f"{i}: {ts['from_in_timezone']} - {ts['to_in_timezone']}", color=True, fg="cyan")
            try:
                timeindex = IntPrompt.ask("Выберите время (по умолчанию последнее)", default=-1)
                secho(
                    f"Выбрано время {timeslots[timeindex]['from_in_timezone']} - {timeslots[timeindex]['to_in_timezone']}",
                    color=True,
                    fg="green",
                )
            except Exception as e:
                timeindex = -1
                secho(
                    f"Выбрано последнее время {timeslots[timeindex]['from_in_timezone']} - {timeslots[timeindex]['to_in_timezone']} по умолчанию, {e}",
                    color=True,
                    fg="yellow",
                )

            self.selected_timeslot = timeslots[timeindex]
            return self.selected_timeslot
        raise OzonSellerError(message="Отсутствуют временные слоты")

    @cache(ttl="3d", condition=NOT_NONE, key="draft_info")
    @retry(attempts=2, wait_initial=5, on=(OzonSellerError,))
    async def populate_draft_info(self) -> dict:
        draft_info = await self.ozon.get_draft_info(draft_id=self.draft_id)

        if draft_info["status"] != "SUCCESS":
            raise OzonSellerError(
                message=f"Проблема с черновиком {self.draft_id}, status={draft_info['status']} errors={draft_info['errors']}"
            )
        self.draft_info = draft_info
        return draft_info

    def print_draft_info(self):
        if self.draft_info:
            secho(f"Информация о черновике {self.draft_id}:", bold=True)
            for cluster in self.draft_info["clusters"]:
                state = cluster["warehouses"][0]["availability_status"]["state"]
                secho(
                    f"{cluster['cluster_name']}: {cluster['macrolocal_cluster_id']} - {state}",
                    color=True,
                    fg="green" if state == "FULL_AVAILABLE" else "yellow",
                )
        else:
            raise OzonSellerError("Информация о черновике отсутствует.")

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

    @cache(ttl="1d", condition=NOT_NONE, key="order_id")
    @retry(attempts=2, wait_initial=5, on=(OzonSellerError,))
    async def get_order_id(self) -> int:
        result = await self.ozon.get_order_id(self.draft_id)
        if errors := result.get("error_reasons"):
            raise OzonSellerError(message=f"Проблема при создании поставки {self.draft_id}, errors={errors}")

        if result["status"] != "SUCCESS":
            raise OzonSellerError(
                message=f"Проблема при получении ID заказа {self.draft_id}, status={result['status']}"
            )

        order_id = result["order_id"]

        logger.success(f"Поставка {order_id} из черновика {self.draft_id} создана, status={result['status']}")
        self.order_id = order_id
        return order_id

    @cache(ttl="1d", condition=NOT_NONE, key="orders")
    async def get_order_info(self) -> list[dict]:
        result = await self.ozon.get_order_info(self.order_id)
        self.orders = result["orders"]

        return self.orders

    async def set_cargos(self):
        cargoes = []
        orders = self.orders[0]
        for supply in orders["supplies"]:
            cluster_id = supply["macrolocal_cluster_id"]
            for cluster in self.draft_payload["cluster_info"]:
                value: dict = {"type": "BOX"}
                items: list[dict] = []
                if cluster_id == cluster["macrolocal_cluster_id"]:
                    for item in cluster["items"]:
                        items.append(
                            {
                                "offer_id": item["offer_id"],
                                "barcode": item["barcode"],
                                "quantity": item["quantity"],
                                "quant": 1,
                            }
                        )
                    value["items"] = items
                    cargoes.append(
                        {"key": f"{supply['created_date']}", "value": value, "supply_id": supply["supply_id"]}
                    )
                    break

        # "supply_id": order["supplies"]["supply_id"]

    async def select_warehouse(self) -> int | None:
        for i, wh in enumerate(self.warehouses):
            secho(f"{i}: {wh['name']} ({wh['address']})", color=True, fg="cyan")

        try:
            warehouse = IntPrompt.ask("Выберите склад", default=0)
            secho(f"Выбран склад {self.warehouses[warehouse]['name']}", color=True, fg="green")
            return self.warehouses[warehouse]["warehouse_id"]
        except Exception as e:
            secho(f"Выбран склад по умолчанию, {e}", color=True, fg="yellow")

    @cache(ttl="30m", condition=NOT_NONE, key="warehouse")
    async def populate_warehouse(self) -> int:
        search = Prompt.ask("Введите город для поиска склада", default="димитровград")
        self.warehouses = await self.get_warehouses(search=search)
        if selected_warehouse := await self.select_warehouse():
            self.selected_warehouse_id = selected_warehouse

        return self.selected_warehouse_id

    async def run(self, draft_id: int | None = None):
        if not draft_id:
            self.all_clusters = await self.populate_all_clusters()
            self.selected_warehouse_id = await self.populate_warehouse()

            self.draft_id = await self.create_draft()
            await asyncio.sleep(5)
        else:
            self.draft_id = draft_id

        self.draft_info = await self.populate_draft_info()
        self.timeslots = await self.populate_timeslots()
        self.selected_timeslot = self.select_timeslot_date()
        await self.create_supply_by_draft()
        self.order_id = await self.get_order_id()
