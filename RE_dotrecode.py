"""
从 dotrecode.log 中恢复指定id的修改
"""
import json
import time

from main import send_task

RE_id = ["10875368","9355656"]  # 想重置的的记录ID
LOG_FILE = "dbmiss/dotrecode.log" # 当mysql无法连接时回退的记录文件

with open(LOG_FILE, "r", encoding="utf-8") as f:
    recover = []
    for line in f:
        entry = json.loads(line)
        data = tuple(entry["data"])
        if str(data[1]) in RE_id:
            print(data) # ('WittyCap', 10875368, '', 1689, 799, 517, 683, '(0, 0, 0, 255)', '(0, 0, 0, 0)')
            color  = data[7].strip("()").replace(", ", ",").split(",")
            recover.append({"TlX": data[3], "TlY": data[4], "PxX": data[5], "PxY": data[6], "color": f'{color[0]},{color[1]},{color[2]}'})

    print(f"共找到 {len(recover)} 条记录")
    task = {
        "taskname": f'WRE_dotrecode_{time.strftime("%Y%m%d%H%M")}_{data[3]}x{data[4]}',
        "mark": [
            item for item in recover
        ]
    }
    task_json = json.dumps(task, ensure_ascii=False)
    print(task_json)
    send_task(task_json)
