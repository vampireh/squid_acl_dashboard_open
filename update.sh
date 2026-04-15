#!/bin/bash
# Squid ACL Dashboard 更新脚本
# 用于从 GitHub 拉取最新代码并更新

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 配置
INSTALL_DIR="/opt/squid_acl_dashboard"
BACKUP_DIR="/opt/squid_acl_dashboard_backups"
GITHUB_REPO="https://github.com/vampireh/squid_acl_dashboard_open.git"
SERVICE_NAME="squid-acl-dashboard"
URL_PREFIX="squid-acl"

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
║        Squid ACL Dashboard - 更新脚本                             ║
╚══════════════════════════════════════════════════════════════════╝

用法:
    ./update.sh [选项]

选项:
    -h, --help          显示此帮助信息
    -b, --backup        仅备份当前版本
    -r, --restore       从备份恢复
    -f, --force         强制更新（跳过确认）
    --branch <名称>     指定要更新的分支（默认: master）

示例:
    # 常规更新
    sudo ./update.sh

    # 强制更新（不提示确认）
    sudo ./update.sh --force

    # 仅备份当前版本
    sudo ./update.sh --backup

    # 从备份恢复
    sudo ./update.sh --restore

说明:
    • 更新前会自动备份当前版本
    • 更新失败可以自动回滚
    • 数据库文件不会被覆盖
    • 配置文件会保留用户修改
EOF
}

