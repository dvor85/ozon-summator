from enum import StrEnum
from pathlib import Path
from typing import Generator

import pandas as pd
from loguru import logger
from typer import Typer

from core.config import get_settings
from ozon_app.base_operations import ExcelOperations
from ozon_app.used_types import ROOT_PATH

settings = get_settings()


app = Typer()


class ReportType(StrEnum):
    PLAN = "план"
    FACT = "факт"


class Summator(ExcelOperations):
    def __init__(self, path: Path, rep_type: ReportType):
        super().__init__(path)
        self.type = rep_type
        self.template = "*.".join(self.template_fn.rsplit(".", 2))
        if self.type == ReportType.FACT:
            self.template = self.cargos_template_fn

    @property
    def columns(self) -> dict[str, str]:
        if self.type == ReportType.FACT:
            return self.package_columns
        return self.template_columns

    def read_file(self, filename: Path) -> pd.DataFrame:
        if self.type == ReportType.FACT:
            return self.read_package_file(filename)
        return self.read_template_file(filename)

    def read_dir(self) -> Generator[pd.DataFrame]:
        for f in self.path.rglob(self.template):
            yield self.read_file(f)

    def run(self) -> None:
        dfs = self.read_dir()
        gen_file = self.path / f"Итог {self.type}.xlsx"
        try:
            sum_col = [k for k, v in self.columns.items() if v == "Int64"][0]
            group_cols = [col for col in self.columns if "артикул" in col.lower()]
            result = (
                pd.concat(dfs, ignore_index=True)
                .groupby(
                    group_cols,
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


class PrintPakages(ExcelOperations):
    def run(self) -> None:
        try:
            with pd.ExcelWriter(self.cargos_fn) as writer:
                startrow = 0
                for f in self.path.rglob(self.cargos_template_fn):
                    city = f.parent.name.capitalize()
                    try:
                        df = self.read_package_file(f)
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
            logger.success(f"{self.cargos_fn} успешно создан")
        except Exception as e:
            logger.warning(f"Нет файлов сооветствующих шаблону '{self.cargos_template_fn}': {e}")
            self.cargos_fn.unlink(missing_ok=True)


@app.command()
def plan(root_path: ROOT_PATH):
    """Суммарный отчет поставки по плану"""
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")
    summator = Summator(root_path, ReportType.PLAN)
    summator.run()


@app.command()
def fact(root_path: ROOT_PATH):
    """Суммарный отчет поставки по факту"""
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")
    summator = Summator(root_path, ReportType.FACT)
    summator.run()


@app.command()
def cargos(root_path: ROOT_PATH):
    """Суммарный отчет по грузоместам"""
    root_path = Path(root_path).absolute()
    logger.info(f"Рабочая директория: {root_path}")
    pp = PrintPakages(root_path)
    pp.run()
