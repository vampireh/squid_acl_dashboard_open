# Squid ACL Dashboard 项目文档

> 本文档为 Squid ACL Dashboard 项目的完整技术文档，涵盖项目简介、技术架构、功能模块、数据模型、部署指南和运维手册。

---

## 一、项目简介

### 1.1 项目概述

**Squid ACL Dashboard** 是一个基于 Flask 的 **Squid 代理访问控制管理平台**，同时也是一套**代理日志可视化分析系统**。

项目旨在为高校、企业等机构提供一套完整的上网行为管理解决方案，通过 Web 界面便捷地管理代理服务器的访问控制策略，同时为管理员和用户提供直观的日志查询和统计分析功能。

### 1.2 核心功能

本项目包含两个核心功能模块：

| 功能模块 | 面向用户 | 说明 |
|---------|---------|------|
| **代理上网行为管理** | 管理员 | 管理四类 IP 白名单、两类用户账号、白名单域名池，编辑 squid.conf 配置文件并重载生效 |
| **代理日志看板** | 最终用户/管理员 | 实时解析 Squid 访问日志，展示个人访问记录、域名统计、支持按时间/IP/域名搜索 |

### 1.3 功能特性

- 🔐 **用户认证管理** - 支持多用户、权限分级
- 🌐 **IP 分组管理** - 灵活配置 IP 访问策略（A/B/C/D 四类分组）
- 📊 **访问日志** - 实时监控代理访问情况，支持统计分析和搜索
- 🔄 **Squid 集成** - 自动同步配置到 Squid，支持语法检查和配置重载
- 📧 **邮件通知** - 支持 SMTP 配置，密码找回功能
- 🎨 **响应式设计** - 支持桌面和移动端访问
- ⚡ **自动化运维** - 自动备份、自动更新、自动清理过期日志

---

## 二、技术架构

### 2.1 技术栈

| 层次 | 技术 | 说明 |
|------|------|------|
| Web 框架 | Flask 2.0.3 + Werkzeug 2.0.3 | 轻量级 Python Web 框架 |
| 用户认证 | Flask-Login 0.5.0 + Werkzeug 密码哈希 | Session 管理与密码安全 |
| 数据库 | SQLite（`acl_dashboard.db`） | 本地文件存储 |
| 日志来源 | `/var/log/squid/access.log` | Squid 访问日志 |
| 代理服务端 | Squid 缓存代理（Linux） | 代理服务 |
| 前端 | Jinja2 模板 + 原生 HTML/CSS/JS | 无框架依赖 |
| 部署方式 | systemd 服务 `squid-acl-dashboard` | 系统服务管理 |
| Web 服务器 | Gunicorn 4 worker processes | WSGI 应用服务器 |
| URL 前缀 | `/squid-acl` | 由 `URL_PREFIX` 常量控制 |

### 2.2 系统要求

- **操作系统**：Ubuntu 20.04/22.04/24.04（推荐）
- **Python 版本**：Python 3.8+
- **Squid 版本**：Squid 4.x/5.x
- **内存**：最低 512MB，推荐 1GB 以上
- **磁盘**：根据日志量预留足够的存储空间

### 2.3 目录结构

```
/opt/squid_acl_dashboard/
├── app.py                  # 主应用文件
├── requirements.txt        # Python 依赖
├── install.sh              # 一键安装脚本
├── update.sh               # 系统更新脚本
├── reset_password.py       # 密码重置工具
├── squid_acl.db            # SQLite 数据库
├── venv/                   # Python 虚拟环境
├── templates/              # Jinja2 模板目录
│   ├── login.html
│   ├── forgot_password.html
│   ├── index.html
│   └── ...
├── ip_lists/               # IP 列表文件目录
├── logs/                   # 应用日志目录
└── squid_backups/          # Squid 配置备份目录

/etc/squid/                 # Squid 配置目录
├── squid.conf              # Squid 主配置
├── passwd                  # HTPasswd 用户文件
├── ip_group_a.txt          # A 类 IP 分组
├── ip_group_b.txt          # B 类 IP 分组
├── ip_group_c.txt          # C 类 IP 分组
├── ip_group_d.txt          # D 类 IP 分组
└── allow.txt               # 白名单域名列表

/var/log/squid/
└── access.log              # Squid 访问日志
```

---

## 三、数据模型

### 3.1 数据库表结构

#### 3.1.1 events（访问日志）

