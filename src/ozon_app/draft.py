import asyncio
from pathlib import Path

from cashews import cache
from loguru import logger
from typer import Typer

from core.config import get_settings
from ozon_app.ozon_operations import OzonSupplier
from ozon_app.ozon_seller import OzonApi
from ozon_app.used_types import ROOT_PATH, FORCE

settings = get_settings()


app = Typer()


async def _create(root_path: Path, force: bool = False):
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")
    if force:
        await cache.clear()

    async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
        supplier = OzonSupplier(root_path, ozon_api=ozon)
        await supplier.initialize()
        if draft_id := supplier.draft_id:
            logger.info(f"Черновик из кэша {draft_id}")
        else:
            logger.info("Черновик не найден, создаем новый...")
            await supplier.populate_all_clusters()
            await supplier.populate_warehouse()
            draft_id = await supplier.create_draft()
            logger.info(f"Создан новый черновик: {draft_id}")

        await supplier.populate_draft_info(draft_id)
        supplier.print_draft_info()


@app.command()
def create(root_path: ROOT_PATH, force: FORCE = False):
    """Создать черновик поставки"""
    asyncio.run(_create(root_path=root_path, force=force))
