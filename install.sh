#!/bin/bash
# Squid ACL Dashboard 一键安装脚本 (Ubuntu)
# 版本: v1.0.4
# 支持 Ubuntu 20.04/22.04/24.04

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
INSTALL_DIR="/opt/squid_acl_dashboard"
SERVICE_NAME="squid-acl-dashboard"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
DEFAULT_ADMIN_USER="admin"
DEFAULT_ADMIN_PASS="admin123"
DEFAULT_SECRET_KEY=$(openssl rand -hex 32)

# 日志函数
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

# 检查 root 权限
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "请使用 root 权限运行此脚本"
        exit 1
    fi
}

# 检测系统版本
detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$NAME
        VERSION=$VERSION_ID
        log_info "检测到系统: $OS $VERSION"
    else
        log_error "无法检测操作系统版本"
        exit 1
    fi
    
    if [[ "$OS" != *"Ubuntu"* ]]; then
        log_warning "此脚本专为 Ubuntu 设计，在其他系统上可能无法正常工作"
        read -p "是否继续? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# 安装系统依赖
install_dependencies() {
    log_info "正在更新软件包列表..."
    apt-get update -qq
    
    log_info "正在安装系统依赖..."
    apt-get install -y -qq \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        squid \
        apache2-utils \
        sqlite3 \
        curl \
        wget \
        git \
        openssl \
        net-tools \
        ufw
    
    log_success "系统依赖安装完成"
}

# 配置 Squid
configure_squid() {
    log_info "正在配置 Squid..."
    
    # 创建 Squid 配置目录
    mkdir -p /etc/squid
    
    # 备份原始配置
    if [[ -f /etc/squid/squid.conf ]]; then
        cp /etc/squid/squid.conf /etc/squid/squid.conf.backup.$(date +%Y%m%d%H%M%S)
        log_info "已备份原始 Squid 配置"
    fi
    
    # 创建密码文件
    touch /etc/squid/passwd
    chown proxy:proxy /etc/squid/passwd
    chmod 640 /etc/squid/passwd
    
    # 创建日志目录
    mkdir -p /var/log/squid
    chown proxy:proxy /var/log/squid
    
    # 创建缓存目录
    mkdir -p /var/spool/squid
    chown proxy:proxy /var/spool/squid
    
    # 生成 Squid 配置文件
    cat > /etc/squid/squid.conf << 'EOF'
# Squid ACL Dashboard 生成的配置文件

# 基础配置
http_port 3128

# 认证配置 - Ubuntu 路径
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic realm Squid Proxy
auth_param basic credentialsttl 2 hours

# ACL 定义
acl authenticated proxy_auth REQUIRED
acl SSL_ports port 443
acl Safe_ports port 80          # http
acl Safe_ports port 21          # ftp
acl Safe_ports port 443         # https
acl Safe_ports port 70          # gopher
acl Safe_ports port 210         # wais
acl Safe_ports port 1025-65535  # unregistered ports
acl Safe_ports port 280         # http-mgmt
acl Safe_ports port 488         # gss-http
acl Safe_ports port 591         # filemaker
acl Safe_ports port 777         # multiling http
acl CONNECT method CONNECT

# 访问控制规则
http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow authenticated
http_access deny all

# 日志配置
cache_log /var/log/squid/cache.log
access_log /var/log/squid/access.log squid

# 缓存配置
cache_dir ufs /var/spool/squid 100 16 256
coredump_dir /var/spool/squid

# DNS 配置
dns_nameservers 8.8.8.8 8.8.4.4

# 性能调优
maximum_object_size 1024 MB
cache_mem 256 MB
maximum_object_size_in_memory 512 KB
EOF
    
    # 初始化 Squid 缓存
    log_info "正在初始化 Squid 缓存..."
    squid -z 2>/dev/null || true
    
    # 启动 Squid
    log_info "正在启动 Squid 服务..."
    systemctl restart squid || service squid restart || squid
    systemctl enable squid 2>/dev/null || true
    
    log_success "Squid 配置完成"
}