日志解析后存入 SQLite，字段对应 Squid access.log 格式。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| event_time | TEXT | 北京时间可读时间（如 `2026-04-14 16:30:00`） |
| event_ts | REAL | Unix 时间戳（北京时间） |
| client_ip | TEXT | 客户端 IP |
| status | TEXT | Squid 状态码（如 `TCP_MISS/200`） |
| category | TEXT | 分类：`SUCCESS` / `ACL` / `ERROR` |
| http_code | TEXT | HTTP 状态码（200/403/407 等） |
| method | TEXT | 请求方法（GET/POST/CONNECT 等） |
| target | TEXT | 目标 URL（原始格式） |
| host | TEXT | 解析出的域名/主机 |
| user_field | TEXT | Squid 日志中的用户字段 |
| hierarchy | TEXT | 上游代理层级 |
| content_type | TEXT | Content-Type |
| raw_line | TEXT | 原始日志行 |
| created_at | TEXT | 入库时间 |

**日志解析正则（LOG_RE）**：
```
ts.elapsed client_ip status size method target user hierarchy content_type
```

**status → category 分类逻辑**：
- `ACL`：`TCP_DENIED/403`、`TCP_DENIED/407`、`TAG_NONE/403`
- `SUCCESS`：`TCP_MISS/200`、`TCP_HIT/200`、`TCP_MEM_HIT/200`、`TCP_TUNNEL/200` 等
- `ERROR`：`NONE_NONE/000`、`ERR_CONNECT_FAIL`、`ERR_DNS_FAIL` 等

#### 3.1.2 proxy_ips（IP 分组）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| ip_addr | TEXT UNIQUE | IP 地址 |
| ip_group | TEXT | 分组：`A` / `B` / `C` / `D` |
| description | TEXT | 描述 |
| created_at | TEXT | 入库时间 |

#### 3.1.3 proxy_users（代理账号）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| username | TEXT UNIQUE | 用户名 |
| password_hash | TEXT | 密码哈希（HTPasswd 格式） |
| user_group | TEXT | 分组：`B` / `D` |
| user_realname | TEXT | 真实姓名（可选） |
| created_at | TEXT | 入库时间 |

#### 3.1.4 users（系统管理员账号）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| username | TEXT UNIQUE | 管理员用户名 |
| password | TEXT | 密码哈希 |
| email | TEXT | 邮箱地址 |
| is_admin | INTEGER | 是否为管理员（1=是，0=否） |
| created_at | TEXT | 创建时间 |

#### 3.1.5 reset_tokens（密码重置令牌）

| 字段 | 类型 | 说明 |
|------|------|------|
| token | TEXT PRIMARY KEY | 重置令牌 |
| expires_at | REAL | 过期时间戳 |
| created_at | TEXT | 创建时间 |

### 3.2 IP 分组机制

Squid 通过 IP 分组实现差异化代理访问权限，分组逻辑在 squid.conf 中定义：

| 分组 | IP 来源文件 | 认证 | 权限 |
|------|------------|------|------|
| **A 类** | `ip_group_a.txt` | 无需密码 | 全域网段（无白名单限制） |
| **B 类** | `ip_group_b.txt` | 需要密码 | 全域网段 |
| **C 类** | `ip_group_c.txt` | 无需密码 | **仅白名单域名**（受 allow.txt 限制） |
| **D 类** | `ip_group_d.txt` | 需要密码 | **仅白名单域名** |

**重要说明**：真实访问权限由**客户端 IP** 决定，不是用户名。proxy_users 表的 user_group 字段是管理用途，用于在页面上按组展示账号。

---

## 四、功能模块详解

### 4.1 日志看板（用户面向）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/squid-acl/` | GET | 首页看板：今日统计、访问趋势图、最近访问记录 |
| `/squid-acl/detail/ip/<ip>` | GET | 某 IP 的所有访问记录（分页，支持时间过滤） |
| `/squid-acl/detail/host/<path:host>` | GET | 某域名的所有访问记录（分页，支持时间过滤） |

### 4.2 配置管理（管理员面向）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/squid-acl/proxy` | GET | 配置管理首页 |
| `/squid-acl/proxy/ips` | GET/POST | IP 分组管理（A/B/C/D 四类，增删改查，同步文件） |
| `/squid-acl/proxy/allow` | GET/POST | 白名单域名管理（allow.txt，增删改） |
| `/squid-acl/proxy/users` | GET/POST | 用户账号管理（B/D 类，含用户名+真实姓名） |
| `/squid-acl/proxy/conf` | GET/POST | squid.conf 编辑器（语法高亮 + 保存） |
| `/squid-acl/proxy/conf/check` | POST | 检查 squid.conf 语法（`squid -k parse`） |
| `/squid-acl/proxy/conf/reload` | POST | 重载 Squid 配置（`squid -k reconfigure`） |
| `/squid-acl/proxy/conf/backup/<name>` | GET | 下载配置备份 |

