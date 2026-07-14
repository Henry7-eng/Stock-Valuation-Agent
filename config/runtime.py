from __future__ import annotations

import logging
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 运行态目录：默认落在用户 home，避免污染项目目录
DEFAULT_STATE_DIR = Path.home() / ".quantamental_runtime"
PLAYWRIGHT_USER_DATA_DIR = Path(os.getenv("PLAYWRIGHT_USER_DATA_DIR", DEFAULT_STATE_DIR / "pw_user_data"))
PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

DATA_HARVEST_DIR = PROJECT_ROOT / "01_Data_Harvest"
VIP_TXT_DUMPS_DIR = DATA_HARVEST_DIR / "VIP_Txt_Dumps"
VIP_TXT_DUMPS_DIR.mkdir(parents=True, exist_ok=True)

REPORT_DIR = PROJECT_ROOT / "03_Quant_Data" / "A_Share_Reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

BPC_PATH = Path(os.getenv("BPC_PATH", DATA_HARVEST_DIR / "bpc_extension"))

LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "365"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger
