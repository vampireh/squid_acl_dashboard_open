#!/bin/bash
# Squid ACL Dashboard 一键安装脚本 v1.0.2
# 适用于 Ubuntu 20.04/22.04/24.04

set -e

# ============================================
# 配置
# ============================================
INSTALL_DIR="/opt/squid_acl_dashboard"
SERVICE_NAME="squid-acl-dashboard"
GITHUB_REPO="https://github.com/vampireh/squid_acl_dashboard_open.git"
GITHUB_RAW="https://raw.githubusercontent.com/vampireh/squid_acl_dashboard_open/master"
URL_PREFIX="squid-acl"
SQUID_PORT=3128
WEB_PORT=5001

# 默认 SMTP 配置（163邮箱）
SMTP_SERVER="smtp.163.com"
SMTP_PORT=587
SMTP_FROM="noreply@163.com"

# 数据库
DB_NAME="acl_dashboard.db"

# ============================================
# 颜色定义
# ============================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ============================================
# 日志函数
# ============================================
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================
# 检查 root 权限
# ============================================
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "请使用 root 权限运行此脚本"
        exit 1
    fi
}

# ============================================
# 检查 Ubuntu 版本
# ============================================
check_ubuntu_version() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "无法检测操作系统版本"
        exit 1
    fi

    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        log_warning "本脚本主要针对 Ubuntu 设计，其他系统可能需要额外配置"
    fi

    log_info "检测到 Ubuntu ${VERSION_ID}"
}

# ============================================
# 配置防火墙
# ============================================
configure_firewall() {
    log_info "配置防火墙..."

    # 检查 ufw 是否启用
    if command -v ufw &> /dev/null; then
        if systemctl is-active --quiet ufw; then
            ufw allow ${SQUID_PORT}/tcp > /dev/null 2>&1 || true
            ufw allow ${WEB_PORT}/tcp > /dev/null 2>&1 || true
            log_success "防火墙已开放 ${SQUID_PORT} 和 ${WEB_PORT} 端口"
        fi
    fi

    # 云服务器安全组提示
    log_warning "【重要】如果使用云服务器（阿里云/腾讯云等），请在控制台安全组中手动开放以下端口："
    log_warning "  - ${SQUID_PORT}/TCP（Squid 代理）"
    log_warning "  - ${WEB_PORT}/TCP（Web 管理面板）"
}

# ============================================
# 安装系统依赖
# ============================================
install_system_dependencies() {
    log_info "安装系统依赖..."

    export DEBIAN_FRONTEND=noninteractive

    # 检查并安装缺失的依赖
    local packages="python3 python3-pip python3-venv squid apache2-utils git curl wget net-tools ufw ca-certificates squid-common"

    for pkg in $packages; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            log_info "安装 $pkg..."
            apt-get install -y "$pkg" 2>/dev/null || true
        else
            log_info "$pkg 已安装，跳过"
        fi
    done

    log_success "系统依赖安装完成"
}

# ============================================
# 创建应用目录
# ============================================
setup_app_directory() {
    log_info "创建应用目录..."

    mkdir -p ${INSTALL_DIR}
    mkdir -p ${INSTALL_DIR}/logs
    mkdir -p ${INSTALL_DIR}/templates
    mkdir -p ${INSTALL_DIR}/squid_backups

    chown -R root:root ${INSTALL_DIR}
    chmod -R 755 ${INSTALL_DIR}

    log_success "应用目录创建完成: ${INSTALL_DIR}"
}

