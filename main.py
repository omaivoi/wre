import ast
import json
import logging

import cloudscraper
import dotenv
import os
import requests
import shutil
import time
import io
import numpy as np
from PIL import Image, ImageChops
from apscheduler.schedulers.background import BackgroundScheduler
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from fake_useragent import UserAgent


def env_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes", "on")

# env文件
config = dotenv.dotenv_values(".env")
WPLACER_URL = f'http://{config["WPLACER_HOST"]}:{config["WPLACER_PORT"]}' if config.get("WPLACER_PORT") else f'http://{config["WPLACER_HOST"]}'
MONITOR_AREA=ast.literal_eval(config.get("MONITOR_AREA", "[]"))
BACKUP=env_bool(config.get("BACKUP", True))
BACKUP_SCHEDULE= config.get("BACKUP_SCHEDULE", "* /30 * * * *")
BLACK_LIST=ast.literal_eval(config.get("BLACK_LIST", "[]"))
BLACK_ALLIANCENAME_LIST=ast.literal_eval(config.get("BLACK_ALLIANCENAME_LIST", "[]"))
BACKUP_BLACKED=env_bool(config.get("BACKUP_BLACKED",True))
ONLY_OVERLAY=env_bool(config.get("ONLY_OVERLAY",False))
LOOP_SLEEP=int(config["LOOP_SLEEP"])
LOOP_SLEEP_SHORT=int(config["LOOP_SLEEP_SHORT"])
MAX_GETPOKEAUTHOR_THREAD=int(config["MAX_GETPOKEAUTHOR_THREAD"])
HTTP_PROXY = config.get("HTTP_PROXY")
HTTPS_PROXY = config.get("HTTPS_PROXY")

# 请求配置
if HTTP_PROXY and HTTPS_PROXY:
    proxies = {
        "http": HTTP_PROXY,
        "https": HTTPS_PROXY
    }
else:
    proxies = None
USERAGENT=UserAgent()
UA=USERAGENT.edge
MAX_RETRIES=999999 # 最大重试次数
DELAY=1 # 每个请求和重试间延迟，单位秒

# 目录配置
MODEL_DIR="model" # 模板目录
COMPARISON_DIR=os.path.join(MODEL_DIR, 'comparison') # 比较目录
BACKUP_DIR="backup" # 备份目录
BACKUP_BLACKED_DIR=os.path.join(BACKUP_DIR, 'black') # 黑名单涂鸦备份
LOG_DIR="logs" # 日志目录
LOG_FILE = os.path.join(LOG_DIR, "info.log") # 日志文件

