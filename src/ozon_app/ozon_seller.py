import datetime
from dataclasses import dataclass

import httpx


@dataclass
class OzonSellerError(Exception):
    message: str
    code: int | None = None


class OzonApi:
    def __init__(self, client_id: str, api_key: str):
        self.headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
        }
        self.session = httpx.AsyncClient(headers=self.headers)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.aclose()

    @staticmethod
    def _process_response(res: httpx.Response) -> dict:
        jdata = res.json()
        if res.status_code != 200:
            raise Exception(f"Error {jdata.get('code')}: {jdata.get('message')}")
        return jdata

    async def get_clusters(self):
        resp_stock = await self.session.post(url="https://api-seller.ozon.ru/v2/cluster/list")

        return self._process_response(resp_stock)

    async def draft_create(self, data: dict) -> dict:
        resp_stock = await self.session.post(
            url="https://api-seller.ozon.ru/v1/draft/multi-cluster/create",
            json=data,
        )

        return self._process_response(resp_stock)

    async def get_draft_info(self, draft_id: int) -> dict:
        data = {"draft_id": draft_id}
        resp_stock = await self.session.post(
            url="https://api-seller.ozon.ru/v2/draft/create/info",
            json=data,
        )

        return self._process_response(resp_stock)

    async def get_order_info(self, draft_id: int) -> dict:
        data = {"draft_id": draft_id}
        resp_stock = await self.session.post(
            url="https://api-seller.ozon.ru/v2/draft/supply/create/status",
            json=data,
        )

        return self._process_response(resp_stock)

    async def get_timeslots(self, selected_clusters: list[dict], draft_id: int) -> dict:
        date_from = datetime.date.today()
        date_to = date_from + datetime.timedelta(days=7)

        data = {
            "date_from": f"{date_from:%Y-%m-%d}",
            "date_to": f"{date_to:%Y-%m-%d}",
            "draft_id": draft_id,
            "supply_type": "MULTI_CLUSTER",
            "selected_cluster_warehouses": [
                {"macrolocal_cluster_id": cluster["macrolocal_cluster_id"]} for cluster in selected_clusters
            ],
        }

        resp_stock = await self.session.post(
            url="https://api-seller.ozon.ru/v2/draft/timeslot/info",
            json=data,
        )

        return self._process_response(resp_stock)

    async def supply_create_by_draft(self, selected_clusters: list[dict], draft_id: int, timeslot: dict) -> dict:
        last_time = timeslot["timeslots"][-1]
        date_from = last_time["from_in_timezone"]
        date_to = last_time["to_in_timezone"]

        data = {
            "draft_id": draft_id,
            "selected_cluster_warehouses": [
                {"macrolocal_cluster_id": cluster["macrolocal_cluster_id"]} for cluster in selected_clusters
            ],
            "timeslot": {"from_in_timezone": date_from, "to_in_timezone": date_to},
            "supply_type": "MULTI_CLUSTER",
        }
        resp_stock = await self.session.post(
            url="https://api-seller.ozon.ru/v2/draft/supply/create",
            json=data,
        )

        return self._process_response(resp_stock)

    async def get_dbo_warehouses(self, search: str) -> dict:
        data = {"filter_by_supply_type": ["CREATE_TYPE_CROSSDOCK"], "search": search}
        resp_stock = await self.session.post(
            url="https://api-seller.ozon.ru/v1/warehouse/fbo/list",
            json=data,
        )

        return self._process_response(resp_stock)
