import os
import re
import sqlite3
import threading
import time
import logging
import secrets
import smtplib
import string
from email.mime.text import MIMEText
from email.header import Header
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from flask import Flask, g, render_template, request, redirect, url_for, flash, session, jsonify, Markup
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

BASE_DIR = "/opt/squid_acl_dashboard"
DB_PATH = os.path.join(BASE_DIR, "acl_dashboard.db")
LOG_PATH = "/var/log/squid/access.log"
URL_PREFIX = "/squid-acl"

# 北京时间（UTC+8），无论服务器时区如何都强制使用
CST = timezone(timedelta(hours=8))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# 日志
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "app.log")

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

app.logger.setLevel(logging.INFO)
app.logger.addHandler(file_handler)

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


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def _open_db():
    """裸连接（用于 auth 路由，避免请求上下文污染）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
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

    # 尝试为旧数据库补 category 列
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

    # ── proxy_ips 表：IP 分组（A/B/C/D）──────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS proxy_ips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_addr TEXT UNIQUE NOT NULL,
            ip_group TEXT NOT NULL CHECK(ip_group IN ('A','B','C','D')),
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_proxy_ips_group ON proxy_ips(ip_group)")

    # ── proxy_users 表：B/D 类用户账号密码 ──────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS proxy_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            user_group TEXT NOT NULL CHECK(user_group IN ('B','D')),
            user_realname TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    # 旧库补 user_realname 列
    try:
        cur.execute("ALTER TABLE proxy_users ADD COLUMN user_realname TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    conn.commit()

    # ── 从服务器文件初始化 proxy_ips（如表为空）─────────────
    if conn.execute("SELECT COUNT(*) FROM proxy_ips").fetchone()[0] == 0:
        for g in ["A", "B", "C", "D"]:
            sync_ips_from_file(g)
        app.logger.info("proxy_ips 表已从服务器文件初始化")

    # ── 从服务器文件初始化 proxy_users（如表为空）───────────
    if conn.execute("SELECT COUNT(*) FROM proxy_users").fetchone()[0] == 0:
        cnt = sync_users_from_passwd()
        app.logger.info("proxy_users 表已从 passwd 初始化（共 %d 条）", cnt)

    # ── 用户表 ────────────────────────────────────────────────────────────────
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            password_changed_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # ── 密码重置 Token 表 ─────────────────────────────────────────────────────
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reset_tokens (
            token TEXT PRIMARY KEY,
            expires_at REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # 插入默认管理员（如不存在）
    DEFAULT_USER = "admin"
    DEFAULT_PWD = "admin@123"
    existing = cur.execute(
        "SELECT username FROM users WHERE username = ?", (DEFAULT_USER,)
    ).fetchone()
    if not existing:
        cur.execute(
            "INSERT INTO users (username, password_hash, password_changed_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                DEFAULT_USER,
                generate_password_hash(DEFAULT_PWD),
                datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        app.logger.info("默认管理员已创建：%s / %s", DEFAULT_USER, DEFAULT_PWD)

    conn.commit()
    conn.close()


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

    return {
        "event_time": dt,
        "event_ts": ts,
        "client_ip": data["client_ip"],
        "status": status,
        "category": classify_status(status),
        "http_code": http_code,
        "method": method,
        "target": target,
        "host": host,
        "user_field": data["user"],
        "hierarchy": data["hierarchy"],
        "content_type": data["content_type"],
        "raw_line": line.strip(),
        "created_at": datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
    }


def insert_event(conn, event):
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO events (
            event_time, event_ts, client_ip, status, category, http_code,
            method, target, host, user_field, hierarchy,
            content_type, raw_line, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event["event_time"],
            event["event_ts"],
            event["client_ip"],
            event["status"],
            event["category"],
            event["http_code"],
            event["method"],
            event["target"],
            event["host"],
            event["user_field"],
            event["hierarchy"],
            event["content_type"],
            event["raw_line"],
            event["created_at"],
        ),
    )
    conn.commit()

    app.logger.info(
        "event inserted: ip=%s status=%s category=%s host=%s target=%s",
        event["client_ip"],
        event["status"],
        event["category"],
        event["host"],
        event["target"],
    )


def tail_f(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if line:
                yield line
            else:
                time.sleep(0.5)
                try:
                    if os.stat(path).st_ino != os.fstat(f.fileno()).st_ino:
                        f.close()
                        f = open(path, "r", encoding="utf-8", errors="ignore")
                except FileNotFoundError:
                    time.sleep(1)


KEEP_DAYS = 180          # 保留最近 180 天的数据
CLEANUP_HOUR = 3         # 每天北京时间 03:00 执行一次清理

# ── 邮件找回密码配置 ──────────────────────────────────────────────────────────
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.example.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = SMTP_USER          # 发件人（与 SMTP_USER 相同）
ADMIN_EMAIL = "admin@example.com"  # 【开源版】请修改上方 ADMIN_EMAIL 为你的邮箱后使用

# ── Flask-Login 初始化 ────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "请先登录。"
login_manager.login_message_category = "warning"


class User(UserMixin):
    """Flask-Login 用户对象，仅作包装用，数据仍在 users 表。"""

    def __init__(self, user_id: str):
        self.id = user_id


@login_manager.user_loader
def load_user(user_id: str):
    """根据 session 中的 user_id（实际存的是 username）验证用户是否存在。"""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT username FROM users WHERE username = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return User(user_id)
    return None


def send_reset_email(new_password: str) -> bool:
    """发送新密码邮件到 ADMIN_EMAIL。失败时写日志但不抛异常。"""
    if not SMTP_USER or not SMTP_PASS:
        app.logger.warning(
            "SMTP_USER / SMTP_PASS 未配置，邮件未发送。"
            "新密码（仅演示）：%s", new_password
        )
        return False

    subject = "Squid ACL 看板 - 密码重置通知"
    body = (
        f"您好，\n\n"
        f"您的 Squid ACL 看板账号已重置密码为：\n\n"
        f"    {new_password}\n\n"
        f"请登录后立即修改为更安全的密码。\n"
        f"此邮件由系统自动发出，请勿回复。\n\n"
        f"Squid ACL 看板"
    )
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = Header(f" Squid ACL <{FROM_EMAIL}>", "utf-8")
        msg["To"] = ADMIN_EMAIL

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, [ADMIN_EMAIL], msg.as_string())

        app.logger.info("密码重置邮件已发送至 %s", ADMIN_EMAIL)
        return True
    except Exception as e:
        app.logger.error("邮件发送失败：%s", e)
        return False


def gen_password(length: int = 16) -> str:
    """生成随机密码：大小写字母 + 数字，避开易混淆字符。"""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def cleanup_old_data():
    """删除 event_ts 早于 KEEP_DAYS 天前的记录，并压缩数据库。"""
    cutoff_dt = datetime.now(tz=CST) - timedelta(days=KEEP_DAYS)
    cutoff_ts = cutoff_dt.timestamp()

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        total_before = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        cur.execute("DELETE FROM events WHERE event_ts < ?", (cutoff_ts,))
        deleted = cur.rowcount
        conn.commit()

        # 回收磁盘空间（VACUUM 会短暂锁表，凌晨执行影响最小）
        conn.execute("VACUUM")
        total_after = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()

        app.logger.info(
            "cleanup done: cutoff=%s deleted=%d before=%d after=%d",
            cutoff_dt.strftime("%Y-%m-%d %H:%M:%S"),
            deleted,
            total_before,
            total_after,
        )
    except Exception as e:
        app.logger.error("cleanup failed: %s", e)


def cleanup_scheduler():
    """
    后台线程：每天北京时间 CLEANUP_HOUR 点执行一次数据清理。
    启动时若当天清理时间已过则等到明天，否则等到今天的清理时间。
    """
    app.logger.info(
        "cleanup_scheduler started: keep_days=%d, run_at=%02d:00 CST",
        KEEP_DAYS, CLEANUP_HOUR,
    )
    while True:
        now = datetime.now(tz=CST)
        # 计算下一次执行时间
        next_run = now.replace(hour=CLEANUP_HOUR, minute=0, second=0, microsecond=0)
        if now >= next_run:
            # 今天的时间已过，改为明天
            next_run += timedelta(days=1)

        wait_secs = (next_run - now).total_seconds()
        app.logger.info(
            "cleanup_scheduler: next run at %s (%.0f s later)",
            next_run.strftime("%Y-%m-%d %H:%M:%S"), wait_secs,
        )
        time.sleep(wait_secs)
        cleanup_old_data()


# ════════════════════════════════════════════════════════════════════════════
#  Squid 配置管理
# ════════════════════════════════════════════════════════════════════════════

# Squid 配置文件路径（在服务器上的实际路径）
SQUID_DIR = "/etc/squid"
SQUID_CONF = os.path.join(SQUID_DIR, "squid.conf")
SQUID_BACKUP_DIR = os.path.join(BASE_DIR, "squid_backups")
IP_FILES = {
    "A": os.path.join(SQUID_DIR, "ip_group_a.txt"),
    "B": os.path.join(SQUID_DIR, "ip_group_b.txt"),
    "C": os.path.join(SQUID_DIR, "ip_group_c.txt"),
    "D": os.path.join(SQUID_DIR, "ip_group_d.txt"),
}
PASSWD_FILE = os.path.join(SQUID_DIR, "passwd")
ALLOW_FILE = os.path.join(SQUID_DIR, "allow.txt")

os.makedirs(SQUID_BACKUP_DIR, exist_ok=True)

# 四类 IP 分组说明（前端展示用）
IP_GROUP_DESC = {
    "A": {
        "label": "A 类（VIP）",
        "icon": "👑",
        "color": "#f59e0b",
        "desc": "免密访问，可浏览所有网站",
        "auth": "无需账号密码",
        "sites": "全网站",
        "tip": "适用于学校管理层、服务器等高权限终端",
    },
    "B": {
        "label": "B 类（教职工）",
        "icon": "👤",
        "color": "#3b82f6",
        "desc": "输入账号密码，可浏览所有网站",
        "auth": "需输入账号密码（在下方「B/D 类用户管理」中配置）",
        "sites": "全网站",
        "tip": "适用于教师、职工等需实名记录的终端",
    },
    "C": {
        "label": "C 类（哑终端）",
        "icon": "🖥️",
        "color": "#10b981",
        "desc": "免密访问，仅可浏览白名单网站",
        "auth": "无需账号密码",
        "sites": "仅限白名单（allow.txt）",
        "tip": "适用于打印机、摄像头等哑终端设备",
    },
    "D": {
        "label": "D 类（受限员工）",
        "icon": "🔒",
        "color": "#8b5cf6",
        "desc": "输入账号密码，仅可浏览白名单网站",
        "auth": "需输入账号密码（在下方「B/D 类用户管理」中配置）",
        "sites": "仅限白名单（allow.txt）",
        "tip": "适用于需要限制访问范围的临时或受限账号",
    },
}


class SquidConf:
    """Squid.conf 文件管理器：读取、备份、写入。"""

    @staticmethod
    def read() -> str:
        try:
            with open(SQUID_CONF, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
        except Exception as e:
            app.logger.error("读取 squid.conf 失败：%s", e)
            return ""

    @staticmethod
    def write(content: str) -> tuple:
        """
        写入新内容前先备份，返回 (success, message)。
        备份文件名：squid.conf.bak.20260414_143000
        """
        try:
            # 生成带时间戳的备份名
            ts = datetime.now(tz=CST).strftime("%Y%m%d_%H%M%S")
            backup_name = f"squid.conf.bak.{ts}"
            backup_path = os.path.join(SQUID_BACKUP_DIR, backup_name)

            # 读取旧内容（如果存在）再备份
            old_content = SquidConf.read()
            if old_content:
                with open(backup_path, "w", encoding="utf-8") as f:
                    f.write(old_content)
                app.logger.info("已备份 squid.conf → %s", backup_path)

            # 写入新内容
            with open(SQUID_CONF, "w", encoding="utf-8") as f:
                f.write(content)

            app.logger.info("squid.conf 已更新")
            return True, f"保存成功，已自动备份到 {backup_name}"
        except PermissionError:
            return False, "权限不足，请确保服务有 /etc/squid/squid.conf 写入权限（通常需要 root）"
        except Exception as e:
            app.logger.error("写入 squid.conf 失败：%s", e)
            return False, f"写入失败：{e}"

    @staticmethod
    def backups() -> list:
        """返回备份文件列表（按时间倒序）。"""
        try:
            files = []
            for f in os.listdir(SQUID_BACKUP_DIR):
                if f.startswith("squid.conf.bak."):
                    fp = os.path.join(SQUID_BACKUP_DIR, f)
                    files.append({
                        "name": f,
                        "path": fp,
                        "size": os.path.getsize(fp),
                        "mtime": datetime.fromtimestamp(
                            os.path.getmtime(fp), tz=CST
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                    })
            files.sort(key=lambda x: x["mtime"], reverse=True)
            return files
        except Exception:
            return []


def gen_proxy_password(length: int = 12) -> str:
    """生成随机密码（字母+数字）。"""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def sync_ips_from_file(group: str) -> int:
    """从 IP 文件读取内容到 proxy_ips 表（group 分类），返回读取条数。"""
    ip_file = IP_FILES.get(group)
    if not ip_file or not os.path.exists(ip_file):
        return 0
    try:
        conn = _open_db()
        # 先清空该分组
        conn.execute("DELETE FROM proxy_ips WHERE ip_group = ?", (group,))
        count = 0
        with open(ip_file, "r", encoding="utf-8") as f:
            for line in f:
                ip = line.strip()
                if ip and not ip.startswith("#"):
                    conn.execute(
                        "INSERT INTO proxy_ips (ip_addr, ip_group, description) VALUES (?, ?, ?)",
                        (ip, group, ""),
                    )
                    count += 1
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        app.logger.error("同步 %s 组 IP 文件失败：%s", group, e)
        return 0


def sync_ips_to_file(group: str) -> tuple:
    """将 proxy_ips 表中 group 分组写回 IP 文件，返回 (success, count, message)。"""
    conn = _open_db()
    rows = conn.execute(
        "SELECT ip_addr FROM proxy_ips WHERE ip_group = ? ORDER BY id", (group,)
    ).fetchall()
    conn.close()

    ip_file = IP_FILES.get(group)
    if not ip_file:
        return False, 0, "文件路径未定义"

    try:
        with open(ip_file, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(row["ip_addr"] + "\n")
        app.logger.info("已同步 %s 组 IP → %s（共 %d 条）", group, ip_file, len(rows))
        return True, len(rows), f"已写入 {ip_file}（共 {len(rows)} 条）"
    except PermissionError:
        return False, 0, "权限不足，请确保服务有 /etc/squid/ 写入权限"
    except Exception as e:
        app.logger.error("写回 %s 组 IP 文件失败：%s", group, e)
        return False, 0, str(e)


def sync_users_from_passwd() -> int:
    """从 passwd 文件解析用户到 proxy_users 表，返回读取条数。"""
    if not os.path.exists(PASSWD_FILE):
        return 0
    try:
        conn = _open_db()
        count = 0
        with open(PASSWD_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                parts = line.split(":", 1)
                username = parts[0].strip()
                pw_hash = parts[1].strip() if len(parts) > 1 else ""
                if username:
                    conn.execute(
                        "INSERT OR IGNORE INTO proxy_users (username, password_hash, user_group) VALUES (?, ?, ?)",
                        (username, pw_hash, "B"),
                    )
                    count += 1
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        app.logger.error("同步 passwd 文件失败：%s", e)
        return 0


def write_passwd_file() -> tuple:
    """将 proxy_users 表中所有用户写回 passwd 文件。"""
    conn = _open_db()
    rows = conn.execute("SELECT username, password_hash FROM proxy_users").fetchall()
    conn.close()
    try:
        lines = [f"{r['username']}:{r['password_hash']}\n" for r in rows]
        with open(PASSWD_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
        app.logger.info("已写回 passwd 文件（共 %d 用户）", len(rows))
        return True, f"已保存 passwd（共 {len(rows)} 用户）"
    except PermissionError:
        return False, "权限不足，请确保服务有 /etc/squid/passwd 写入权限"
    except Exception as e:
        return False, str(e)


# ════════════════════════════════════════════════════════════════════════════
#  Squid 配置管理路由
# ════════════════════════════════════════════════════════════════════════════

@app.route(f"{URL_PREFIX}/proxy")
@login_required
def proxy_index():
    """Squid 配置管理首页：展示四类分组的统计。"""
    conn = _open_db()

    stats = {}
    for g_name in ["A", "B", "C", "D"]:
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM proxy_ips WHERE ip_group = ?", (g_name,)
        ).fetchone()["c"]
        stats[g_name] = cnt

    user_count = conn.execute("SELECT COUNT(*) AS c FROM proxy_users").fetchone()["c"]
    allow_count = 0
    if os.path.exists(ALLOW_FILE):
        with open(ALLOW_FILE, "r", encoding="utf-8") as f:
            allow_count = sum(1 for line in f if line.strip() and not line.strip().startswith("#"))

    conn.close()
    return render_template(
        "proxy_index.html",
        stats=stats,
        user_count=user_count,
        allow_count=allow_count,
        group_desc=IP_GROUP_DESC,
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


@app.route(f"{URL_PREFIX}/proxy/ips", methods=["GET", "POST"])
@login_required
def proxy_ips():
    """IP 分组管理：展示 + 增删改。"""
    group = request.args.get("group", "A").upper()
    if group not in IP_FILES:
        group = "A"

    conn = _open_db()

    # 处理 POST 请求
    action = request.form.get("action")
    if action == "add":
        ip_addr = request.form.get("ip_addr", "").strip()
        desc = request.form.get("description", "").strip()
        target_group = request.form.get("ip_group", group).upper()
        if ip_addr and target_group in IP_FILES:
            conn.execute(
                "INSERT INTO proxy_ips (ip_addr, ip_group, description) VALUES (?, ?, ?)",
                (ip_addr, target_group, desc),
            )
            conn.commit()
            sync_ips_to_file(target_group)
            flash(f"IP {ip_addr} 已添加到 {target_group} 组", "success")

    elif action == "delete":
        row_id = request.form.get("id")
        if row_id:
            row = conn.execute("SELECT ip_addr, ip_group FROM proxy_ips WHERE id = ?", (row_id,)).fetchone()
            conn.execute("DELETE FROM proxy_ips WHERE id = ?", (row_id,))
            conn.commit()
            if row:
                sync_ips_to_file(row["ip_group"])
                flash(f"IP {row['ip_addr']} 已删除", "success")

    elif action == "update":
        row_id = request.form.get("id")
        new_ip = request.form.get("ip_addr", "").strip()
        new_desc = request.form.get("description", "").strip()
        if row_id and new_ip:
            conn.execute(
                "UPDATE proxy_ips SET ip_addr = ?, description = ? WHERE id = ?",
                (new_ip, new_desc, row_id),
            )
            conn.commit()
            row = conn.execute("SELECT ip_group FROM proxy_ips WHERE id = ?", (row_id,)).fetchone()
            if row:
                sync_ips_to_file(row["ip_group"])
            flash(f"IP 已更新", "success")

    elif action == "move":
        row_id = request.form.get("id")
        new_group = request.form.get("new_group", "").strip().upper()
        if row_id and new_group in IP_FILES:
            row = conn.execute("SELECT ip_group FROM proxy_ips WHERE id = ?", (row_id,)).fetchone()
            if row:
                conn.execute("UPDATE proxy_ips SET ip_group = ? WHERE id = ?", (new_group, row_id))
                conn.commit()
                sync_ips_to_file(row["ip_group"])
                sync_ips_to_file(new_group)
                flash(f"已移动到 {new_group} 组", "success")

    # 读取当前分组数据
    rows = conn.execute(
        "SELECT * FROM proxy_ips WHERE ip_group = ? ORDER BY id", (group,)
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS c FROM proxy_ips WHERE ip_group = ?", (group,)).fetchone()["c"]

    # 各组数量
    group_counts = {}
    for g_name in ["A", "B", "C", "D"]:
        group_counts[g_name] = conn.execute(
            "SELECT COUNT(*) AS c FROM proxy_ips WHERE ip_group = ?", (g_name,)
        ).fetchone()["c"]

    conn.close()
    return render_template(
        "proxy_ips.html",
        rows=rows,
        group=group,
        total=total,
        group_counts=group_counts,
        group_desc=IP_GROUP_DESC,
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


@app.route(f"{URL_PREFIX}/proxy/allow", methods=["GET", "POST"])
@login_required
def proxy_allow():
    """白名单（allow.txt）管理。"""
    action = request.form.get("action")

    if action == "add":
        entry = request.form.get("entry", "").strip()
        if entry:
            try:
                with open(ALLOW_FILE, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
                flash(f"已添加：{entry}", "success")
            except PermissionError:
                flash("权限不足，无法写入 /etc/squid/allow.txt", "danger")
            except Exception as e:
                flash(f"写入失败：{e}", "danger")

    elif action == "delete":
        entry = request.form.get("entry", "").strip()
        if entry:
            try:
                with open(ALLOW_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(ALLOW_FILE, "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.strip() != entry:
                            f.write(line)
                flash(f"已删除：{entry}", "success")
            except Exception as e:
                flash(f"操作失败：{e}", "danger")

    # 读取当前内容
    entries = []
    if os.path.exists(ALLOW_FILE):
        try:
            with open(ALLOW_FILE, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        entries.append({"lineno": i, "entry": line})
        except Exception as e:
            flash(f"读取 allow.txt 失败：{e}", "danger")

    return render_template(
        "proxy_allow.html",
        entries=entries,
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


@app.route(f"{URL_PREFIX}/proxy/users", methods=["GET", "POST"])
@login_required
def proxy_users():
    """B/D 类用户账号密码管理。"""
    conn = _open_db()
    action = request.form.get("action")

    if action == "add":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user_group = request.form.get("user_group", "B").strip().upper()
        user_realname = request.form.get("user_realname", "").strip()
        if username and password and user_group in ("B", "D"):
            pw_hash = generate_password_hash(password, method="pbkdf2:sha256")
            try:
                conn.execute(
                    "INSERT INTO proxy_users (username, password_hash, user_group, user_realname) VALUES (?, ?, ?, ?)",
                    (username, pw_hash, user_group, user_realname),
                )
                conn.commit()
                write_passwd_file()
                flash(f"用户 {username}（{user_group}组）已添加，passwd 已更新", "success")
            except sqlite3.IntegrityError:
                flash(f"用户名 {username} 已存在", "warning")
            except Exception as e:
                flash(f"添加失败：{e}", "danger")

    elif action == "delete":
        uid = request.form.get("id")
        if uid:
            row = conn.execute("SELECT username FROM proxy_users WHERE id = ?", (uid,)).fetchone()
            conn.execute("DELETE FROM proxy_users WHERE id = ?", (uid,))
            conn.commit()
            write_passwd_file()
            flash(f"用户 {row['username'] if row else ''} 已删除", "success")

    elif action == "reset_password":
        uid = request.form.get("id")
        if uid:
            new_pwd = gen_proxy_password(12)
            pw_hash = generate_password_hash(new_pwd, method="pbkdf2:sha256")
            conn.execute("UPDATE proxy_users SET password_hash = ? WHERE id = ?", (pw_hash, uid))
            conn.commit()
            write_passwd_file()
            flash(f"新密码已生成：{new_pwd}（请妥善保存）", "success")

    elif action == "change_group":
        uid = request.form.get("id")
        new_group = request.form.get("new_group", "").strip().upper()
        if uid and new_group in ("B", "D"):
            conn.execute("UPDATE proxy_users SET user_group = ? WHERE id = ?", (new_group, uid))
            conn.commit()
            flash(f"已移动到 {new_group} 组", "success")

    elif action == "update_realname":
        uid = request.form.get("id")
        new_realname = request.form.get("user_realname", "").strip()
        if uid:
            conn.execute("UPDATE proxy_users SET user_realname = ? WHERE id = ?", (new_realname, uid))
            conn.commit()
            flash("姓名已更新", "success")

    rows = conn.execute("SELECT * FROM proxy_users ORDER BY id").fetchall()
    conn.close()
    return render_template(
        "proxy_users.html",
        rows=rows,
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


@app.route(f"{URL_PREFIX}/proxy/conf", methods=["GET", "POST"])
@login_required
def proxy_conf():
    """在线编辑 squid.conf。"""
    if request.method == "POST":
        content = request.form.get("content", "")
        ok, msg = SquidConf.write(content)
        if ok:
            flash(msg, "success")
        else:
            flash(msg, "danger")
        return render_template(
            "proxy_conf.html",
            content=content,
            backups=SquidConf.backups(),
            url_prefix=URL_PREFIX,
            current_user=current_user,
        )

    content = SquidConf.read()
    return render_template(
        "proxy_conf.html",
        content=content,
        backups=SquidConf.backups(),
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


@app.route(f"{URL_PREFIX}/proxy/conf/check", methods=["POST"])
@login_required
def proxy_conf_check():
    """执行 squid -k parse 语法检查。"""
    result = execute_squid_cmd("parse")
    return jsonify(result)


@app.route(f"{URL_PREFIX}/proxy/conf/reload", methods=["POST"])
@login_required
def proxy_conf_reload():
    """执行 squid -k reconfigure 重载配置。"""
    ok, msg = SquidConf.write(SquidConf.read())  # 先保存当前页面内容
    if not ok:
        return jsonify({"success": False, "output": msg})

    result = execute_squid_cmd("reconfigure")
    return jsonify(result)


@app.route(f"{URL_PREFIX}/proxy/conf/backup/<name>")
@login_required
def proxy_conf_backup(name):
    """下载备份文件。"""
    safe_name = os.path.basename(name)
    backup_path = os.path.join(SQUID_BACKUP_DIR, safe_name)
    if not os.path.exists(backup_path):
        flash("备份文件不存在", "danger")
        return redirect(url_for("proxy_conf"))
    from flask import send_file
    return send_file(backup_path, as_attachment=True, download_name=safe_name)


# ════════════════════════════════════════════════════════════════════════════
#  辅助命令执行
# ════════════════════════════════════════════════════════════════════════════

def execute_squid_cmd(cmd: str) -> dict:
    """在服务器上执行 squid 命令，返回 dict(success, output)。"""
    import subprocess
    try:
        result = subprocess.run(
            ["squid", "-k", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        app.logger.info("squid -k %s → returncode=%d output=%s", cmd, result.returncode, output[:200])
        return {"success": success, "output": output or ("命令执行成功（无输出）" if success else "命令执行失败")}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "执行超时（30秒）"}
    except FileNotFoundError:
        return {"success": False, "output": "未找到 squid 命令，请确认已安装并加入 PATH"}
    except Exception as e:
        app.logger.error("执行 squid -k %s 失败：%s", cmd, e)
        return {"success": False, "output": str(e)}


# ════════════════════════════════════════════════════════════════════════════
#  认证路由
# ════════════════════════════════════════════════════════════════════════════

@app.route(f"{URL_PREFIX}/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("用户名和密码不能为空。", "danger")
            return render_template("login.html", url_prefix=URL_PREFIX)

        conn = _open_db()
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if row and check_password_hash(row["password_hash"], password):
            login_user(User(username))
            session["username"] = username
            app.logger.info("用户登录成功：%s", username)

            next_url = request.args.get("next")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("index"))

        flash("用户名或密码错误。", "danger")
        app.logger.warning("登录失败，用户名：%s", username)

    return render_template("login.html", url_prefix=URL_PREFIX)


@app.route(f"{URL_PREFIX}/logout")
@login_required
def logout():
    username = current_user.id
    logout_user()
    session.clear()
    app.logger.info("用户登出：%s", username)
    return redirect(url_for("login"))


@app.route(f"{URL_PREFIX}/settings", methods=["GET", "POST"])
@login_required
def settings():
    username = current_user.id
    error = None
    success = None

    if request.method == "POST":
        old_pwd = request.form.get("old_password", "")
        new_pwd = request.form.get("new_password", "")
        confirm_pwd = request.form.get("confirm_password", "")

        if not old_pwd or not new_pwd or not confirm_pwd:
            error = "所有字段均为必填。"
        elif new_pwd != confirm_pwd:
            error = "新密码两次输入不一致。"
        elif len(new_pwd) < 6:
            error = "新密码长度不能少于 6 位。"
        else:
            conn = _open_db()
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
            conn.close()

            if not row or not check_password_hash(row["password_hash"], old_pwd):
                error = "原密码不正确。"
            else:
                conn = _open_db()
                conn.execute(
                    "UPDATE users SET password_hash = ?, password_changed_at = ? "
                    "WHERE username = ?",
                    (
                        generate_password_hash(new_pwd),
                        datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
                        username,
                    ),
                )
                conn.commit()
                conn.close()
                success = "密码修改成功。"
                app.logger.info("用户 %s 修改了密码。", username)

    return render_template(
        "settings.html",
        username=username,
        error=error,
        success=success,
        url_prefix=URL_PREFIX,
    )


@app.route(f"{URL_PREFIX}/forgot", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    sent = False
    if request.method == "POST":
        username = request.form.get("username", "").strip()

        if not username:
            flash("请输入用户名。", "warning")
            return render_template("forgot.html", url_prefix=URL_PREFIX)

        conn = _open_db()
        row = conn.execute(
            "SELECT username FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if not row:
            # 用户不存在也显示成功，防止用户名枚举攻击
            flash(
                "如果该用户名存在，重置链接已发送至管理员邮箱。",
                "info",
            )
            app.logger.info("密码重置请求（用户不存在）：%s", username)
            return render_template("forgot.html", sent=True, url_prefix=URL_PREFIX)

        # 生成新密码
        new_pwd = gen_password()
        token = secrets.token_urlsafe(32)

        conn = _open_db()
        conn.execute(
            "UPDATE users SET password_hash = ?, password_changed_at = ? WHERE username = ?",
            (
                generate_password_hash(new_pwd),
                datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
                username,
            ),
        )
        # 记录 token（目前通过邮件直接告知新密码，跳过 token 校验页面）
        conn.execute(
            "INSERT OR REPLACE INTO reset_tokens (token, expires_at, created_at) VALUES (?, ?, ?)",
            (
                token,
                (datetime.now(tz=CST) + timedelta(hours=1)).timestamp(),
                datetime.now(tz=CST).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        conn.close()

        # 发送邮件
        sent_ok = send_reset_email(new_pwd)
        app.logger.info(
            "密码已重置，用户：%s，邮件发送：%s", username, "成功" if sent_ok else "失败"
        )

        flash(
            "如果该用户名存在，重置链接已发送至管理员邮箱。",
            "info",
        )
        return render_template("forgot.html", sent=True, url_prefix=URL_PREFIX)

    return render_template("forgot.html", sent=False, url_prefix=URL_PREFIX)


def worker():
    init_db()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    for line in tail_f(LOG_PATH):
        event = parse_line(line)
        if event:
            insert_event(conn, event)


@app.route(f"{URL_PREFIX}/")
@login_required
def index():
    db = get_db()

    recent = db.execute(
        """
        SELECT * FROM events
        ORDER BY event_ts DESC
        LIMIT 1000
        """
    ).fetchall()

    top_ip = db.execute(
        """
        SELECT client_ip, COUNT(*) AS cnt
        FROM events
        GROUP BY client_ip
        ORDER BY cnt DESC
        LIMIT 20
        """
    ).fetchall()

    top_host = db.execute(
        """
        SELECT host, COUNT(*) AS cnt
        FROM events
        WHERE host IS NOT NULL AND host != ''
        GROUP BY host
        ORDER BY cnt DESC
        LIMIT 20
        """
    ).fetchall()

    status_stats = db.execute(
        """
        SELECT status, COUNT(*) AS cnt
        FROM events
        GROUP BY status
        ORDER BY cnt DESC
        """
    ).fetchall()

    category_stats = db.execute(
        """
        SELECT category, COUNT(*) AS cnt
        FROM events
        GROUP BY category
        ORDER BY cnt DESC
        """
    ).fetchall()

    total = db.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]

    return render_template(
        "index.html",
        recent=recent,
        top_ip=top_ip,
        top_host=top_host,
        status_stats=status_stats,
        category_stats=category_stats,
        total=total,
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


@app.route(f"{URL_PREFIX}/detail/ip/<ip>")
@login_required
def detail_ip(ip):
    db = get_db()
    rows = db.execute(
        """
        SELECT * FROM events
        WHERE client_ip = ?
        ORDER BY event_ts DESC
        LIMIT 500
        """,
        (ip,),
    ).fetchall()
    return render_template(
        "detail.html",
        title=f"IP 详情: {ip}",
        rows=rows,
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


@app.route(f"{URL_PREFIX}/detail/host/<path:host>")
@login_required
def detail_host(host):
    db = get_db()
    rows = db.execute(
        """
        SELECT * FROM events
        WHERE host = ?
        ORDER BY event_ts DESC
        LIMIT 500
        """,
        (host,),
    ).fetchall()
    return render_template(
        "detail.html",
        title=f"域名详情: {host}",
        rows=rows,
        url_prefix=URL_PREFIX,
        current_user=current_user,
    )


def _start_background_threads():
    """
    在 WSGI 服务器（gunicorn / uWSGI）或直接运行时都能启动后台线程。
    使用标记变量防止 debug 模式下 Reloader 导致的重复启动。
    """
    import os
    # gunicorn 多 worker 时每个 worker 都会执行，属于预期行为（各自独立清理）
    # Werkzeug debug reloader 下跳过子进程：只在主进程启动
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return
    t_worker = threading.Thread(target=worker, daemon=True)
    t_worker.start()
    t_cleanup = threading.Thread(target=cleanup_scheduler, daemon=True)
    t_cleanup.start()


# 模块被 WSGI 服务器 import 时自动建表、启动后台线程（gunicorn / uWSGI）
init_db()
_start_background_threads()


if __name__ == "__main__":
    # init_db 与后台线程已在模块级 _start_background_threads() 中启动
    app.run(host="127.0.0.1", port=5001, debug=False)