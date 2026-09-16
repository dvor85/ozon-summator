from pathlib import Path
from typing import Annotated

from typer import Argument, Option

ROOT_PATH = Annotated[Path, Argument(help="Путь к папке с данными.")]
FORCE = Annotated[bool, Option("--force", help="Принудительное создание черновика. Очистка кэша.")]
