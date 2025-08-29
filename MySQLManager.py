import os
import json
import pymysql
from datetime import datetime
from logger_config import logger

# 无法连接数据库时，像素变化记录存放到这里
os.makedirs("dbmiss", exist_ok=True)
DOTRECODE_LOG = os.path.join("dbmiss", "dotrecode.log")

class MySQLManager:
    def __init__(self, db_config, table_config):
        self.db_config = db_config
        self.table_config = table_config
        self.conn = None
        self._connect()
        self._init_tables()

    def _connect(self):
        """建立数据库连接"""
        try:
            self.conn = pymysql.connect(**self.db_config)
            logger.info('数据库连接成功')
        except Exception as e:
            logger.error(f'数据库连接失败: {e}')
            self.conn = None

    def _init_tables(self):
        """初始化数据库表"""
        create_table_sql = f'CREATE TABLE IF NOT EXISTS {self.table_config["dot_recode"]} (id int auto_increment primary key, pointer_name varchar(20), pointer_id varchar(20), pointer_alliancename varchar(40), TlX int, TlY int, PxX int, PxY int, color_origin varchar(30), color_now varchar(30), action_time timestamp default current_timestamp) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'

        try:
            with self._get_cursor() as cursor:
                cursor.execute(create_table_sql)
            self.conn.commit()
            logger.info('数据库表初始化成功')
        except Exception as e:
            logger.error(f'数据库表初始化失败: {e}')
            self.conn.rollback()

    def _get_cursor(self):
        """确保连接可用并返回 cursor"""
        try:
            self.conn.ping(reconnect=True)
        except Exception:
            logger.warning("数据库连接失效，正在重连...")
            self._connect()
        return self.conn.cursor()

    def insert(self, sql, data_list):
        """
        批量插入数据
        """
        if not data_list:
            return

        try:
            with self._get_cursor() as cursor:
                cursor.executemany(sql, data_list)
            self.conn.commit()
            logger.info(f'成功插入 {len(data_list)} 条记录')
        except Exception as e:
            logger.error(f'记录插入失败: {e}')
            self.conn.rollback()
            self.write_recode_log(sql, data_list)

    def write_recode_log(self, sql, data_list):
        """将失败数据写入日志"""
        try:
            with open(DOTRECODE_LOG, "a", encoding="utf-8") as f:
                for row in data_list:
                    log_entry = {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "sql": sql,
                        "data": row
                    }
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            logger.info(f'[!] 无法链接到mysql, 已将 {len(data_list)} 条保存失败的数据放到了 {DOTRECODE_LOG}')
        except Exception as e:
            logger.error(f'[!!] 无法链接到mysql, 且无法写入记录日志, 记录已丢失 {e}')