# 从 GitHub 下载项目
download_project() {
    log_info "正在从 GitHub 下载项目..."
    
    local GITHUB_REPO="https://github.com/vampireh/squid_acl_dashboard_open.git"
    local TEMP_DIR=$(mktemp -d)
    
    # 克隆仓库
    if git clone --depth 1 ${GITHUB_REPO} ${TEMP_DIR} 2>/dev/null; then
        log_success "项目下载完成"
        
        # 复制文件到安装目录（排除 venv 目录，避免覆盖）
        # 使用 rsync 或选择性复制，排除 venv
        if command -v rsync &> /dev/null; then
            rsync -av --exclude='venv' --exclude='.git' ${TEMP_DIR}/ ${INSTALL_DIR}/
        else
            # 手动复制，排除 venv
            for item in ${TEMP_DIR}/* ${TEMP_DIR}/.[!.]* ${TEMP_DIR}/..?*; do
                if [[ -e "$item" ]]; then
                    local basename=$(basename "$item")
                    if [[ "$basename" != "venv" && "$basename" != ".git" ]]; then
                        cp -r "$item" ${INSTALL_DIR}/
                    fi
                fi
            done
        fi
        
        # 清理临时目录
        rm -rf ${TEMP_DIR}
        
        log_success "项目文件已复制到 ${INSTALL_DIR}"
    else
        log_warning "从 GitHub 下载失败，尝试使用本地文件..."
        
        # 如果当前目录有项目文件，复制过去
        if [[ -f "app.py" ]]; then
            log_info "复制当前目录的项目文件..."
            # 排除 venv 目录
            for item in * .[!.]* ..?*; do
                if [[ -e "$item" && "$item" != "venv" && "$item" != ".git" ]]; then
                    cp -r "$item" ${INSTALL_DIR}/
                fi
            done
        else
            log_error "未检测到项目文件，安装失败"
            exit 1
        fi
    fi
}

# 创建应用目录
setup_app_directory() {
    log_info "正在创建应用目录..."
    
    # 创建目录
    mkdir -p ${INSTALL_DIR}
    
    # 从 GitHub 下载或复制本地文件
    download_project
    
    # 创建 templates 目录（如果不存在）
    mkdir -p ${INSTALL_DIR}/templates
    
    # 设置权限
    chown -R root:root ${INSTALL_DIR}
    chmod -R 755 ${INSTALL_DIR}
    
    # 确保虚拟环境中的可执行文件有执行权限
    if [[ -d ${INSTALL_DIR}/venv/bin ]]; then
        chmod +x ${INSTALL_DIR}/venv/bin/* 2>/dev/null || true
    fi
    
    # 设置脚本可执行权限
    chmod +x ${INSTALL_DIR}/reset_password.py 2>/dev/null || true
    chmod +x ${INSTALL_DIR}/update.sh 2>/dev/null || true
    
    log_success "应用目录创建完成: ${INSTALL_DIR}"
}

# 创建 Python 虚拟环境
setup_python_env() {
    log_info "正在创建 Python 虚拟环境..."
    
    cd ${INSTALL_DIR}
    
    # 如果 venv 已存在，先删除（避免冲突）
    if [[ -d venv ]]; then
        rm -rf venv
    fi
    
    # 创建虚拟环境
    python3 -m venv venv
    
    # 激活虚拟环境并安装依赖
    source venv/bin/activate
    
    # 升级 pip
    pip install --upgrade pip -q
    
    # 安装依赖（直接安装，不通过 requirements.txt）
    pip install flask==3.0.0 flask-login==0.6.3 werkzeug==3.0.1 gunicorn==21.2.0 -q
    
    # 验证 gunicorn 是否安装成功
    if [[ ! -f venv/bin/gunicorn ]]; then
        log_error "gunicorn 安装失败，请检查网络连接"
        exit 1
    fi
    
    deactivate
    
    log_success "Python 虚拟环境配置完成"
}

# 创建 Systemd 服务
create_systemd_service() {
    log_info "正在创建 Systemd 服务..."
    
    # 获取 SMTP 配置
    read -p "请输入 SMTP 服务器地址 (默认: smtp.gmail.com): " SMTP_HOST
    SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}
    
    read -p "请输入 SMTP 端口 (默认: 587): " SMTP_PORT
    SMTP_PORT=${SMTP_PORT:-587}
    
    read -p "请输入 SMTP 用户名: " SMTP_USER
    SMTP_USER=${SMTP_USER:-""}
    
    read -s -p "请输入 SMTP 密码: " SMTP_PASS
    echo
    SMTP_PASS=${SMTP_PASS:-""}
    
    read -p "请输入管理员邮箱 (用于接收密码重置邮件): " ADMIN_EMAIL
    ADMIN_EMAIL=${ADMIN_EMAIL:-"admin@example.com"}
    
    cat > ${SERVICE_FILE} << EOF
[Unit]
Description=Squid ACL Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin"
Environment="SECRET_KEY=${DEFAULT_SECRET_KEY}"
Environment="SMTP_HOST=${SMTP_HOST}"
Environment="SMTP_PORT=${SMTP_PORT}"
Environment="SMTP_USER=${SMTP_USER}"
Environment="SMTP_PASS=${SMTP_PASS}"
Environment="ADMIN_EMAIL=${ADMIN_EMAIL}"
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn -w 4 -b 0.0.0.0:5001 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    # 重载 systemd
    systemctl daemon-reload
    
    # 启用服务
    systemctl enable ${SERVICE_NAME}
    
    log_success "Systemd 服务创建完成"
}

# 初始化数据库
init_database() {
    log_info "正在初始化数据库..."
    
    cd ${INSTALL_DIR}
    source venv/bin/activate
    
    # 运行数据库初始化
    python3 -c "
import sys
sys.path.insert(0, '${INSTALL_DIR}')
from app import init_db
init_db()
print('数据库初始化完成')
"
    
    deactivate
    
    log_success "数据库初始化完成"
}

# 配置防火墙
configure_firewall() {
    log_info "正在配置防火墙..."
    
    # 检查 ufw 是否启用
    if command -v ufw &> /dev/null; then
        UFW_STATUS=$(ufw status | grep -i "Status: active" || true)
        
        if [[ -n "$UFW_STATUS" ]]; then
            log_info "检测到 ufw 已启用，正在开放 5001 端口..."
            ufw allow 5001/tcp
            log_success "已开放 5001 端口"
        else
            log_warning "ufw 未启用，跳过防火墙配置"
            log_info "如需启用防火墙，请运行: ufw allow 5001/tcp"
        fi
    else
        log_warning "未检测到 ufw，请手动配置防火墙开放 5001 端口"
    fi
    
    # 提示云服务器安全组配置
    echo ""
    log_warning "【重要】如果您使用的是云服务器（阿里云、腾讯云、AWS等），"
    log_warning "请在云服务器控制台的安全组/防火墙中开放 5001 端口！"
    echo ""
}

# 启动服务
start_services() {
    log_info "正在启动服务..."
    
    # 启动 Dashboard 服务
    systemctl start ${SERVICE_NAME}
    
    # 等待服务启动
    sleep 3
    
    # 检查服务状态
    if systemctl is-active --quiet ${SERVICE_NAME}; then
        log_success "Dashboard 服务启动成功"
    else
        log_error "Dashboard 服务启动失败，请检查日志:"
        systemctl status ${SERVICE_NAME} --no-pager
        exit 1
    fi
    
    # 检查 Squid 状态
    if systemctl is-active --quiet squid 2>/dev/null || pgrep -x squid > /dev/null; then
        log_success "Squid 服务运行正常"
    else
        log_warning "Squid 服务未运行，尝试启动..."
        systemctl start squid 2>/dev/null || squid &
    fi
}

# 显示安装信息
show_install_info() {
    SERVER_IP=$(hostname -I | awk '{print $1}')
    
    echo ""
    echo "========================================"
    echo -e "${GREEN}Squid ACL Dashboard 安装完成!${NC}"
    echo "========================================"
    echo ""
    echo -e "访问地址: ${GREEN}http://${SERVER_IP}:5001${NC}"
    echo ""
    echo "默认管理员账号:"
    echo -e "  用户名: ${YELLOW}admin${NC}"
    echo -e "  密码: ${YELLOW}admin123${NC}"
    echo ""
    echo "Squid 代理地址:"
    echo -e "  ${YELLOW}http://${SERVER_IP}:3128${NC}"
    echo ""
    echo "常用命令:"
    echo "  查看 Dashboard 状态: systemctl status ${SERVICE_NAME}"
    echo "  重启 Dashboard: systemctl restart ${SERVICE_NAME}"
    echo "  查看日志: journalctl -u ${SERVICE_NAME} -f"
    echo "  查看 Squid 状态: systemctl status squid"
    echo ""
    echo "命令行工具:"
    echo "  重置用户密码: python3 ${INSTALL_DIR}/reset_password.py <用户名> <新密码>"
    echo "  列出所有用户: python3 ${INSTALL_DIR}/reset_password.py --list"
    echo "  系统更新: ${INSTALL_DIR}/update.sh"
    echo "  查看版本: ${INSTALL_DIR}/update.sh --version"
    echo ""
    echo "配置文件位置:"
    echo "  应用目录: ${INSTALL_DIR}"
    echo "  Squid 配置: /etc/squid/squid.conf"
    echo "  密码文件: /etc/squid/passwd"
    echo ""
    log_warning "【安全提示】"
    log_warning "1. 请及时修改默认管理员密码"
    log_warning "2. 建议配置 Nginx 反向代理并启用 HTTPS"
    log_warning "3. 如果无法访问，请检查防火墙和安全组设置"
    log_warning "   - 本地防火墙: ufw status"
    log_warning "   - 云服务器安全组: 需在控制台开放 5001 端口"
    echo ""
    echo "========================================"
}

# 主函数
main() {
    echo "========================================"
    echo "Squid ACL Dashboard 一键安装脚本"
    echo "========================================"
    echo ""
    
    check_root
    detect_os
    
    log_info "开始安装..."
    
    install_dependencies
    configure_squid
    setup_app_directory
    setup_python_env
    create_systemd_service
    init_database
    configure_firewall
    start_services
    
    show_install_info
}

# 运行主函数
main
