import ast
import cloudscraper
import dotenv
import os
import requests
import shutil
import time
from PIL import Image, ImageChops
from apscheduler.schedulers.blocking import BlockingScheduler


def env_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes", "on")

# env文件
config = dotenv.dotenv_values(".env")
wplacer_url = f"{config['WPLACER_HOST']}:{config['WPLACER_PORT']}" if config.get("WPLACER_PORT") else config['WPLACER_HOST']
MONITOR_LEFT=int(config["MONITOR_LEFT"])
MONITOR_TOP=int(config["MONITOR_TOP"])
MONITOR_RIGHT=int(config["MONITOR_RIGHT"])
MONITOR_BOTTOM=int(config["MONITOR_BOTTOM"])
BACKUP=env_bool(config.get("BACKUP", True))
BACKUP_SCHEDULE= config.get("BACKUP_SCHEDULE", "* /30 * * * *")
BLACK_LIST=ast.literal_eval(config.get("BLACK_LIST", "[]"))
BACKUP_BLACKED=env_bool(config.get("BACKUP_BLACKED",True))
ONLY_OVERLAY=env_bool(config.get("ONLY_OVERLAY",False))
LOOP_SLEEP=int(config["LOOP_SLEEP"])

# 请求配置
HEADERS={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36", "Accept": "text/html", "Referer": "https://www.wplace.live/"}
MAX_RETRIES=999999 # 最大重试次数
DELAY=1 # 每个请求和重试间延迟，单位秒

# 目录配置
MODEL_DIR="model" # 模板目录
COMPARISON_DIR=f'{MODEL_DIR}/comparison' # 比较目录
BACKUP_DIR="backup" # 备份目录
BACKUP_BLACKED=f'{BACKUP_DIR}/black' # 黑名单涂鸦备份

# 杂项
FILE_EXTENSION=".png"
SCRAPER = cloudscraper.create_scraper()

"""
# 地区涂鸦下载
"""
def clone_area(left=MONITOR_LEFT, top=MONITOR_TOP, right=MONITOR_RIGHT, bottom=MONITOR_BOTTOM, max_retries=MAX_RETRIES, delay=DELAY, save_dir=MODEL_DIR):
    for x in range(left, right + 1):
        for y in range(top, bottom + 1):
            retries = 0
            while retries < max_retries:
                try:
                    response = requests.get(f'https://backend.wplace.live/files/s0/tiles/{x}/{y}.png', headers=HEADERS, timeout=10)
                    if response.status_code == 200:
                        with open(f"{save_dir}/{x}_{y}{FILE_EXTENSION}", "wb") as f:
                            f.write(response.content)
                        print(f'[OK] ({x},{y}) 下载成功')
                        break
                    elif response.status_code == 404:
                        print(f'[INFO] ({x},{y}) 图块不存在，跳过')
                        break
                    else:
                        retries += 1
                        print(f'[WARN] ({x},{y}) 状态码 {response.status_code}，重试第 {retries} 次')
                except requests.exceptions.RequestException as e:
                    retries += 1
                    print(f'[ERROR] ({x},{y}) 请求失败: {e}，重试第 {retries} 次')
                time.sleep(delay)


"""
# 地区涂鸦备份
"""
def backup_area(left=MONITOR_LEFT, top=MONITOR_TOP, right=MONITOR_RIGHT, bottom=MONITOR_BOTTOM, max_retries=MAX_RETRIES, delay=DELAY, backup_dir=BACKUP_DIR):
    print(f'[INFO] 开始备份')
    backup_folder = f'{backup_dir}/{time.strftime("%Y%m%d%H%M")}_backup'
    os.makedirs(backup_folder, exist_ok=True)
    clone_area(left=left, top=top, right=right, bottom=bottom, max_retries=max_retries, delay=delay, save_dir=backup_folder)


"""
# 获取点作者
返回: None / {id: 123, name: "321"}
"""
def poke_author(TlX, TlY, PxX, PxY, retries=MAX_RETRIES, delay=DELAY):
    retrie = 0
    while retrie < retries:
        response = SCRAPER.get(f'https://backend.wplace.live/s0/pixel/{TlX}/{TlY}?x={PxX}&y={PxY}')
        print(f'https://backend.wplace.live/s0/pixel/{TlX}/{TlY}?x={PxX}&y={PxY}')
        if response.status_code == 200:
            data = response.json()
            if data.get("paintedBy").get("id") != "":
                print(f'[OK] TlX: {TlX}, TlY: {TlY}, PxX: {PxX}, PxY: {PxY}, 获取点作者成功: {data["paintedBy"]}')
                return data["paintedBy"]
            else:
                print('[INFO] 该像素无作者信息')
                return None
        else:
            retrie += 1
            print(f'[WARN] 状态码 {response.status_code}, {response.content}, 重试第 {retrie} 次')
        time.sleep(delay)
    return None


"""
像素比较器
参数: img1_path: 图片1路径
       img2_path: 图片2路径
返回: None: 图片无效
        0: 图片相同
        [空]: ONLY_OVERLAY为true,黑名单用户画了图,但是没修改别人的画
        [[],[],[]]: 具体不相同的像素点
"""
def pixel_comparator(modelImg_path, comparImg_path):
    img1 = Image.open(modelImg_path).convert("RGBA")
    img2 = Image.open(comparImg_path).convert("RGBA")

    if img1.size != img2.size:
        return None

    diff = ImageChops.difference(img1, img2)
    if not diff.getbbox():
        return 0

    diff_pixels = []
    width, height = diff.size
    img1_data = img1.getdata()
    diff_data = diff.getdata()

    for y in range(height):
        for x in range(width):
            r, g, b, a = diff_data[y * width + x]
            if (r, g, b, a) != (0, 0, 0, 0):
                origin_a = img1_data[y * width + x][3]
                if not ONLY_OVERLAY or origin_a > 0:
                    diff_pixels.append((x, y, img1_data[y * width + x]))

    return diff_pixels


"""
# 区域变更处理器
"""
def map_check(left=MONITOR_LEFT, top=MONITOR_TOP, right=MONITOR_RIGHT, bottom=MONITOR_BOTTOM, max_retries=MAX_RETRIES, delay=DELAY, model_dir=MODEL_DIR):
    # 克隆对比图
    # clone_area(left=left, top=top, right=right, bottom=bottom, max_retries=max_retries, delay=delay, save_dir=COMPARISON_DIR)
    # 遍历比较每一张图
    for _, _, compfiles in os.walk(COMPARISON_DIR):
        for comp_item in compfiles:
            print(comp_item)
            if not os.path.exists(os.path.join(model_dir, comp_item)):
                shutil.copy(os.path.join(COMPARISON_DIR, comp_item), os.path.join(model_dir, comp_item))
                continue
            diff_pixels = pixel_comparator(os.path.join(model_dir, comp_item), os.path.join(COMPARISON_DIR, comp_item))
            if diff_pixels is None or diff_pixels == 0: continue
            print(f'[INFO] {comp_item} 发现 {len(diff_pixels)} 个不同像素')
            print(diff_pixels)
            Tl = comp_item[:-len(FILE_EXTENSION)].split("_")
            for dot in diff_pixels:
                print(f'{Tl[0]}, {Tl[1]}, {dot[0]}, {dot[1]}')
                author = poke_author(Tl[0], Tl[1], dot[0], dot[1])
                if author is not None and author["id"] in BLACK_LIST:
                    print("发现黑名单修改")

"""
# 画图任务管理器
"""


"""
# 初始化
"""
def init():
    # 创建目录
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(COMPARISON_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(BACKUP_BLACKED, exist_ok=True)

    # 设置备份定时任务
    if BACKUP:
        scheduler = BlockingScheduler()
        fields = BACKUP_SCHEDULE.split()
        if len(fields) != 6:
            print("备份任务设置失败, BACKUP_SCHEDULE 必须是 6 位 cron 表达式")
        else:
            scheduler.add_job(
                backup_area,
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
    while True:
        map_check()
        time.sleep(LOOP_SLEEP)