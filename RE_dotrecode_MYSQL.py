import json
import time
import pymysql
from main import MYSQLDB_TABLE_CONFIG, MYSQLDB_CONFIG, send_task

# player#10875295
RE_id = ["10634086","10629537","10630805","10003894"]  # 黑名单指针ID

conn = pymysql.connect(**MYSQLDB_CONFIG)
table = MYSQLDB_TABLE_CONFIG["dot_recode"]
cursor = conn.cursor()

placeholders = ",".join(["%s"] * len(RE_id))

# 说明：
# 1) 仅筛选黑名单 pointer_id
# 2) 用 MIN(CONCAT(action_time, '|', color_origin)) 找到“最早一次修改”的 color_origin
# 3) 在 SQL 里顺便把括号与空格去掉，返回如 "237,28,36,255"
sql = f"""
    SELECT
        TlX, TlY, PxX, PxY,
        SUBSTRING_INDEX(
            MIN(
                CONCAT(
                    DATE_FORMAT(action_time, '%%Y-%%m-%%d %%H:%%i:%%s'),
                    '|',
                    REPLACE(REPLACE(REPLACE(color_origin, '(', ''), ')', ''), ', ', ',')
                )
            ),
            '|',
            -1
        ) AS earliest_color_origin
    FROM {table}
    WHERE pointer_id IN ({placeholders})
    GROUP BY TlX, TlY, PxX, PxY
"""

cursor.execute(sql, RE_id)
rows = cursor.fetchall()

recover = []
for TlX, TlY, PxX, PxY, color_str in rows:
    # color_str 形如 "237,28,36,255"；这里只取 RGB
    if color_str is None:
        continue
    parts = [p.strip() for p in color_str.split(",") if p.strip() != ""]
    if len(parts) < 3:
        continue
    rgb = ",".join(parts[:3])
    recover.append({
        "TlX": TlX,
        "TlY": TlY,
        "PxX": PxX,
        "PxY": PxY,
        "color": rgb
    })

cursor.close()
conn.close()

print(f"去重后共 {len(recover)} 个坐标（颜色为黑名单最早一次修改的 color_origin）")

task = {
    "taskname": f'WRE_dotrecode_MYSQL_{time.strftime("%Y%m%d%H%M")}',
    "mark": recover
}

# JSON 美化输出（多行）
task_json = json.dumps(task, ensure_ascii=False, indent=4)
print(task_json)

send_task(task_json)