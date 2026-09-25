import asyncio
from pathlib import Path

from cashews import cache
from typer import Typer, Abort, secho

from core.config import get_settings
from ozon_app.ozon_operations import OzonSupplier
from ozon_app.ozon_seller import OzonApi, OzonSellerError
from ozon_app.used_types import ROOT_PATH, FORCE

settings = get_settings()


app = Typer()


async def _create(root_path: Path, force: bool = False):
    if force:
        await cache.clear()

    async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
        try:
            supplier = OzonSupplier(root_path, ozon_api=ozon)
            await supplier.initialize()
            if draft_id := supplier.draft_id:
                secho(f"Черновик из кэша {draft_id}")
            else:
                secho("Черновик не найден, создаем новый...")
                await supplier.populate_all_clusters()
                await supplier.populate_warehouse()
                draft_id = await supplier.create_draft()
                secho(f"Создан новый черновик: {draft_id}", color=True, fg="green")

            await supplier.populate_draft_info()
            supplier.print_draft_info()
        except OzonSellerError as e:
            secho(e.message, color=True, bg="red")
            raise Abort from None


async def _warehouse(root_path: Path, force: bool = False):
    if force:
        await cache.clear()

    async with OzonApi(client_id=settings.ozon.client_id, api_key=settings.ozon.api_key) as ozon:
        try:
            supplier = OzonSupplier(root_path, ozon_api=ozon)
            await supplier.initialize()

            await supplier.populate_warehouse()

        except OzonSellerError as e:
            secho(e.message, color=True, bg="red")
            raise Abort from None


@app.command()
def create(root_path: ROOT_PATH, force: FORCE = False):
    """Создать черновик поставки"""
    root_path = Path(root_path).absolute()
    asyncio.run(_create(root_path=root_path, force=force))


@app.command()
def warehouse(root_path: ROOT_PATH, force: bool = False):
    """Найти склад отгрузки"""
    root_path = Path(root_path).absolute()
    asyncio.run(_warehouse(root_path=root_path, force=force))
