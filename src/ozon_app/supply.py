import asyncio
from pathlib import Path

from cashews import cache
from loguru import logger
from typer import Typer, Abort

from core.config import get_settings
from ozon_app.ozon_operations import OzonSupplier
from ozon_app.ozon_seller import OzonApi
from ozon_app.used_types import ROOT_PATH, FORCE

settings = get_settings()


app = Typer()


async def _create(root_path: Path, force: bool = False):
    logger.info(f"Рабочая директория: {root_path}")
    if force:
        await cache.clear()

    async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
        supplier = OzonSupplier(root_path, ozon_api=ozon)
        await supplier.initialize()
        if supplier.draft_id:
            supplier.print_draft_info()
            await supplier.populate_timeslots()
            selected_date = supplier.select_timeslot_date()
            await asyncio.sleep(0)
            supplier.select_timeslot_time(selected_date=selected_date)
            await supplier.create_supply_by_draft()
            await supplier.get_order_id()
            await supplier.get_order_info()

        Abort("Черновик не найден, сначала создайте черновик!")


# async def _cargos(root_path: Path, force: bool = False):
#     root_path = Path(root_path).absolute()
#     logger.info(f"Рабочая директория: {root_path}")
#     if force:
#         await cache.clear()
#
#     async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
#         supplier = OzonSupplier(root_path, ozon_api=ozon)
#         await supplier.initialize()
#         if supplier.draft_id:
#             supplier.print_draft_info()
#             await supplier.get_order_info()
#             await supplier.set_cargos()
#
#         Abort("Черновик не найден, сначала создайте черновик!")


async def _order_info(root_path: Path, force: bool = False):
    logger.info(f"Рабочая директория: {root_path}")
    if force:
        await cache.clear()

    async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
        supplier = OzonSupplier(root_path, ozon_api=ozon)
        await supplier.initialize()
        if supplier.draft_id:
            supplier.print_draft_info()
            await supplier.get_order_id()

        Abort("Черновик не найден, сначала создайте черновик!")


@app.command()
def create(root_path: ROOT_PATH, force: FORCE = False):
    """Создать поставку по черновику из кэша"""
    root_path = Path(root_path).absolute()
    asyncio.run(_create(root_path=root_path, force=force))


@app.command()
def order_info(root_path: ROOT_PATH, force: FORCE = False):
    """Получить информацию о поставке по кэшу"""
    root_path = Path(root_path).absolute()
    asyncio.run(_order_info(root_path=root_path, force=force))


# @app.command()
# def cargos(root_path: ROOT_PATH, force: FORCE = False):
#     asyncio.run(_cargos(root_path=root_path, force=force))
