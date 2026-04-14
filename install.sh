#!/bin/bash
#
# Squid 管理面板 - Ubuntu 一键安装脚本
# 支持 Ubuntu 20.04/22.04/24.04
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
APP_NAME="Squid ACL Dashboard"
APP_DIR="/opt/squid_acl_dashboard"
APP_USER="root"
SQUID_LOG_PATH="/var/log/squid/access.log"
DEFAULT_PORT="5001"
DEFAULT_SECRET_KEY=$(openssl rand -hex 32)

# 打印带颜色的信息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否为 root 用户
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "请使用 root 用户运行此脚本"
        exit 1
    fi
}

# 检查系统版本
check_os() {
    if [[ ! -f /etc/os-release ]]; then
        print_error "无法识别操作系统"
        exit 1
    fi

    source /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        print_error "此脚本仅支持 Ubuntu 系统"
        exit 1
    fi

    UBUNTU_VERSION=$(echo "$VERSION_ID" | cut -d. -f1)
    if [[ "$UBUNTU_VERSION" -lt 20 ]]; then
        print_error "需要 Ubuntu 20.04 或更高版本"
        exit 1
    fi

    print_info "检测到 Ubuntu $VERSION_ID"
}

# 安装系统依赖
install_system_deps() {
    print_info "正在更新软件包列表..."
    apt-get update -qq

    print_info "正在安装系统依赖..."
    apt-get install -y -qq \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        squid \
        apache2-utils \
        curl \
        wget \
        git \
        openssl \
        net-tools

    print_success "系统依赖安装完成"
}

# 安装和配置 Squid
setup_squid() {
    print_info "正在配置 Squid..."

    # 创建 Squid 日志目录
    mkdir -p /var/log/squid
    chown -R proxy:proxy /var/log/squid 2>/dev/null || chown -R root:root /var/log/squid

    # 创建 Squid 配置目录
    mkdir -p /etc/squid

    # 创建必要的配置文件（如果不存在）
    touch /etc/squid/allow.txt
    touch /etc/squid/passwd
    touch /etc/squid/ip_group_a.txt
    touch /etc/squid/ip_group_b.txt
    touch /etc/squid/ip_group_c.txt
    touch /etc/squid/ip_group_d.txt

    # 设置权限
    chmod 640 /etc/squid/passwd
    chmod 644 /etc/squid/allow.txt
    chmod 644 /etc/squid/ip_group_*.txt

    print_success "Squid 基础配置完成"
}

# 获取用户输入
get_user_input() {
    print_info "请配置应用参数（直接回车使用默认值）："

    read -p "应用安装目录 [$APP_DIR]: " input_dir
    APP_DIR=${input_dir:-$APP_DIR}

    read -p "应用监听端口 [$DEFAULT_PORT]: " input_port
    APP_PORT=${input_port:-$DEFAULT_PORT}

    read -p "管理员邮箱（用于接收密码重置邮件）: " ADMIN_EMAIL
    while [[ -z "$ADMIN_EMAIL" ]]; do
        print_warning "管理员邮箱不能为空"
        read -p "管理员邮箱: " ADMIN_EMAIL
    done

    read -p "SMTP 服务器地址 [smtp.163.com]: " SMTP_HOST
    SMTP_HOST=${SMTP_HOST:-smtp.163.com}

    read -p "SMTP 端口 [587]: " SMTP_PORT
    SMTP_PORT=${SMTP_PORT:-587}

    read -p "SMTP 用户名（发件邮箱）: " SMTP_USER
    while [[ -z "$SMTP_USER" ]]; do
        print_warning "SMTP 用户名不能为空"
        read -p "SMTP 用户名: " SMTP_USER
    done

    read -sp "SMTP 授权码（非邮箱密码）: " SMTP_PASS
    echo
    while [[ -z "$SMTP_PASS" ]]; do
        print_warning "SMTP 授权码不能为空"
        read -sp "SMTP 授权码: " SMTP_PASS
        echo
    done

    # 确认信息
    echo
    print_info "配置信息确认："
    echo "  安装目录: $APP_DIR"
    echo "  监听端口: $APP_PORT"
    echo "  管理员邮箱: $ADMIN_EMAIL"
    echo "  SMTP 服务器: $SMTP_HOST:$SMTP_PORT"
    echo "  SMTP 用户名: $SMTP_USER"
    echo

    read -p "确认安装? [Y/n]: " confirm
    if [[ "$confirm" =~ ^[Nn]$ ]]; then
        print_info "安装已取消"
        exit 0
    fi
}

