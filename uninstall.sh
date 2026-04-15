#!/bin/bash
# Squid ACL Dashboard 卸载脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 配置
INSTALL_DIR="/opt/squid_acl_dashboard"
SERVICE_NAME="squid-acl-dashboard"

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

# 显示帮助
show_help() {
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════╗
║        Squid ACL Dashboard - 卸载脚本                              ║
╚══════════════════════════════════════════════════════════════════╝

用法:
    sudo ./uninstall.sh [选项]

选项:
    -h, --help          显示此帮助信息
    -y, --yes           跳过确认，直接卸载

说明:
    • 此脚本会停止并禁用服务
    • 删除应用程序目录
    • 删除系统服务文件
    • 删除 Squid 配置（可选）
    • 删除数据库文件（可选）

EOF
}

# 确认卸载
confirm_uninstall() {
    log_warning "========================================"
    log_warning "  即将卸载 Squid ACL Dashboard"
    log_warning "========================================"
    echo ""
    log_warning "将执行以下操作:"
    log_warning "  • 停止并禁用服务"
    log_warning "  • 删除 ${INSTALL_DIR}"
    log_warning "  • 删除 systemd 服务文件"
    echo ""

    if [[ "$SKIP_CONFIRM" != "true" ]]; then
        read -p "确认卸载? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "已取消卸载"
            exit 0
        fi
    fi
}

# 停止服务
stop_service() {
    log_info "停止服务..."

    systemctl stop ${SERVICE_NAME} 2>/dev/null || true
    systemctl disable ${SERVICE_NAME} 2>/dev/null || true

    log_success "服务已停止"
}

# 删除服务文件
remove_service_file() {
    log_info "删除服务文件..."

    rm -f /etc/systemd/system/${SERVICE_NAME}.service
    systemctl daemon-reload

    log_success "服务文件已删除"
}

# 删除应用目录
remove_app_directory() {
    log_info "删除应用目录..."

    if [[ -d ${INSTALL_DIR} ]]; then
        rm -rf ${INSTALL_DIR}
        log_success "应用目录已删除: ${INSTALL_DIR}"
    else
        log_info "应用目录不存在，跳过"
    fi
}

# 删除 Squid 配置（可选）
remove_squid_config() {
    log_info "删除 Squid 配置..."

    rm -f /etc/squid/squid.conf.backup 2>/dev/null || true
    rm -f /etc/squid/passwd 2>/dev/null || true

    log_success "Squid 配置已删除"
}

# 删除数据库（可选）
remove_database() {
    log_info "删除数据库..."

    rm -f /etc/squid/squid_acl.db 2>/dev/null || true

    log_success "数据库已删除"
}

# 删除备份
remove_backups() {
    log_info "删除备份..."

    rm -rf /opt/squid_acl_dashboard_backups 2>/dev/null || true

    log_success "备份已删除"
}

# 主函数
main() {
    local skip_squid=false
    local skip_db=false

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -y|--yes)
                SKIP_CONFIRM="true"
                shift
                ;;
            --keep-squid)
                skip_squid=true
                shift
                ;;
            --keep-db)
                skip_db=true
                shift
                ;;
            *)
                log_error "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done

    # 检查 root 权限
    check_root

    # 确认卸载
    confirm_uninstall

    # 执行卸载步骤
    echo ""
    log_info "开始卸载..."
    echo ""

    stop_service
    remove_service_file
    remove_app_directory

    if [[ "$skip_squid" != "true" ]]; then
        remove_squid_config
    else
        log_info "保留 Squid 配置（--keep-squid）"
    fi

    if [[ "$skip_db" != "true" ]]; then
        remove_database
        remove_backups
    else
        log_info "保留数据库（--keep-db）"
    fi

    echo ""
    log_success "========================================"
    log_success "  卸载完成！"
    log_success "========================================"
    echo ""
    log_info "如需重新安装，请运行:"
    echo "  curl -fsSL https://raw.githubusercontent.com/vampireh/squid_acl_dashboard_open/master/install.sh -o install.sh"
    echo "  sudo bash install.sh"
    echo ""
}

# 运行主函数
main "$@"
