# squid_acl_dashboard_open - AI 项目理解文档

> **用途**：本文档供 AI 阅读，使其快速理解项目架构、功能和数据模型，替代直接阅读全部源码。
> **最新版本**：2026-04-15，Flask 2.0.3 + SQLite + Squid 代理日志分析 + 访问控制系统，v1.0.2。

---

## 一、项目是什么

**squid_acl_dashboard_open** 是一个基于 Flask 的 **Squid 代理访问控制管理平台**，同时也是一套**代理日志可视化分析系统**。

**两个核心功能**：

1. **代理上网行为管理**（面向管理员）：管理四类 IP 白名单、两类用户账号、白名单域名池，编辑 squid.conf 配置文件并重载生效。
2. **代理日志看板**（面向最终用户/管理员）：实时解析 Squid 访问日志，展示个人访问记录、域名统计、支持按时间/IP/域名搜索。

---

## 二、技术栈

| 层次 | 技术 |
|------|------|
| Web 框架 | Flask 2.0.3 + Werkzeug 2.0.3 |
| 用户认证 | Flask-Login 0.5.0 + Werkzeug 密码哈希 |
| 数据库 | SQLite（`acl_dashboard.db`），本地文件 |
| 日志来源 | `/var/log/squid/access.log`（Squid 访问日志） |
| 代理服务端 | Squid 缓存代理（Linux） |
| 前端 | Jinja2 模板 + 原生 HTML/CSS/JS（无框架） |
| 部署方式 | systemd 服务 `squid-acl-dashboard` |
| URL 前缀 | `/squid-acl`（由 `URL_PREFIX` 常量控制） |
| 安装方式 | 一键安装脚本 `install.sh` |

---

## 三、路由总览

### 日志看板（用户面向）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/squid-acl/` | GET | 首页看板：今日统计、访问趋势图、最近访问记录 |
| `/squid-acl/detail/ip/<ip>` | GET | 某 IP 的所有访问记录（分页，支持时间过滤） |
| `/squid-acl/detail/host/<path:host>` | GET | 某域名的所有访问记录（分页，支持时间过滤） |

### 配置管理（管理员面向）

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

### 用户认证

| 路由 | 方法 | 说明 |
|------|------|------|
| `/squid-acl/login` | GET/POST | 登录 |
| `/squid-acl/logout` | GET | 登出 |
| `/squid-acl/settings` | GET/POST | 修改登录密码 |
| `/squid-acl/forgot` | GET/POST | 忘记密码（发送邮件重置链接） |

---

## 四、数据模型

### events（访问日志）

> 日志解析后存入 SQLite，字段对应 Squid access.log 格式。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| event_time | TEXT | 北京时间可读时间（如 `2026-04-15 16:30:00`） |
| event_ts | REAL | Unix 时间戳（北京时间） |
| client_ip | TEXT | 客户端 IP |
| status | TEXT | Squid 状态码（如 `TCP_MISS/200`） |
| category | TEXT | 分类：`SUCCESS` / `ACL` / `ERROR`（由 classify_status() 判断） |
| http_code | TEXT | HTTP 状态码（200/403/407 等） |
| method | TEXT | 请求方法（GET/POST/CONNECT 等） |
| target | TEXT | 目标 URL（原始格式） |
| host | TEXT | 解析出的域名/主机 |
| user_field | TEXT | Squid 日志中的用户字段 |
| hierarchy | TEXT | 上游代理层级 |
| content_type | TEXT | Content-Type |
| raw_line | TEXT | 原始日志行 |
| created_at | TEXT | 入库时间 |

**日志解析正则**（`LOG_RE`）：
```
ts.elapsed client_ip status size method target user hierarchy content_type
```

**status → category 分类逻辑**：
- `ACL`：`TCP_DENIED/403`、`TCP_DENIED/407`、`TAG_NONE/403`
- `SUCCESS`：`TCP_MISS/200`、`TCP_HIT/200`、`TCP_MEM_HIT/200`、`TCP_TUNNEL/200` 等
- `ERROR`：`NONE_NONE/000`、`ERR_CONNECT_FAIL`、`ERR_DNS_FAIL` 等

### proxy_ips（IP 分组）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| ip_addr | TEXT UNIQUE | IP 地址 |
| ip_group | TEXT | 分组：`A` / `B` / `C` / `D` |
| description | TEXT | 描述 |
| created_at | TEXT | 入库时间 |

