#!/bin/bash
# Squid ACL Dashboard 卸载脚本 v1.0.2
# 用于完全卸载 Squid ACL Dashboard

set -e

# ============================================
# 配置
# ============================================
INSTALL_DIR="/opt/squid_acl_dashboard"
SERVICE_NAME="squid-acl-dashboard"
BACKUP_DIR="/opt/squid_acl_dashboard_backups"

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
# 显示帮助
# ============================================
show_help() {
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════╗
║        Squid ACL Dashboard - 卸载脚本                           ║
╚══════════════════════════════════════════════════════════════════╝

用法:
    ./uninstall.sh [选项]

选项:
    -h, --help          显示此帮助信息
    --keep-squid        保留 Squid 配置（不清除 Squid）
    --keep-db           保留数据库备份
    --keep-logs         保留日志文件

示例:
    # 完全卸载
    sudo ./uninstall.sh

    # 保留 Squid 配置
    sudo ./uninstall.sh --keep-squid

    # 保留数据库
    sudo ./uninstall.sh --keep-db

    # 保留数据库和日志
    sudo ./uninstall.sh --keep-db --keep-logs
EOF
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
# 创建备份
# ============================================
create_backup() {
    log_info "正在创建备份..."

    mkdir -p ${BACKUP_DIR}
    local backup_name="uninstall_backup_$(date +%Y%m%d_%H%M%S)"
    local backup_path="${BACKUP_DIR}/${backup_name}"

    mkdir -p ${backup_path}

    # 备份应用目录
    if [[ -d ${INSTALL_DIR} ]]; then
        cp -r ${INSTALL_DIR} ${backup_path}/ 2>/dev/null || true
    fi

    # 备份 Squid 配置
    if [[ -f /etc/squid/squid.conf ]]; then
        cp /etc/squid/squid.conf ${backup_path}/ 2>/dev/null || true
    fi

    log_success "备份已保存: ${backup_path}"
    log_info "如需恢复，请联系技术支持"
}

# ============================================
# 停止服务
# ============================================
stop_services() {
    log_info "停止服务..."

    # 停止 Dashboard
    systemctl stop ${SERVICE_NAME} 2>/dev/null || true
    systemctl disable ${SERVICE_NAME} 2>/dev/null || true

    # 停止 Squid（可选）
    if [[ "$KEEP_SQUID" != "true" ]]; then
        systemctl stop squid 2>/dev/null || true
        systemctl disable squid 2>/dev/null || true
    fi

    log_success "服务已停止"
}

# ============================================
# 卸载应用
# ============================================
uninstall_app() {
    log_info "卸载应用..."

    # 删除应用目录
    if [[ -d ${INSTALL_DIR} ]]; then
        rm -rf ${INSTALL_DIR}
        log_info "应用目录已删除: ${INSTALL_DIR}"
    fi

    # 删除 Systemd 服务文件
    if [[ -f /etc/systemd/system/${SERVICE_NAME}.service ]]; then
        rm -f /etc/systemd/system/${SERVICE_NAME}.service
        systemctl daemon-reload
        log_info "Systemd 服务已删除"
    fi

    log_success "应用卸载完成"
}

# ============================================
# 卸载 Squid
# ============================================
uninstall_squid() {
    if [[ "$KEEP_SQUID" == "true" ]]; then
        log_info "保留 Squid 配置..."
        return
    fi

    log_info "卸载 Squid..."

    # 删除 Squid 配置
    rm -f /etc/squid/squid.conf
    rm -f /etc/squid/squid.conf.backup
    rm -f /etc/squid/ip_group_*.txt
    rm -f /etc/squid/passwd
    rm -f /etc/squid/allow.txt
    rmdir /etc/squid 2>/dev/null || true

    # 删除 Squid 日志
    rm -f /var/log/squid/access.log
    rmdir /var/log/squid 2>/dev/null || true

    log_success "Squid 配置已清除"
}

# ============================================
# 清理残留文件
# ============================================
cleanup_residuals() {
    log_info "清理残留文件..."

    # 删除备份目录
    if [[ "$KEEP_DB" != "true" ]] && [[ -d ${BACKUP_DIR} ]]; then
        rm -rf ${BACKUP_DIR}
        log_info "备份目录已清理"
    fi

    # 删除日志
    if [[ "$KEEP_LOGS" != "true" ]]; then
        find /var/log -name "*squid*" -type f 2>/dev/null | xargs rm -f 2>/dev/null || true
    fi

    log_success "残留文件清理完成"
}

# ============================================
# 显示卸载结果
# ============================================
show_result() {
    echo ""
    echo "========================================"
    echo "     Squid ACL Dashboard 卸载完成"
    echo "========================================"
    echo ""
    echo "已卸载组件："
    echo "  ✓ Dashboard 应用"
    echo "  ✓ Systemd 服务"
    if [[ "$KEEP_SQUID" != "true" ]]; then
        echo "  ✓ Squid 代理"
    else
        echo "  - Squid 代理（保留）"
    fi
    echo ""
    if [[ "$KEEP_DB" == "true" ]]; then
        echo "  - 数据库（已备份）"
    fi
    if [[ "$KEEP_LOGS" == "true" ]]; then
        echo "  - 日志文件（已保留）"
    fi
    echo ""
    echo "备份位置（如有）：${BACKUP_DIR}"
    echo "========================================"
}

# ============================================
# 主函数
# ============================================
main() {
    # 解析参数
    KEEP_SQUID="false"
    KEEP_DB="false"
    KEEP_LOGS="false"

    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            --keep-squid)
                KEEP_SQUID="true"
                shift
                ;;
            --keep-db)
                KEEP_DB="true"
                shift
                ;;
            --keep-logs)
                KEEP_LOGS="true"
                shift
                ;;
            *)
                log_error "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done

    check_root

    echo ""
    log_warning "即将卸载 Squid ACL Dashboard"
    log_warning "此操作将删除："
    log_warning "  - 应用目录: ${INSTALL_DIR}"
    log_warning "  - Systemd 服务: ${SERVICE_NAME}"
    if [[ "$KEEP_SQUID" != "true" ]]; then
        log_warning "  - Squid 配置: /etc/squid"
    fi
    echo ""

    read -p "确认卸载? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "已取消卸载"
        exit 0
    fi

    create_backup
    stop_services
    uninstall_app
    uninstall_squid
    cleanup_residuals
    show_result

    log_success "卸载完成！"
}

main "$@"