### 4.3 用户认证

| 路由 | 方法 | 说明 |
|------|------|------|
| `/squid-acl/login` | GET/POST | 登录 |
| `/squid-acl/logout` | GET | 登出 |
| `/squid-acl/settings` | GET/POST | 修改登录密码 |
| `/squid-acl/forgot` | GET/POST | 忘记密码（发送邮件重置链接） |

---

## 五、部署指南

### 5.1 一键安装（推荐）

支持 Ubuntu 20.04/22.04/24.04

```bash
# 下载安装脚本
curl -fsSL https://raw.githubusercontent.com/vampireh/squid_acl_dashboard_open/master/install.sh -o install.sh

# 运行安装脚本（需要 root 权限）
sudo bash install.sh
```

安装完成后，访问 `http://<服务器IP>:5001` 即可使用。

**默认管理员账号**：
- 用户名：`admin`
- 密码：`admin123`

**安装后可用命令**：
```bash
# 重置用户密码（当邮件找回不可用时）
sudo python3 /opt/squid_acl_dashboard/reset_password.py admin newpassword

# 系统更新（从 GitHub 拉取最新代码）
sudo /opt/squid_acl_dashboard/update.sh
```

### 5.2 手动安装

#### 5.2.1 安装系统依赖

```bash
sudo apt-get update
sudo apt-get install -y squid apache2-utils python3 python3-pip python3-venv sqlite3 curl ufw
```

#### 5.2.2 创建安装目录和虚拟环境

```bash
sudo mkdir -p /opt/squid_acl_dashboard
cd /opt/squid_acl_dashboard
sudo python3 -m venv venv
source venv/bin/activate
```

#### 5.2.3 安装 Python 依赖

```bash
pip install flask==3.0.0 flask-login==0.6.3 werkzeug==3.0.1 gunicorn==21.2.0
```

#### 5.2.4 上传应用代码并初始化数据库

将 `app.py` 上传到 `/opt/squid_acl_dashboard/` 目录，然后运行数据库初始化。

#### 5.2.5 配置防火墙

```bash
sudo ufw allow 5001/tcp
sudo ufw allow 3128/tcp
```

**注意**：如果服务器在云环境（阿里云、腾讯云、AWS等），还需要在**云服务器安全组/防火墙**中开放 5001 和 3128 端口。

#### 5.2.6 创建 Systemd 服务

```bash
sudo tee /etc/systemd/system/squid-acl-dashboard.service > /dev/null << EOF
[Unit]
Description=Squid ACL Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/squid_acl_dashboard
Environment="PATH=/opt/squid_acl_dashboard/venv/bin"
Environment="SECRET_KEY=$(openssl rand -hex 32)"
ExecStart=/opt/squid_acl_dashboard/venv/bin/gunicorn -w 4 -b 0.0.0.0:5001 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

#### 5.2.7 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable squid-acl-dashboard
sudo systemctl start squid-acl-dashboard
```

### 5.3 SMTP 配置（可选）

如需启用密码找回功能，需要配置 SMTP。修改 Systemd 服务文件：

```bash
sudo nano /etc/systemd/system/squid-acl-dashboard.service
```

在 `[Service]` 部分添加环境变量：

```ini
[Service]
Environment="SMTP_HOST=smtp.example.com"
Environment="SMTP_PORT=587"
Environment="SMTP_USER=your-email@example.com"
Environment="SMTP_PASS=your-password"
Environment="ADMIN_EMAIL=admin@example.com"
```

然后重载并重启服务：

```bash
sudo systemctl daemon-reload
sudo systemctl restart squid-acl-dashboard
```

**常用邮箱 SMTP 设置**：

| 邮箱服务商 | SMTP 服务器 | 端口 |
|-----------|------------|------|
| Gmail | smtp.gmail.com | 587 |
| 企业邮箱 | smtp.example.com | 587 |
| 163邮箱 | smtp.163.com | 25/587 |
| Outlook | smtp.office365.com | 587 |
| 阿里云 | smtp.aliyun.com | 25/465 |

---

## 六、自动化特性

### 6.1 Git 自动化部署

本地代码目录 `git push` → 服务器裸仓库 `post-receive` hook → 自动 checkout 代码 + 保护数据库/日志 + 重启服务

钩子路径：`/opt/git/squid_acl_dashboard.git/hooks/post-receive`

### 6.2 后台数据清理

- 每天北京时间凌晨 3 点（`CLEANUP_HOUR=3`）自动清理超期日志
- 默认保留 30 天（`KEEP_DAYS=30`）
- 清理后执行 `VACUUM` 压缩数据库