### proxy_users（代理账号）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| username | TEXT UNIQUE | 用户名 |
| password_hash | TEXT | 密码哈希（HTPasswd 格式） |
| user_group | TEXT | 分组：`B` / `D` |
| user_realname | TEXT | 真实姓名（可选） |
| created_at | TEXT | 入库时间 |

### users（系统管理员账号）

| 字段 | 类型 | 说明 |
|------|------|------|
| username | TEXT | 管理员用户名 |
| password_hash | TEXT | 密码哈希 |
| password_changed_at | TEXT | 上次修改时间 |
| created_at | TEXT | 创建时间 |

### reset_tokens（密码重置令牌）

| 字段 | 类型 | 说明 |
|------|------|------|
| token | TEXT PRIMARY KEY | 重置令牌 |
| expires_at | REAL | 过期时间戳 |
| created_at | TEXT | 创建时间 |

---

## 五、IP 分组机制（Squid ACL 分类）

Squid 通过 IP 分组实现差异化代理访问权限，分组逻辑在 squid.conf 中定义：

| 分组 | IP 来源文件 | 认证 | 权限 |
|------|------------|------|------|
| **A 类** | `ip_group_a.txt` | 无需密码 | 全域网段（无白名单限制） |
| **B 类** | `ip_group_b.txt` | 需要密码 | 全域网段 |
| **C 类** | `ip_group_c.txt` | 无需密码 | **仅白名单域名**（受 allow.txt 限制） |
| **D 类** | `ip_group_d.txt` | 需要密码 | **仅白名单域名** |

**关键理解**：真实访问权限由**客户端 IP** 决定，不是用户名。proxy_users 表的 user_group 字段是管理用途，用于在页面上按组展示账号。

---

## 六、关键文件路径（服务器部署路径）

| 路径 | 说明 |
|------|------|
| `/opt/squid_acl_dashboard/` | 应用根目录 |
| `/opt/squid_acl_dashboard/acl_dashboard.db` | SQLite 数据库 |
| `/opt/squid_acl_dashboard/logs/` | 应用日志（`app.log`，10MB 滚动，保留5份） |
| `/opt/squid_acl_dashboard/squid_backups/` | squid.conf 备份 |
| `/etc/squid/squid.conf` | Squid 主配置 |
| `/etc/squid/ip_group_[a-d].txt` | IP 分组文件 |
| `/etc/squid/passwd` | HTPasswd 用户文件 |
| `/etc/squid/allow.txt` | 白名单域名列表 |
| `/var/log/squid/access.log` | Squid 访问日志（应用读取的来源） |

---

## 七、一键安装脚本特性

### install.sh
- 自动检测 Ubuntu 版本
- 自动安装系统依赖（Python3, pip, Squid, Apache2-utils 等）
- 自动配置防火墙（ufw + 云服务器安全组提示）
- 自动初始化数据库
- 自动配置 Squid 代理
- 自动配置 systemd 服务
- 默认 SMTP: smtp.163.com:587
- 默认访问地址: http://ip:5001/squid-acl/

### uninstall.sh
- 支持 `--keep-squid` 保留 Squid 配置
- 支持 `--keep-db` 保留数据库备份
- 支持 `--keep-logs` 保留日志文件
- 自动创建卸载前备份

### update.sh
- 支持 `--force` 强制更新
- 支持 `--backup` 仅备份
- 支持 `--restore` 从备份恢复
- 支持 `--version` 查看版本信息
- 自动备份当前版本
- 更新失败自动回滚

---

## 八、关键配置常量（app.py 头部）

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

## 九、.gitignore 配置

以下文件/目录不提交到 Git：

```
# 运行时数据
logs/
oncetask/
*.db
*.db.backup

# Python
__pycache__/
*.pyc
venv/
.venv/

# 备份
*.bak
squid_backups/
```

---

## 十、已知的架构注意点

1. **Python 版本兼容**：代码中 `subprocess.run()` 不可使用 `capture_output=True`（Python 3.6 不支持），需使用 `stdout=subprocess.PIPE, stderr=subprocess.PIPE` 替代。
2. **北京时间强制**：无论服务器系统时区如何，应用层强制使用 UTC+8（`CST`）。
3. **数据库保护**：`acl_dashboard.db` 和 `logs/` 目录通过 .gitignore 保护，不被提交到 Git。
4. **Squid 服务名**：`systemctl restart squid-acl-dashboard`（不是 squid）。
5. **HTPasswd 格式**：passwd 文件使用 Apache `htpasswd -b` 格式，`username:password_hash`。

---

*文档由 AI 自动生成，基于 `app.py` 源码分析。最后更新：2026-04-15。*