# 创建目录
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(COMPARISON_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(BACKUP_BLACKED_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# 杂项
FILE_EXTENSION=".png"
SCRAPER = cloudscraper.create_scraper()
def get_daily_logger():
    now_str = datetime.now().strftime("%Y%m%d%H%M")
    log_filename = os.path.join(LOG_DIR, f"l{now_str}_info.log") # 每天一个日志文件

    logger = logging.getLogger("daily_info")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # 控制台输出（可选）
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        logger.addHandler(console)

    return logger

logger = get_daily_logger()
"""
# 地区涂鸦下载
"""
def clone_area(left, top, right, bottom, max_retries=MAX_RETRIES, delay=DELAY, save_dir=MODEL_DIR):
    for x in range(left, right + 1):
        for y in range(top, bottom + 1):
            retries = 0
            while retries < max_retries:
                try:
                    response = requests.get(f'https://backend.wplace.live/files/s0/tiles/{x}/{y}.png', proxies=proxies, headers={"User-Agent": UA, "Accept": "image/webp,*/*", "Referer": "https://www.wplace.live/"}, timeout=10)
                    if response.status_code == 200:
                        with open(f"{save_dir}{os.path.sep}{x}_{y}{FILE_EXTENSION}", "wb") as f:
                            f.write(response.content)
                        print(f'[OK] ({x},{y}) 下载成功')
                        break
                    elif response.status_code == 404:
                        print(f'[INFO] ({x},{y}) 图块不存在，跳过')
                        break
                    else:
                        retries += 1
                        logger.info(f'[WARN] ({x},{y}) 状态码 {response.status_code}，重试第 {retries} 次')
                except requests.exceptions.RequestException as e:
                    retries += 1
                    logger.info(f'[ERROR] ({x},{y}) 请求失败: {e}，重试第 {retries} 次')
                time.sleep(delay)


"""
# 地区涂鸦备份
"""
def backup_area(left, top, right, bottom, max_retries=MAX_RETRIES, delay=DELAY, backup_dir=BACKUP_DIR):
    logger.info(f'[INFO] 开始备份, 备份区域: left={left}, top={top}, right={right}, bottom={bottom}')
    backup_folder = f'{backup_dir}{os.path.sep}{time.strftime("%Y%m%d%H%M")}_backup'
    os.makedirs(backup_folder, exist_ok=True)
    clone_area(left=left, top=top, right=right, bottom=bottom, max_retries=max_retries, delay=delay, save_dir=backup_folder)
def backup_job():
    for area in MONITOR_AREA:
        MONITOR_LEFT, MONITOR_TOP, MONITOR_RIGHT, MONITOR_BOTTOM = area[0], area[1], area[2], area[3]
        backup_area(left=MONITOR_LEFT, top=MONITOR_TOP, right=MONITOR_RIGHT, bottom=MONITOR_BOTTOM)
    logger.info('[INFO] 备份完成')

"""
# 获取点作者
返回: None / {id: 123, name: "321"}
"""
def poke_author(TlX, TlY, PxX, PxY, retries=MAX_RETRIES, delay=DELAY):
    err_delay=delay
    retrie = 0
    while retrie < retries:
        try:
            response = SCRAPER.get(f'https://backend.wplace.live/s0/pixel/{TlX}/{TlY}?x={PxX}&y={PxY}', proxies=proxies, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("paintedBy").get("id") != "":
                    logger.info(f'[OK] TlX: {TlX}, TlY: {TlY}, PxX: {PxX}, PxY: {PxY}, 获取点作者成功: {data["paintedBy"]}')
                    # logger.recode
                    return data["paintedBy"]
                else:
                    logger.info('[INFO] TlX: {TlX}, TlY: {TlY}, PxX: {PxX}, PxY: {PxY}, 该像素无作者信息')
                    return None
            else:
                retrie += 1
                err_delay += 1
                logger.info(f'[WARN] 状态码 {response.status_code}, 重试第 {retrie} 次')
                time.sleep(err_delay)
            time.sleep(delay)
        except Exception as e:
            logger.info(e)
            time.sleep(err_delay)
            err_delay *= 2
            continue
    return None


"""
像素比较器
参数: modelImg_path: 底图
       comparImg_path: 新图
返回: None: 图片无效
        0: 图片相同
        [空]: ONLY_OVERLAY为true,存在用户画了图,但是没修改别人的画
        [[],[],[]]: 具体不相同的像素点
"""


# diff = ImageChops.difference(img1, img2) # 这种比对方式有概率忽略像素点
# diff_pixels = []
# width, height = diff.size
# img1_data = img1.getdata()
# diff_data = diff.getdata()
#
# for y in range(height):
#     for x in range(width):
#         r, g, b, a = diff_data[y * width + x]
#         if (r, g, b, a) != (0, 0, 0, 0):
#             origin_a = img1_data[y * width + x][3]
#             if not ONLY_OVERLAY or origin_a > 0:
#                 diff_pixels.append((x, y, img1_data[y * width + x]))
#
# return diff_pixels
def pixel_comparator(modelImg_path, comparImg_path):
    if (not os.path.exists(modelImg_path)) or (not os.path.exists(comparImg_path)):
        return None

    # 某种神奇的缓存机制总是读到旧版图片, io确保读到的图片一定是最新的
    with open(modelImg_path, "rb") as f:
        img1 = Image.open(io.BytesIO(f.read())).convert("RGBA").copy()
        img1np = np.array(img1)
    with open(comparImg_path, "rb") as f:
        img2 = Image.open(io.BytesIO(f.read())).convert("RGBA").copy()
        img2np = np.array(img2)

    if img1np.shape != img2np.shape:
        return None

    # 找出不同像素的布尔掩码：在任意 RGBA 通道不同的像素
    diff_mask = np.any(img1np != img2np, axis=-1)

    # 如果图片完全相同，返回 0
    if not np.any(diff_mask):
        return 0

    if ONLY_OVERLAY:
        # 只比较原图非透明的像素
        overlay_mask = img1np[..., 3] > 0
        final_mask = diff_mask & overlay_mask
    else:
        final_mask = diff_mask

    # 获取所有不同的像素坐标 (y, x)
    diff_coordinates = np.argwhere(final_mask)

    # 提取像素信息
    diff_pixels = [(x, y, tuple(img1np[y, x])) for y, x in diff_coordinates]

    return diff_pixels


"""
# 区域变更处理器
返回: True: 需要恢复像素, False: 不需要恢复像素
"""
def map_check(left, top, right, bottom, max_retries=MAX_RETRIES, delay=DELAY, model_dir=MODEL_DIR, comparison_dir=COMPARISON_DIR):
    changes_flag = False
    # 克隆对比图
    clone_area(left=left, top=top, right=right, bottom=bottom, max_retries=max_retries, delay=delay, save_dir=COMPARISON_DIR)
    # 遍历比较每一张图
    for _, _, compfiles in os.walk(COMPARISON_DIR):
        for comp_item in compfiles:
            model_path = os.path.join(model_dir, comp_item)
            comparison_path = os.path.join(comparison_dir, comp_item)
            if not os.path.exists(model_path):
                shutil.copy(comparison_path, model_path)
                continue
            diff_pixels = pixel_comparator(model_path, comparison_path)
            if diff_pixels is None or diff_pixels == 0 or diff_pixels == []:
                logger.info(f'{comp_item} 不需恢复, 因为 {"图片无效" if diff_pixels is None else "图片相同" if diff_pixels == 0 else "ONLY_OVERLAY为true,存在用户画了图,但是没修改别人的画"}')
                continue
            logger.info(f'[INFO] {comp_item} 发现 {len(diff_pixels)} 个不同像素')
            Tl = comp_item[:-len(FILE_EXTENSION)].split("_")
            # 用io避免读到缓存图片
            with open(model_path, "rb") as f:
                model_img = Image.open(io.BytesIO(f.read())).convert("RGBA").copy()
            with open(comparison_path, "rb") as f:
                comparison_img = Image.open(io.BytesIO(f.read())).convert("RGBA").copy()
            model_img_data = model_img.getdata()
            model_img_width, model_img_height = model_img.size

            # 固化成列表，避免生成器被消费
            diff_pixels = list(diff_pixels)
            color_adjust = []

            with ThreadPoolExecutor(max_workers=MAX_GETPOKEAUTHOR_THREAD) as executor:
                results_iter = executor.map(
                    lambda Px: poke_author(Tl[0], Tl[1], Px[0], Px[1]),
                    diff_pixels
                )

                for Px, author in zip(diff_pixels, results_iter):
                    if author is not None and (str(author["id"]) in BLACK_LIST or str(author["allianceName"]) in BLACK_ALLIANCENAME_LIST):
                        changes_flag = True
                        color_origin = model_img_data[Px[1]*model_img_width+Px[0]]
                        logger.info(f'[INFO] [!] 发现黑名单用户 {author["name"]}#{author["id"]} 修改 [{Tl[0]} {Tl[1]} {Px[0]} {Px[1]}], 图片原颜色: {color_origin}')
                        color_adjust.append(((int(Tl[0]), int(Tl[1]), int(Px[0]), int(Px[1])), color_origin))
                        # 设置颜色, 把comparison_img_data对应位置颜色改成color_origin
                        comparison_img.putpixel((Px[0],Px[1]), color_origin)

            if color_adjust:
                if BACKUP_BLACKED:
                    shutil.copy(comparison_path, BACKUP_BLACKED_DIR+os.path.sep+time.strftime("%Y%m%d%H%M")+"_"+comp_item)
                taskBody = {
                    "taskname": f'WRE_{time.strftime("%Y%m%d%H%M")}_{Tl[0]}x{Tl[1]}',
                    "mark": [{"TlX": item[0][0], "TlY": item[0][1], "PxX": item[0][2], "PxY": item[0][3], "color": f'{item[1][0]},{item[1][1]},{item[1][2]}'} for item in color_adjust]
                }
                taskBody = json.dumps(taskBody)
                send_task(taskBody)
                # logger.info(taskBody) # {"taskname": "WRE_202508241001_1687x797", "mark": [{"TlX": 1687, "TlY": 797, "PxX": 18, "PxY": 6, "color": "120,120,120"}, {"TlX": 1687, "TlY": 797, "PxX": 19, "PxY": 6, "color": "120,120,120"}, {"TlX": 1687, "TlY": 797, "PxX": 20, "PxY": 6, "color": "120,120,120"}, {"TlX": 1687, "TlY": 797, "PxX": 21, "PxY": 6, "color": "120,120,120"}, {"TlX": 1687, "TlY": 797, "PxX": 22, "PxY": 6, "color": "120,120,120"}, {"TlX": 1687, "TlY": 797, "PxX": 20, "PxY": 7, "color": "120,120,120"}]}
                comparison_img.save(comparison_path)
            shutil.copy(comparison_path, model_path)
    return changes_flag

"""
# 画图任务管理器
"""
def send_task(taskBody):
    logger.info(f'[INFO] 提交任务: {taskBody}')
    url = f'{WPLACER_URL}/pixelTask'
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, data=taskBody, headers=headers)
        response.raise_for_status()
        logger.info("[INFO] 任务提交成功:", response.json())
    except Exception as e:
        logger.info("[ERROR] 提交任务失败:", e)


"""
# 初始化
"""
def init():

    # 设置备份定时任务
    if BACKUP:
        scheduler = BackgroundScheduler()
        fields = BACKUP_SCHEDULE.split()
        if len(fields) != 6:
            logger.info("备份任务设置失败, BACKUP_SCHEDULE 必须是 6 位 cron 表达式")
        else:
            scheduler.add_job(
                backup_job,
                'cron',
                second=fields[0],
                minute=fields[1],
                hour=fields[2],
                day=fields[3],
                month=fields[4],
                day_of_week=fields[5]
            )
            scheduler.start()



if __name__ == "__main__":
    init()
    logger.info("开始主程序")
    while True:
        changes_pixel = False
        for area in MONITOR_AREA:
            logger.info(f'检查区域: {area}')
            MONITOR_LEFT, MONITOR_TOP, MONITOR_RIGHT, MONITOR_BOTTOM = area[0], area[1], area[2], area[3]
            if map_check(left=MONITOR_LEFT, top=MONITOR_TOP, right=MONITOR_RIGHT, bottom=MONITOR_BOTTOM) : changes_pixel = True
        time.sleep(LOOP_SLEEP_SHORT if changes_pixel else LOOP_SLEEP)