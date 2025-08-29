import logging
import os
from datetime import datetime

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def get_daily_logger():
    now_str = datetime.now().strftime("%Y%m%d%H%M")
    log_filename = os.path.join(LOG_DIR, f"l{now_str}_info.log")
    loger = logging.getLogger("daily_info")
    loger.setLevel(logging.INFO)
    if not loger.handlers:
        handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        loger.addHandler(handler)

        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        loger.addHandler(console)
    return loger

logger = get_daily_logger()