### 6.3 日志实时 tail

- 看板首页实时 tail Squid access.log（后台线程，5秒间隔）
- 推送日志到前端 JS（WebSocket 或轮询）

### 6.4 文件 ↔ 数据库同步

- `sync_ips_from_file()`：从 `ip_group_*.txt` 文件导入 IP 到 proxy_ips 表
- `sync_ips_to_file()`：从 proxy_ips 表导出 IP 到文件
- `sync_users_from_passwd()`：从 `/etc/squid/passwd` 导入账号
- 用户变更后同步写回 `passwd` 文件（HTPasswd 格式）

### 6.5 邮件重置密码

- 生成随机 16 位密码
- 通过 SMTP 发送重置邮件
- 令牌 1 小时有效期

---

## 七、关键配置常量

`app.py` 中的核心配置常量：

```python
BASE_DIR      = "/opt/squid_acl_dashboard"   # 应用根目录
DB_PATH       = "/opt/squid_acl_dashboard/acl_dashboard.db"
LOG_PATH      = "/var/log/squid/access.log"  # Squid 日志
URL_PREFIX    = "/squid-acl"                 # URL 前缀
SQUID_DIR     = "/etc/squid"                 # Squid 配置目录
SQUID_CONF    = "/etc/squid/squid.conf"     # Squid 主配置
SQUID_BACKUP_DIR = "/opt/squid_acl_dashboard/squid_backups"

KEEP_DAYS     = 30    # 日志保留天数
CLEANUP_HOUR  = 3     # 清理任务执行时间（北京时间）
CST           = timezone(timedelta(hours=8))  # 北京时区
```

---

## 八、运维手册

### 8.1 常用命令

```bash
# 查看服务状态
sudo systemctl status squid-acl-dashboard

# 查看实时日志
sudo journalctl -u squid-acl-dashboard -f

# 重启服务
sudo systemctl restart squid-acl-dashboard

# 停止服务
sudo systemctl stop squid-acl-dashboard

# 查看 Squid 状态
sudo systemctl status squid

# 查看 Squid 日志
sudo tail -f /var/log/squid/access.log
```

### 8.2 命令行工具

#### 8.2.1 密码重置工具 (reset_password.py)

当邮件找回功能不可用时，root 用户可以通过命令行重置用户密码。

```bash
# 重置指定用户密码
sudo python3 /opt/squid_acl_dashboard/reset_password.py admin newpassword123

# 列出所有用户
sudo python3 /opt/squid_acl_dashboard/reset_password.py --list

# 显示帮助
sudo python3 /opt/squid_acl_dashboard/reset_password.py --help
```

#### 8.2.2 更新工具 (update.sh)

用于从 GitHub 拉取最新代码并自动更新系统。

```bash
# 常规更新（会提示确认）
sudo /opt/squid_acl_dashboard/update.sh

# 强制更新（跳过确认）
sudo /opt/squid_acl_dashboard/update.sh --force

# 仅备份当前版本
sudo /opt/squid_acl_dashboard/update.sh --backup

# 从备份恢复（更新失败时使用）
sudo /opt/squid_acl_dashboard/update.sh --restore

# 查看当前版本信息
sudo /opt/squid_acl_dashboard/update.sh --version
```

### 8.3 排障指南

#### 8.3.1 无法访问管理面板

**排查步骤**：
```bash
# 1. 检查服务状态
sudo systemctl status squid-acl-dashboard

# 2. 检查端口监听（应该显示 0.0.0.0:5001）
sudo netstat -tlnp | grep 5001

# 3. 检查防火墙
sudo ufw status

# 4. 查看应用日志
sudo journalctl -u squid-acl-dashboard -f

# 5. 本地测试
curl http://127.0.0.1:5001/
```

**常见原因**：
- 服务未启动：检查 `systemctl status`，查看日志中的错误
- 端口未监听：确认 Gunicorn 绑定的是 `0.0.0.0:5001` 而不是 `127.0.0.1:5001`
- 防火墙拦截：检查 ufw 状态和云服务器安全组
- 端口冲突：检查是否有其他程序占用 5001 端口

#### 8.3.2 服务启动失败 (status=203/EXEC)

**原因**：Gunicorn 未找到或路径错误

**解决**：
```bash
# 检查 gunicorn 是否存在
ls -la /opt/squid_acl_dashboard/venv/bin/gunicorn

# 如果不存在，重新安装
source /opt/squid_acl_dashboard/venv/bin/activate
pip install gunicorn==21.2.0

# 重启服务
sudo systemctl restart squid-acl-dashboard
```