# 创建备份
create_backup() {
    log_info "正在创建备份..."

    mkdir -p ${BACKUP_DIR}

    local backup_name="backup_$(date +%Y%m%d_%H%M%S)"
    local backup_path="${BACKUP_DIR}/${backup_name}"

    # 创建备份目录
    mkdir -p ${backup_path}

    # 备份文件
    cp -r ${INSTALL_DIR}/* ${backup_path}/ 2>/dev/null || true

    # 备份数据库（单独备份）
    if [[ -f ${INSTALL_DIR}/squid_acl.db ]]; then
        cp ${INSTALL_DIR}/squid_acl.db ${backup_path}/squid_acl.db.backup
        log_info "数据库已备份"
    fi

    # 备份配置文件
    if [[ -f /etc/systemd/system/${SERVICE_NAME}.service ]]; then
        cp /etc/systemd/system/${SERVICE_NAME}.service ${backup_path}/
        log_info "服务配置已备份"
    fi

    echo ${backup_path} > ${BACKUP_DIR}/latest_backup.txt
    log_success "备份完成: ${backup_path}"

    # 清理旧备份（保留最近10个）
    ls -t ${BACKUP_DIR}/backup_* 2>/dev/null | tail -n +11 | xargs -r rm -rf

    echo ${backup_path}
}

# 恢复备份
restore_backup() {
    log_info "正在恢复备份..."

    if [[ ! -f ${BACKUP_DIR}/latest_backup.txt ]]; then
        log_error "没有找到备份文件"
        exit 1
    fi

    local backup_path=$(cat ${BACKUP_DIR}/latest_backup.txt)

    if [[ ! -d ${backup_path} ]]; then
        log_error "备份目录不存在: ${backup_path}"

        # 显示可用备份
        log_info "可用备份列表:"
        ls -lt ${BACKUP_DIR}/backup_* 2>/dev/null | head -10
        exit 1
    fi

    log_warning "即将从备份恢复: ${backup_path}"
    read -p "确认恢复? (y/N): " -n 1 -r
    echo

    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "已取消恢复"
        exit 0
    fi

    # 停止服务
    systemctl stop ${SERVICE_NAME} 2>/dev/null || true

    # 恢复文件
    cp -r ${backup_path}/* ${INSTALL_DIR}/

    # 恢复数据库
    if [[ -f ${backup_path}/squid_acl.db.backup ]]; then
        cp ${backup_path}/squid_acl.db.backup ${INSTALL_DIR}/squid_acl.db
        log_info "数据库已恢复"
    fi

    # 恢复服务配置
    if [[ -f ${backup_path}/${SERVICE_NAME}.service ]]; then
        cp ${backup_path}/${SERVICE_NAME}.service /etc/systemd/system/
        systemctl daemon-reload
    fi

    # 重启服务
    systemctl start ${SERVICE_NAME}

    log_success "恢复完成"
}

# 检查服务状态
check_service() {
    log_info "检查服务状态..."

    if systemctl is-active --quiet ${SERVICE_NAME}; then
        log_success "服务运行正常"
        return 0
    else
        log_error "服务未运行"
        systemctl status ${SERVICE_NAME} --no-pager
        return 1
    fi
}

# 创建 Squid 命令软链接
create_squid_symlink() {
    log_info "检查 Squid 命令软链接..."

    # 查找 squid 命令位置
    SQUID_PATH=""
    for path in /usr/sbin/squid /usr/bin/squid /usr/local/sbin/squid /usr/local/bin/squid; do
        if [[ -f "$path" ]]; then
            SQUID_PATH="$path"
            break
        fi
    done

    if [[ -n "$SQUID_PATH" ]]; then
        # 创建软链接到 /usr/local/bin
        ln -sf "$SQUID_PATH" /usr/local/bin/squid 2>/dev/null || true
        log_success "Squid 命令软链接已创建: /usr/local/bin/squid"
    fi
}

# 执行更新
perform_update() {
    local force=$1
    local branch=${2:-master}

    log_info "开始更新 Squid ACL Dashboard..."
    log_info "目标分支: ${branch}"

    # 确认更新
    if [[ "$force" != "true" ]]; then
        read -p "确认更新? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "已取消更新"
            exit 0
        fi
    fi

    # 创建备份
    local backup_path=$(create_backup)

    # 停止服务
    log_info "停止服务..."
    systemctl stop ${SERVICE_NAME} 2>/dev/null || true

    # 进入安装目录
    cd ${INSTALL_DIR}

    # 检查是否是 git 仓库
    if [[ -d .git ]]; then
        log_info "从 GitHub 拉取更新..."

        # 保存本地修改（如果有）
        git stash 2>/dev/null || true

        # 拉取最新代码
        git fetch origin
        git checkout ${branch}
        git pull origin ${branch}

        log_success "代码更新完成"
    else
        log_info "使用临时目录下载更新..."

        # 创建临时目录
        local temp_dir=$(mktemp -d)

        # 克隆仓库
        git clone --depth 1 --branch ${branch} ${GITHUB_REPO} ${temp_dir}

        # 复制文件（保留数据库和配置）
        cp -r ${temp_dir}/* ${INSTALL_DIR}/

        # 清理临时目录
        rm -rf ${temp_dir}

        log_success "代码更新完成"
    fi

    # 更新 Python 依赖
    log_info "更新 Python 依赖..."
    if [[ -f "${INSTALL_DIR}/venv/bin/activate" ]]; then
        source ${INSTALL_DIR}/venv/bin/activate
        pip install -r ${INSTALL_DIR}/requirements.txt -q
        deactivate
    else
        log_warning "虚拟环境不存在，跳过依赖更新"
    fi

    # 设置权限
    chown -R root:root ${INSTALL_DIR}
    chmod -R 755 ${INSTALL_DIR}
    chmod +x ${INSTALL_DIR}/reset_password.py 2>/dev/null || true
    chmod +x ${INSTALL_DIR}/update.sh 2>/dev/null || true

    # 重建 Squid 命令软链接
    create_squid_symlink

    # 启动服务
    log_info "启动服务..."
    systemctl start ${SERVICE_NAME}

    # 等待服务启动
    sleep 3

    # 检查服务状态
    if check_service; then
        log_success "更新成功完成！"

        # 获取服务器 IP
        local server_ip=$(hostname -I | awk '{print $1}')
        echo ""
        echo "========================================"
        echo -e "访问地址: ${GREEN}http://${server_ip}:5001/${URL_PREFIX}/${NC}"
        echo "========================================"

        # 清理旧备份
        log_info "清理旧备份..."
        ls -t ${BACKUP_DIR}/backup_* 2>/dev/null | tail -n +6 | xargs -r rm -rf

        return 0
    else
        log_error "服务启动失败，准备回滚..."

        # 回滚
        log_info "正在回滚到备份版本..."
        cp -r ${backup_path}/* ${INSTALL_DIR}/
        systemctl start ${SERVICE_NAME}

        log_warning "已回滚到备份版本"
        return 1
    fi
}

# 显示版本信息
show_version() {
    log_info "当前版本信息:"

    if [[ -d ${INSTALL_DIR}/.git ]]; then
        cd ${INSTALL_DIR}
        echo "  Git 分支: $(git branch --show-current 2>/dev/null || echo 'N/A')"
        echo "  最新提交: $(git log -1 --oneline 2>/dev/null || echo 'N/A')"
        echo "  提交时间: $(git log -1 --format=%cd --date=iso 2>/dev/null || echo 'N/A')"
    else
        echo "  不是 Git 仓库，无法获取版本信息"
    fi

    echo "  安装目录: ${INSTALL_DIR}"
    echo "  服务状态: $(systemctl is-active ${SERVICE_NAME} 2>/dev/null || echo 'unknown')"
    echo "  访问地址: http://$(hostname -I | awk '{print $1}'):5001/${URL_PREFIX}/"
}

# 主函数
main() {
    local force="false"
    local branch="master"

    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -b|--backup)
                check_root
                create_backup
                exit 0
                ;;
            -r|--restore)
                check_root
                restore_backup
                exit 0
                ;;
            -f|--force)
                force="true"
                shift
                ;;
            --branch)
                branch="$2"
                shift 2
                ;;
            -v|--version)
                show_version
                exit 0
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

    # 检查安装目录
    if [[ ! -d ${INSTALL_DIR} ]]; then
        log_error "安装目录不存在: ${INSTALL_DIR}"
        log_info "请先运行安装脚本"
        exit 1
    fi

    # 执行更新
    perform_update ${force} ${branch}
}

# 运行主函数
main "$@"
