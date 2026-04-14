import os
import sqlite3
from datetime import datetime, timedelta, timezone

BASE_DIR = "/opt/squid_acl_dashboard"
DB_PATH = os.path.join(BASE_DIR, "acl_dashboard.db")
KEEP_DAYS = 180

# 北京时间（UTC+8），无论服务器时区如何都强制使用
CST = timezone(timedelta(hours=8))


def main():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] 数据库不存在: {DB_PATH}")
        return

    cutoff_dt = datetime.now(tz=CST) - timedelta(days=KEEP_DAYS)
    cutoff_ts = cutoff_dt.timestamp()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 先看看总量
    total_before = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # 删除旧数据
    cur.execute("DELETE FROM events WHERE event_ts < ?", (cutoff_ts,))
    deleted = cur.rowcount

    conn.commit()

    # 回收空间
    cur.execute("VACUUM")

    total_after = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()

    print("========== 清理完成 ==========")
    print(f"当前时间         : {datetime.now(tz=CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"保留最近天数     : {KEEP_DAYS}")
    print(f"删除阈值时间     : {cutoff_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"清理前总记录数   : {total_before}")
    print(f"删除记录数       : {deleted}")
    print(f"清理后总记录数   : {total_after}")


if __name__ == "__main__":
    main()
