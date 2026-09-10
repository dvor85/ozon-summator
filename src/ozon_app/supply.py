import asyncio
from pathlib import Path
from typing import Annotated

from cashews import cache
from loguru import logger
from typer import Typer, Argument, Option, Abort

from core.config import get_settings
from ozon_app.ozon_operations import OzonSupplier
from ozon_app.ozon_seller import OzonApi

settings = get_settings()


app = Typer()


async def _create(
    root_path: Annotated[Path, Argument(help="Путь к папке с данными.")],
    force: Annotated[bool, Option("--force", help="Принудительное создание черновика.")] = False,
):
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")
    if force:
        await cache.clear()

    async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
        supplier = OzonSupplier(root_path, ozon_api=ozon)
        if draft_id := await cache.get("draft_id"):
            supplier.draft_info = await supplier.get_draft_info(draft_id)
            supplier.print_draft_info()
            await supplier.get_timeslots()
            supplier.select_timeslot_date()
            await supplier.create_supply_by_draft()
            # self.order_id = await self.get_order_info()

        Abort("Черновик не найден, сначала создайте черновик!")


@app.command()
def create(
    root_path: Annotated[Path, Argument(help="Путь к папке с данными.")],
    force: Annotated[bool, Option("--force", help="Принудительное создание черновика.")] = False,
):
    asyncio.run(_create(root_path=root_path, force=force))