#### 8.3.3 数据库锁定错误

**解决**：
```bash
# 停止服务
sudo systemctl stop squid-acl-dashboard

# 检查并删除可能存在的锁文件
ls -la /opt/squid_acl_dashboard/*.db*
sudo rm -f /opt/squid_acl_dashboard/*.db-journal

# 重启服务
sudo systemctl start squid-acl-dashboard
```

#### 8.3.4 "未找到 squid 命令" 错误

**原因**：Squid 命令不在系统的 PATH 环境变量中

**解决**：
```bash
# 创建软链接到 PATH
sudo ln -s /usr/sbin/squid /usr/local/bin/squid

# 重启服务
sudo systemctl daemon-reload
sudo systemctl restart squid-acl-dashboard
```

#### 8.3.5 Squid 认证失败

**排查**：
```bash
# 1. 检查密码文件
sudo cat /etc/squid/passwd

# 2. 检查文件权限
ls -la /etc/squid/passwd

# 3. 检查认证程序路径
ls -la /usr/lib/squid/basic_ncsa_auth

# 4. 手动测试认证
echo "admin:admin123" | /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
# 输出 OK 表示成功
```

### 8.4 生产环境建议

1. **使用 Nginx 反向代理**
   - 启用 HTTPS
   - 配置域名访问
   - 隐藏 5001 端口

2. **安全配置**
   - 修改默认管理员密码
   - 配置 SMTP 用于密码找回
   - 限制管理面板访问 IP
   - 定期备份数据库

3. **监控告警**
   - 配置服务监控
   - 设置日志轮转
   - 监控磁盘空间

---

## 九、已知的架构注意点

1. **Python 版本兼容**：代码中 `subprocess.run()` 不可使用 `capture_output=True`（Python 3.6 不支持），需使用 `stdout=subprocess.PIPE, stderr=subprocess.PIPE` 替代。

2. **北京时间强制**：无论服务器系统时区如何，应用层强制使用 UTC+8（`CST`）。

3. **数据库保护**：服务器上的 `acl_dashboard.db` 和 `logs/` 目录在 git push 时由 post-receive hook 备份/恢复，不被覆盖。

4. **Squid 服务名**：`systemctl restart squid-acl-dashboard`（不是 squid）。

5. **HTPasswd 格式**：passwd 文件使用 Apache `htpasswd -b` 格式，`username:password_hash`。

6. **URL 前缀**：`/squid-acl`（由常量 `URL_PREFIX` 控制），修改后需同步更新 Nginx 反向代理配置。

---

## 十、快速修改指南

### 10.1 修改 URL 前缀

修改 `app.py` 第 23 行：
```python
URL_PREFIX = "/squid-acl"  # 改为新前缀
```
同时需更新 Nginx 反向代理配置。

### 10.2 增加 IP 分组（如增加 E 类）

1. 在 `app.py` 的 `IP_FILES` 字典中增加一项
2. 在 `IP_GROUP_DESC` 中增加描述
3. 修改 squid.conf 增加对应 ACL 规则
4. 在前端模板（如 `proxy_ips.html`）中增加分组选项卡

### 10.3 修改日志保留天数

修改 `app.py` 中 `KEEP_DAYS` 常量（默认 30 天）：
```python
KEEP_DAYS = 60  # 改为 60 天
```

### 10.4 增加新的日志分类

在 `classify_status()` 函数中添加新的 status → category 映射。

---

## 十一、开源协议

MIT License

---

## 十二、贡献与支持

- 欢迎提交 Issue 和 Pull Request
- GitHub 仓库：https://github.com/vampireh/squid_acl_dashboard_open

---

## 更新日志

### v1.0.1 (2026-04-15)

- ✅ 添加一键安装脚本（支持 Ubuntu 20.04/22.04/24.04）
- ✅ 添加密码重置工具 `reset_password.py`
- ✅ 添加系统更新工具 `update.sh`
- ✅ 修复忘记密码邮件发送状态显示不一致的 bug
- ✅ 修复 Squid 命令路径检测问题
- ✅ 修复 Gunicorn 绑定地址为 0.0.0.0 支持外网访问
- ✅ 添加防火墙自动配置

### v1.0.0 (2026-04-14)

- ✅ 初始版本发布
- ✅ 用户管理功能
- ✅ IP 分组管理（A/B/C/D 四类）
- ✅ Squid 配置同步
- ✅ 访问日志记录与展示
- ✅ 白名单域名管理
- ✅ 代理账号管理

---

*文档最后更新：2026-04-15*