# 下载项目代码
download_project() {
    print_info "正在下载项目代码..."

    # 如果目录已存在，先备份
    if [[ -d "$APP_DIR" ]]; then
        BACKUP_DIR="${APP_DIR}.backup.$(date +%Y%m%d%H%M%S)"
        print_warning "目录已存在，备份到 $BACKUP_DIR"
        mv "$APP_DIR" "$BACKUP_DIR"
    fi

    # 创建应用目录
    mkdir -p "$APP_DIR"
    cd "$APP_DIR"

    # 从 GitHub 下载最新代码
    if command -v git &> /dev/null; then
        git clone --depth 1 https://github.com/vampireh/squid_acl_dashboard_open.git .
    else
        # 如果没有 git，使用 wget 下载 zip
        wget -q https://github.com/vampireh/squid_acl_dashboard_open/archive/refs/heads/master.zip -O /tmp/squid_acl_dashboard.zip
        apt-get install -y -qq unzip
        unzip -q /tmp/squid_acl_dashboard.zip -d /tmp/
        mv /tmp/squid_acl_dashboard_open-master/* "$APP_DIR/"
        rm -rf /tmp/squid_acl_dashboard.zip /tmp/squid_acl_dashboard_open-master
    fi

    # 创建必要的目录
    mkdir -p "$APP_DIR/logs"

    print_success "项目代码下载完成"
}

# 安装 Python 依赖
install_python_deps() {
    print_info "正在安装 Python 依赖..."

    cd "$APP_DIR"

    # 创建虚拟环境
    python3 -m venv venv
    source venv/bin/activate

    # 升级 pip
    pip install --quiet --upgrade pip

    # 安装依赖
    if [[ -f requirements.txt ]]; then
        pip install --quiet -r requirements.txt
    else
        # 如果没有 requirements.txt，安装默认依赖
        pip install --quiet Flask Werkzeug Flask-Login gunicorn
    fi

    print_success "Python 依赖安装完成"
}

# 配置应用
configure_app() {
    print_info "正在配置应用..."

    cd "$APP_DIR"

    # 修改 app.py 中的配置
    sed -i "s|BASE_DIR = \"/opt/squid_acl_dashboard\"|BASE_DIR = \"$APP_DIR\"|" app.py

    # 检查 Squid 日志路径
    if [[ ! -f "$SQUID_LOG_PATH" ]]; then
        print_warning "Squid 访问日志不存在: $SQUID_LOG_PATH"
        print_info "创建空的日志文件..."
        touch "$SQUID_LOG_PATH"
        chmod 644 "$SQUID_LOG_PATH"
    fi

    # 复制配置文件到 Squid 目录
    if [[ -d "etc/squid" ]]; then
        cp etc/squid/squid.conf /etc/squid/squid.conf 2>/dev/null || print_warning "squid.conf 复制失败，请手动配置"
        cp etc/squid/allow.txt /etc/squid/allow.txt 2>/dev/null || true
        cp etc/squid/passwd /etc/squid/passwd 2>/dev/null || true
        cp etc/squid/ip_group_*.txt /etc/squid/ 2>/dev/null || true
    fi

    # 设置权限
    chmod 640 /etc/squid/passwd 2>/dev/null || true

    print_success "应用配置完成"
}

# 初始化数据库
init_database() {
    print_info "正在初始化数据库..."

    cd "$APP_DIR"
    source venv/bin/activate

    # 运行初始化
    python3 -c "from app import init_db; init_db()"

    print_success "数据库初始化完成"
}

# 创建 Systemd 服务
create_systemd_service() {
    print_info "正在创建 Systemd 服务..."

    cat > /etc/systemd/system/squid-acl-dashboard.service << EOF
[Unit]
Description=Squid ACL Dashboard
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
Environment="SECRET_KEY=$DEFAULT_SECRET_KEY"
Environment="SMTP_HOST=$SMTP_HOST"
Environment="SMTP_PORT=$SMTP_PORT"
Environment="SMTP_USER=$SMTP_USER"
Environment="SMTP_PASS=$SMTP_PASS"
Environment="ADMIN_EMAIL=$ADMIN_EMAIL"
ExecStart=$APP_DIR/venv/bin/gunicorn -w 4 -b 127.0.0.1:$APP_PORT app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # 重载 systemd
    systemctl daemon-reload

    # 启用开机自启
    systemctl enable squid-acl-dashboard

    print_success "Systemd 服务创建完成"
}

# 配置防火墙
configure_firewall() {
    print_info "正在配置防火墙..."

    # 检查 ufw 是否安装
    if command -v ufw &> /dev/null; then
        # 检查 ufw 是否启用
        if ufw status | grep -q "Status: active"; then
            ufw allow $APP_PORT/tcp
            print_info "已开放端口 $APP_PORT"
        else
            print_warning "UFW 未启用，跳过防火墙配置"
        fi
    fi

    print_success "防火墙配置完成"
}

# 启动服务
start_services() {
    print_info "正在启动服务..."

    # 启动 Squid
    systemctl restart squid || systemctl restart squid3 || true

    # 启动应用
    systemctl start squid-acl-dashboard

    # 等待服务启动
    sleep 3

    # 检查服务状态
    if systemctl is-active --quiet squid-acl-dashboard; then
        print_success "服务启动成功"
    else
        print_error "服务启动失败，请检查日志"
        journalctl -u squid-acl-dashboard --no-pager -n 20
        exit 1
    fi
}

# 显示安装结果
show_result() {
    echo
    echo "========================================"
    echo -e "${GREEN}$APP_NAME 安装完成！${NC}"
    echo "========================================"
    echo
    echo "访问地址:"
    echo "  - 本地: http://127.0.0.1:$APP_PORT/squid-acl"
    echo "  - 远程: http://$(hostname -I | awk '{print $1}'):$APP_PORT/squid-acl"
    echo
    echo "默认登录信息:"
    echo "  用户名: admin"
    echo "  密码: admin@123"
    echo
    echo "重要提示:"
    echo "  1. 首次登录后请立即修改默认密码"
    echo "  2. 如需配置 Nginx 反向代理，请参考 README.md"
    echo "  3. 忘记密码功能已配置，重置密码将发送到: $ADMIN_EMAIL"
    echo
    echo "常用命令:"
    echo "  查看状态: systemctl status squid-acl-dashboard"
    echo "  查看日志: journalctl -u squid-acl-dashboard -f"
    echo "  重启服务: systemctl restart squid-acl-dashboard"
    echo "  停止服务: systemctl stop squid-acl-dashboard"
    echo
    echo "配置文件位置:"
    echo "  应用目录: $APP_DIR"
    echo "  数据库: $APP_DIR/acl_dashboard.db"
    echo "  日志: $APP_DIR/logs/"
    echo "  Squid 配置: /etc/squid/"
    echo
    echo "========================================"
}

# 主函数
main() {
    echo "========================================"
    echo "  $APP_NAME - Ubuntu 一键安装脚本"
    echo "========================================"
    echo

    check_root
    check_os
    install_system_deps
    setup_squid
    get_user_input
    download_project
    install_python_deps
    configure_app
    init_database
    create_systemd_service
    configure_firewall
    start_services
    show_result
}

# 运行主函数
main "$@"
