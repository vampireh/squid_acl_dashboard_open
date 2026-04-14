import os
import re
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# 北京时间（UTC+8），无论服务器时区如何都强制使用
CST = timezone(timedelta(hours=8))

BASE_DIR = "/opt/squid_acl_dashboard"
DB_PATH = os.path.join(BASE_DIR, "acl_dashboard.db")
LOG_PATH = "/var/log/squid/access.log"

TARGET_STATUSES = {
    "TCP_MISS/200",
    "TCP_HIT/200",
    "TCP_MEM_HIT/200",
    "TCP_REFRESH_UNMODIFIED/200",
    "TCP_REFRESH_MODIFIED/200",
    "TCP_TUNNEL/200",
    "TCP_DENIED/403",
    "TCP_DENIED/407",
    "NONE_NONE/000",
    "TAG_NONE/200",
    "TAG_NONE/403",
    "ERR_CONNECT_FAIL",
    "ERR_DNS_FAIL",
    "TCP_SWAPFAIL_MISS/200",
    "UDP_HIT",
    "UDP_MISS",
}

LOG_RE = re.compile(
    r"""
    ^(?P<ts>\d+\.\d+)\s+
    (?P<elapsed>\d+)\s+
    (?P<client_ip>\S+)\s+
    (?P<status>\S+)\s+
    (?P<size>\d+)\s+
    (?P<method>\S+)\s+
    (?P<target>\S+)\s+
    (?P<user>\S+)\s+
    (?P<hierarchy>\S+)\s+
    (?P<content_type>\S+)
    """,
    re.VERBOSE,
)


def classify_status(status: str) -> str:
    acl_related = {
        "TCP_DENIED/403",
        "TCP_DENIED/407",
        "TAG_NONE/403",
    }

    success_related = {
        "TCP_MISS/200",
        "TCP_HIT/200",
        "TCP_MEM_HIT/200",
        "TCP_REFRESH_UNMODIFIED/200",
        "TCP_REFRESH_MODIFIED/200",
        "TCP_TUNNEL/200",
        "TAG_NONE/200",
        "UDP_HIT",
        "UDP_MISS",
    }

    error_related = {
        "NONE_NONE/000",
        "ERR_CONNECT_FAIL",
        "ERR_DNS_FAIL",
        "TCP_SWAPFAIL_MISS/200",
    }

    if status in acl_related:
        return "ACL"
    if status in success_related:
        return "SUCCESS"
    if status in error_related:
        return "ERROR"
    return "OTHER"


def extract_host(method: str, target: str) -> str:
    if method == "CONNECT":
        return target.split(":")[0]
    if target.startswith("http://") or target.startswith("https://"):
        try:
            parsed = urlparse(target)
            return parsed.hostname or ""
        except Exception:
            return ""
    return target


def init_db(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT NOT NULL,
            event_ts REAL NOT NULL,
            client_ip TEXT NOT NULL,
            status TEXT NOT NULL,
            category TEXT NOT NULL,
            http_code TEXT NOT NULL,
            method TEXT NOT NULL,
            target TEXT NOT NULL,
            host TEXT,
            user_field TEXT,
            hierarchy TEXT,
            content_type TEXT,
            raw_line TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # 兼容旧表
    try:
        cur.execute("ALTER TABLE events ADD COLUMN category TEXT DEFAULT 'OTHER'")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events(event_ts DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_ip ON events(client_ip)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_category ON events(category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_host ON events(host)")
    conn.commit()


def parse_line(line: str):
    m = LOG_RE.match(line.strip())
    if not m:
        return None

    data = m.groupdict()
    status = data["status"]

    if status not in TARGET_STATUSES:
        return None

    ts = float(data["ts"])
    dt = datetime.fromtimestamp(ts, tz=CST).strftime("%Y-%m-%d %H:%M:%S")
    method = data["method"]
    target = data["target"]
    host = extract_host(method, target)

    parts = status.split("/")
    http_code = parts[1] if len(parts) > 1 else ""

    return (
        dt,                               # event_time
        ts,                               # event_ts
        data["client_ip"],                # client_ip
        status,                           # status
        classify_status(status),          # category
        http_code,                        # http_code
        method,                           # method
        target,                           # target
        host,                             # host
        data["user"],                     # user_field
        data["hierarchy"],                # hierarchy
        data["content_type"],             # content_type
        line.strip(),                     # raw_line
        datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S"),  # created_at
    )


def insert_batch(conn, rows):
    if not rows:
        return
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT INTO events (
            event_time, event_ts, client_ip, status, category, http_code,
            method, target, host, user_field, hierarchy,
            content_type, raw_line, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def main():
    log_path = LOG_PATH
    db_path = DB_PATH
    truncate_first = False

    # 用法：
    # python3 import_history.py
    # python3 import_history.py /path/to/access.log
    # python3 import_history.py /path/to/access.log --truncate
    if len(sys.argv) >= 2:
        if sys.argv[1] != "--truncate":
            log_path = sys.argv[1]

    if "--truncate" in sys.argv:
        truncate_first = True

    if not os.path.exists(log_path):
        print(f"[ERROR] access.log 不存在: {log_path}")
        sys.exit(1)

    os.makedirs(BASE_DIR, exist_ok=True)

    conn = sqlite3.connect(db_path)
    init_db(conn)

    if truncate_first:
        print("[INFO] 清空 events 表旧数据...")
        conn.execute("DELETE FROM events")
        conn.commit()

    batch = []
    batch_size = 1000

    total_lines = 0
    parsed_count = 0
    inserted_count = 0
    skipped_count = 0

    print(f"[INFO] 开始导入: {log_path}")
    print(f"[INFO] 数据库: {db_path}")

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            total_lines += 1
            row = parse_line(line)
            if row is None:
                skipped_count += 1
                continue

            parsed_count += 1
            batch.append(row)

            if len(batch) >= batch_size:
                insert_batch(conn, batch)
                inserted_count += len(batch)
                print(f"[INFO] 已导入 {inserted_count} 条")
                batch = []

    if batch:
        insert_batch(conn, batch)
        inserted_count += len(batch)

    conn.close()

    print("========== 导入完成 ==========")
    print(f"总行数       : {total_lines}")
    print(f"匹配行数     : {parsed_count}")
    print(f"导入成功条数 : {inserted_count}")
    print(f"跳过条数     : {skipped_count}")


if __name__ == "__main__":
    main()