# ============================================
# 下载项目
# ============================================
download_project() {
    log_info "下载项目文件..."

    local TEMP_DIR=$(mktemp -d)

    if git clone --depth 1 ${GITHUB_REPO} ${TEMP_DIR} 2>/dev/null; then
        # 复制文件（排除 .git 和 runtime 文件）
        rsync -av --exclude='.git' --exclude='logs' --exclude='*.db' --exclude='.env' ${TEMP_DIR}/ ${INSTALL_DIR}/ 2>/dev/null || \
        cp -r ${TEMP_DIR}/* ${INSTALL_DIR}/

        rm -rf ${TEMP_DIR}
        log_success "项目文件下载完成"
    else
        log_error "从 GitHub 下载失败，请检查网络连接"
        exit 1
    fi
}

# ============================================
# 配置 Python 虚拟环境
# ============================================
setup_python_env() {
    log_info "配置 Python 虚拟环境..."

    cd ${INSTALL_DIR}

    # 创建虚拟环境
    python3 -m venv venv
    source venv/bin/activate

    # 升级 pip
    pip install --upgrade pip -q

    # 安装依赖
    pip install -r requirements.txt -q

    deactivate

    log_success "Python 环境配置完成"
}

# ============================================
# 初始化数据库
# ============================================
init_database() {
    log_info "初始化数据库..."

    cd ${INSTALL_DIR}

    # 创建数据库文件
    if [[ ! -f "${INSTALL_DIR}/${DB_NAME}" ]]; then
        source venv/bin/activate
        python3 << 'PYEOF'
import sqlite3
import os

db_path = os.path.join(os.environ.get('INSTALL_DIR', '/opt/squid_acl_dashboard'), 'acl_dashboard.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 创建 events 表
cursor.execute('''
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT,
    event_ts REAL,
    client_ip TEXT,
    status TEXT,
    category TEXT,
    http_code TEXT,
    method TEXT,
    target TEXT,
    host TEXT,
    user_field TEXT,
    hierarchy TEXT,
    content_type TEXT,
    raw_line TEXT,
    created_at TEXT
)
''')

# 创建 proxy_ips 表
cursor.execute('''
CREATE TABLE IF NOT EXISTS proxy_ips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_addr TEXT UNIQUE,
    ip_group TEXT,
    description TEXT,
    created_at TEXT
)
''')

# 创建 proxy_users 表
cursor.execute('''
CREATE TABLE IF NOT EXISTS proxy_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    password_hash TEXT,
    user_group TEXT,
    user_realname TEXT,
    created_at TEXT
)
''')

# 创建 users 表
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT,
    password_changed_at TEXT,
    created_at TEXT
)
''')

# 创建 reset_tokens 表
cursor.execute('''
CREATE TABLE IF NOT EXISTS reset_tokens (
    token TEXT PRIMARY KEY,
    expires_at REAL,
    created_at TEXT
)
''')

# 创建索引
cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_time ON events(event_time)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_ip ON events(client_ip)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_proxy_ips_group ON proxy_ips(ip_group)')

conn.commit()
conn.close()

print(f"数据库创建成功: {db_path}")
PYEOF
        deactivate
    fi

    chown root:root ${INSTALL_DIR}/${DB_NAME}
    chmod 644 ${INSTALL_DIR}/${DB_NAME}

    log_success "数据库初始化完成"
}

# ============================================
# 配置 Squid
# ============================================
configure_squid() {
    log_info "配置 Squid 代理..."

    # 备份原有配置
    if [[ -f /etc/squid/squid.conf ]] && [[ ! -f /etc/squid/squid.conf.backup ]]; then
        cp /etc/squid/squid.conf /etc/squid/squid.conf.backup
    fi

    # 创建 Squid 配置
    cat > /etc/squid/squid.conf << 'EOF'
# Squid 配置文件 - Squid ACL Dashboard
# 版本: 1.0.2

# 端口配置
http_port 3128

# 认证配置
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic children 5
auth_param basic realm Squid Proxy
auth_param basic credentialsttl 2 hours

# IP 分组文件
acl ip_group_a src "/etc/squid/ip_group_a.txt"
acl ip_group_b src "/etc/squid/ip_group_b.txt"
acl ip_group_c src "/etc/squid/ip_group_c.txt"
acl ip_group_d src "/etc/squid/ip_group_d.txt"

# 用户分组
acl user_group_b proxy_auth "/etc/squid/passwd"
acl user_group_d proxy_auth "/etc/squid/passwd"

# 白名单域名
acl allow_domains dstdomain "/etc/squid/allow.txt"

# 访问控制
# A 类：无密码，全域
http_access allow ip_group_a

# B 类：需要密码，全域
http_access allow ip_group_b user_group_b

# C 类：无密码，仅白名单
http_access allow ip_group_c allow_domains

# D 类：需要密码，仅白名单
http_access allow ip_group_d user_group_d allow_domains

# 拒绝其他所有
http_access deny all

# 日志配置
logformat squid %tl %ts.%03tu %6tr %>a %Ss/%03>Hs %<st %rm %ru %[un %Sh/%<a %mt
access_log /var/log/squid/access.log squid

# 其他配置
cache deny all
dns_v4_first on
visible_hostname squid-acl-dashboard

# 连接优化
client_db on
max_filedescriptors 65536
EOF

    # 创建 IP 分组文件
    touch /etc/squid/ip_group_a.txt
    touch /etc/squid/ip_group_b.txt
    touch /etc/squid/ip_group_c.txt
    touch /etc/squid/ip_group_d.txt

    # 创建白名单文件
    touch /etc/squid/allow.txt

    # 创建密码文件
    touch /etc/squid/passwd
    # 获取 squid 用户的组
    local squid_group=$(id -gn squid 2>/dev/null || echo "root")
    chown root:$squid_group /etc/squid/passwd 2>/dev/null || chown root:root /etc/squid/passwd
    chmod 640 /etc/squid/passwd

    # 设置 Squid 日志
    touch /var/log/squid/access.log
    local proxy_group=$(id -gn proxy 2>/dev/null || echo "root")
    chown proxy:$proxy_group /var/log/squid/access.log 2>/dev/null || true

    log_success "Squid 配置完成"
}

# ============================================
# 配置 Systemd 服务
# ============================================
setup_systemd_service() {
    log_info "配置系统服务..."

    cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=Squid ACL Dashboard
After=network.target

[Service]
Type=notify
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn -w 4 -b 0.0.0.0:${WEB_PORT} app:app
Restart=always
RestartSec=10

# 安全设置
NoNewPrivileges=false
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}

    log_success "系统服务配置完成"
}

# ============================================
# 创建 Squid 命令软链接
# ============================================
create_squid_symlink() {
    log_info "创建 Squid 命令软链接..."

    # 查找 squid 命令
    local SQUID_PATH=""
    for path in /usr/sbin/squid /usr/bin/squid /usr/local/sbin/squid /usr/local/bin/squid; do
        if [[ -f "$path" ]]; then
            SQUID_PATH="$path"
            break
        fi
    done

    if [[ -n "$SQUID_PATH" ]]; then
        ln -sf "$SQUID_PATH" /usr/local/bin/squid 2>/dev/null || true
        log_success "Squid 命令软链接已创建"
    else
        log_warning "未找到 Squid 命令"
    fi
}

# ============================================
# 创建管理命令
# ============================================
create_admin_scripts() {
    log_info "创建管理脚本..."

    # 创建密码重置脚本
    cat > ${INSTALL_DIR}/reset_password.py << 'PYEOF'
#!/usr/bin/env python3
"""
Squid ACL Dashboard 密码重置工具
用于通过命令行重置管理员密码
"""
import sys
import sqlite3
import secrets
import string
from datetime import datetime
from werkzeug.security import generate_password_hash

INSTALL_DIR = "/opt/squid_acl_dashboard"
DB_PATH = f"{INSTALL_DIR}/acl_dashboard.db"

def generate_password(length=16):
    """生成随机密码"""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

def reset_password(username, new_password=None):
    """重置用户密码"""
    if new_password is None:
        new_password = generate_password()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 检查用户是否存在
    cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
    if not cursor.fetchone():
        print(f"错误：用户 '{username}' 不存在")
        print("\n可用用户：")
        cursor.execute("SELECT username FROM users")
        for row in cursor.fetchall():
            print(f"  - {row[0]}")
        conn.close()
        return False

    # 更新密码
    password_hash = generate_password_hash(new_password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE users SET password_hash = ?, password_changed_at = ? WHERE username = ?",
        (password_hash, now, username)
    )
    conn.commit()
    conn.close()

    print(f"✓ 密码已重置")
    print(f"  用户名：{username}")
    print(f"  新密码：{new_password}")
    print(f"  时间：{now}")
    return True

def list_users():
    """列出所有用户"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, password_changed_at, created_at FROM users")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("没有找到用户")
        return

    print("用户列表：")
    print("-" * 50)
    for username, pwd_changed, created in rows:
        print(f"  用户名：{username}")
        print(f"  密码修改：{pwd_changed or '从未'}")
        print(f"  创建时间：{created or '未知'}")
        print("-" * 50)

def main():
    if len(sys.argv) < 2:
        print("用法：")
        print("  重置密码：reset_password.py <用户名> [新密码]")
        print("  列出用户：reset_password.py --list")
        print("  显示帮助：reset_password.py --help")
        sys.exit(1)

    if sys.argv[1] == "--list":
        list_users()
    elif sys.argv[1] == "--help":
        print(__doc__)
    else:
        username = sys.argv[1]
        new_password = sys.argv[2] if len(sys.argv) > 2 else None
        reset_password(username, new_password)

if __name__ == "__main__":
    main()
PYEOF

    chmod +x ${INSTALL_DIR}/reset_password.py
    log_success "管理脚本创建完成"
}

# ============================================
# 启动服务
# ============================================
start_services() {
    log_info "启动服务..."

    # 启动 Squid
    systemctl restart squid
    sleep 1

    # 启动 Dashboard
    systemctl restart ${SERVICE_NAME}
    sleep 2

    # 检查服务状态
    if systemctl is-active --quiet squid; then
        log_success "Squid 服务运行正常"
    else
        log_error "Squid 服务启动失败"
    fi

    if systemctl is-active --quiet ${SERVICE_NAME}; then
        log_success "Dashboard 服务运行正常"
    else
        log_error "Dashboard 服务启动失败"
        journalctl -u ${SERVICE_NAME} -n 10 --no-pager
    fi
}

# ============================================
# 显示安装信息
# ============================================
show_install_info() {
    local server_ip=$(hostname -I | awk '{print $1}')

    echo ""
    echo "========================================"
    echo "     Squid ACL Dashboard 安装完成"
    echo "========================================"
    echo ""
    echo "访问地址："
    echo -e "  ${GREEN}http://${server_ip}:${WEB_PORT}/${URL_PREFIX}/${NC}"
    echo ""
    echo "默认账号："
    echo "  用户名：admin"
    echo "  密 码：admin"
    echo ""
    echo -e "${YELLOW}【安全提示】请立即修改默认密码！${NC}"
    echo ""
    echo "常用命令："
    echo "  查看 Dashboard 状态: systemctl status ${SERVICE_NAME}"
    echo "  重启 Dashboard: systemctl restart ${SERVICE_NAME}"
    echo "  查看 Dashboard 日志: journalctl -u ${SERVICE_NAME} -f"
    echo "  查看 Squid 状态: systemctl status squid"
    echo "  重启 Squid: systemctl restart squid"
    echo ""
    echo "管理工具："
    echo "  重置密码: sudo python3 ${INSTALL_DIR}/reset_password.py <用户名> [新密码]"
    echo "  列出用户: sudo python3 ${INSTALL_DIR}/reset_password.py --list"
    echo "  系统更新: sudo ${INSTALL_DIR}/update.sh"
    echo "  卸载系统: sudo ${INSTALL_DIR}/uninstall.sh"
    echo ""
    echo "配置文件："
    echo "  应用目录: ${INSTALL_DIR}"
    echo "  Squid 配置: /etc/squid/squid.conf"
    echo "  数据库: ${INSTALL_DIR}/${DB_NAME}"
    echo ""
    echo "默认 SMTP 配置："
    echo "  SMTP 服务器: ${SMTP_SERVER}"
    echo "  SMTP 端口: ${SMTP_PORT}"
    echo "  发件人: ${SMTP_FROM}"
    echo ""
    log_warning "【重要】如果无法访问，请检查："
    log_warning "  1. 云服务器安全组是否开放 ${WEB_PORT} 端口"
    log_warning "  2. 本地防火墙: sudo ufw status"
    echo "========================================"
}

# ============================================
# 主函数
# ============================================
main() {
    log_info "开始安装 Squid ACL Dashboard v1.0.2..."
    log_info "安装目录: ${INSTALL_DIR}"

    check_root
    check_ubuntu_version

    configure_firewall
    install_system_dependencies
    setup_app_directory
    download_project
    setup_python_env
    init_database
    configure_squid
    setup_systemd_service
    create_squid_symlink
    create_admin_scripts
    start_services

    show_install_info

    log_success "安装完成！"
}

main "$@"
