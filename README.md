# Squid ACL Dashboard v1.0.2

Squid 代理访问控制管理面板 - 一个用于管理 Squid 代理服务器 ACL 规则的 Web 界面。

## 功能特性

- :lock: **用户认证管理** - 支持多用户、权限分级
- :globe_with_meridians: **IP 分组管理** - 灵活配置 IP 访问策略（A/B/C/D 四类）
- :chart_with_upwards_trend: **访问日志看板** - 实时监控代理访问情况
- :arrows_counterclockwise: **Squid 集成** - 自动同步配置到 Squid
- :envelope: **邮件通知** - 支持 SMTP 配置，密码找回功能
- :art: **响应式设计** - 支持桌面和移动端访问

## 技术栈

- **Web 框架**: Flask 2.0.3 + Werkzeug 2.0.3
- **用户认证**: Flask-Login 0.5.0 + Werkzeug 密码哈希
- **数据库**: SQLite（本地文件）
- **代理服务端**: Squid 缓存代理（Linux）
- **部署方式**: systemd 服务

## 快速安装

### 一键安装 (Ubuntu 推荐)

支持 Ubuntu 20.04/22.04/24.04

```bash
# 下载安装脚本
curl -fsSL https://raw.githubusercontent.com/vampireh/squid_acl_dashboard_open/master/install.sh -o install.sh

# 运行安装脚本
sudo bash install.sh
```

安装完成后，访问 `http://<服务器IP>:5001/squid-acl/` 即可使用。

**默认账号：**
- 用户名：`admin`
- 密码：`admin`

**安装后可用命令：**
```bash
# 重置用户密码（当邮件找回不可用时）
sudo python3 /opt/squid_acl_dashboard/reset_password.py admin newpassword

# 系统更新（从 GitHub 拉取最新代码）
sudo /opt/squid_acl_dashboard/update.sh

# 卸载系统
sudo /opt/squid_acl_dashboard/uninstall.sh
```

**默认 SMTP 配置：**
- SMTP 服务器：`smtp.163.com`
- SMTP 端口：`587`
- 发件人：`noreply@163.com`

### 卸载

```bash
# 下载卸载脚本
curl -fsSL https://raw.githubusercontent.com/vampireh/squid_acl_dashboard_open/master/uninstall.sh -o uninstall.sh

# 运行卸载脚本
sudo bash uninstall.sh

# 保留 Squid 配置卸载
sudo bash uninstall.sh --keep-squid

# 保留数据库卸载
sudo bash uninstall.sh --keep-db
```

## IP 分组机制

Squid 通过 IP 分组实现差异化代理访问权限：

| 分组 | 说明 | 认证 | 权限 |
|------|------|------|------|
| **A 类** | 无密码用户 | 无需密码 | 全域网段（无限制） |
| **B 类** | 密码用户 | 需要密码 | 全域网段 |
| **C 类** | 白名单无密码 | 无需密码 | 仅白名单域名 |
| **D 类** | 白名单密码用户 | 需要密码 | 仅白名单域名 |

## 系统要求

- Ubuntu 20.04/22.04/24.04
- Python 3.8+
- Squid 4.x/5.x
- 磁盘空间：至少 1GB

## 目录结构

```
squid_acl_dashboard/
├── app.py                 # Flask 主应用
├── requirements.txt       # Python 依赖
├── templates/             # HTML 模板
│   ├── login.html         # 登录页
│   ├── dashboard.html     # 访问看板
│   ├── proxy_*.html       # 管理页面
│   └── ...
├── logs/                  # 应用日志（不提交到 Git）
├── onceTask/              # 运维脚本（不提交到 Git）
├── squid_backups/         # Squid 配置备份
├── install.sh             # 一键安装脚本
├── update.sh              # 更新脚本
├── uninstall.sh           # 卸载脚本
└── reset_password.py      # 密码重置工具
```

## 数据库

SQLite 数据库文件 `acl_dashboard.db`（运行时生成，不提交到 Git），包含以下表：

- `events` - 访问日志记录
- `proxy_ips` - IP 分组管理
- `proxy_users` - 代理账号管理
- `users` - 系统管理员账号
- `reset_tokens` - 密码重置令牌

## 常用命令

```bash
# 查看 Dashboard 状态
sudo systemctl status squid-acl-dashboard

# 重启 Dashboard
sudo systemctl restart squid-acl-dashboard

# 查看 Dashboard 日志
sudo journalctl -u squid-acl-dashboard -f

# 查看 Squid 状态
sudo systemctl status squid

# 重启 Squid
sudo systemctl restart squid

# 重置管理员密码
sudo python3 /opt/squid_acl_dashboard/reset_password.py admin newpassword

# 列出所有管理员
sudo python3 /opt/squid_acl_dashboard/reset_password.py --list
```

## 故障排查

### 1. 无法访问管理面板

**现象**：浏览器无法打开 `http://<服务器IP>:5001/squid-acl/`

**排查**：
```bash
# 1. 检查服务状态
sudo systemctl status squid-acl-dashboard

# 2. 检查端口监听
sudo netstat -tlnp | grep 5001

# 3. 检查防火墙
sudo ufw status

# 4. 检查云服务器安全组是否开放 5001 端口
```

### 2. "未找到 squid 命令" 错误

**现象**：点击"检查语法"或"重载配置"时提示"未找到 squid 命令"

**解决**：
```bash
# 创建软链接
sudo ln -s /usr/sbin/squid /usr/local/bin/squid
sudo systemctl restart squid-acl-dashboard
```

### 3. 忘记密码

**方法一**：使用邮件找回
1. 点击登录页的"忘记密码"
2. 输入用户名，系统会发送重置邮件

**方法二**：使用命令行重置
```bash
sudo python3 /opt/squid_acl_dashboard/reset_password.py admin newpassword
```

### 4. Squid 认证失败

**排查**：
```bash
# 检查密码文件
sudo cat /etc/squid/passwd

# 检查文件权限
ls -la /etc/squid/passwd

# 测试认证
echo "admin:password" | /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
```

### 5. 日志显示连接外部网络失败

**排查**：
```bash
# 检查 Squid 日志
sudo tail -f /var/log/squid/access.log

# 测试代理连接
curl -I -x http://127.0.0.1:3128 https://www.google.com
```

## 更新日志

### v1.0.2 (2026-04-15)
- 新增一键安装、卸载、更新脚本
- 默认 SMTP 改为 163 邮箱
- 自动配置防火墙
- 自动安装 Squid 代理
- 访问地址改为 `http://ip:5001/squid-acl/`

### v1.0.1 (2026-04-15)
- 修复忘记密码邮件发送状态显示问题
- 修复 Squid 命令路径检测问题
- 添加密码重置工具

### v1.0.0 (2026-04-14)
- 初始版本
- 支持 IP 分组管理
- 支持用户认证
- 支持访问日志看板

## 开源协议

MIT License

## GitHub 仓库

https://github.com/vampireh/squid_acl_dashboard_open

## 问题反馈

如有问题或建议，请通过 GitHub Issues 反馈。
