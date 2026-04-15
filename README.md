# Squid ACL Dashboard v1.0.1

Squid 代理访问控制管理面板 - 一个用于管理 Squid 代理服务器 ACL 规则的 Web 界面。

## 功能特性

- 🔐 **用户认证管理** - 支持多用户、权限分级
- 🌐 **IP 分组管理** - 灵活配置 IP 访问策略
- 📊 **访问日志** - 实时监控代理访问情况
- 🔄 **Squid 集成** - 自动同步配置到 Squid
- 📧 **邮件通知** - 支持 SMTP 配置，密码找回功能
- 🎨 **响应式设计** - 支持桌面和移动端访问

## 快速安装

### 一键安装 (推荐)

```bash
# 下载安装脚本
curl -fsSL https://raw.githubusercontent.com/vampireh/squid_acl_dashboard_open/master/install.sh -o install.sh

# 运行安装脚本
sudo bash install.sh
```

安装完成后，访问 `http://<服务器IP>:5001/squid-acl` 即可使用。

**安装后可用命令：**
```bash
# 重置用户密码（当邮件找回不可用时）
sudo python3 /opt/squid_acl_dashboard/reset_password.py admin newpassword

# 系统更新（从 GitHub 拉取最新代码）
sudo /opt/squid_acl_dashboard/update.sh
```

**默认 SMTP 配置**：
- SMTP 服务器：`smtp.163.com`
- SMTP 端口：`587`

### 手动安装

#### 系统要求

- Ubuntu 20.04/22.04/24.04
- Python 3.8+
- Squid 4.x/5.x

#### 安装步骤

1. **安装系统依赖**

```bash
sudo apt-get update
sudo apt-get install -y squid apache2-utils python3 python3-pip python3-venv sqlite3 curl ufw
```

2. **创建安装目录**

```bash
sudo mkdir -p /opt/squid_acl_dashboard
cd /opt/squid_acl_dashboard
```

3. **创建 Python 虚拟环境**

```bash
sudo python3 -m venv venv
source venv/bin/activate
```

4. **安装 Python 依赖**

```bash
pip install flask==3.0.0 flask-login==0.6.3 werkzeug==3.0.1 gunicorn==21.2.0
```

5. **上传应用代码**

将 `app.py` 上传到 `/opt/squid_acl_dashboard/` 目录。

6. **初始化数据库**

```bash
cd /opt/squid_acl_dashboard
python3 -c "
import sqlite3
from werkzeug.security import generate_password_hash
conn = sqlite3.connect('squid_acl.db')
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, is_admin INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS ip_groups (id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS ip_addresses (id INTEGER PRIMARY KEY, group_id INTEGER, ip_address TEXT, description TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS access_logs (id INTEGER PRIMARY KEY, username TEXT, ip_address TEXT, action TEXT, details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
admin_pass = generate_password_hash('admin123')
cursor.execute('INSERT OR IGNORE INTO users (username, password, email, is_admin) VALUES (?, ?, ?, ?)', ('admin', admin_pass, 'admin@localhost', 1))
conn.commit()
conn.close()
print('数据库初始化完成')
"
```

7. **配置防火墙**

```bash
# 开放 5001 端口
sudo ufw allow 5001/tcp

# 如果 ufw 未启用，可以启用它
sudo ufw enable
```

**注意**：如果服务器在云环境（阿里云、腾讯云、AWS等），还需要在**云服务器安全组/防火墙**中开放 5001 端口。

8. **创建 Systemd 服务**

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

9. **启动服务**

```bash
sudo systemctl daemon-reload
sudo systemctl enable squid-acl-dashboard
sudo systemctl start squid-acl-dashboard
```

## SMTP 配置（可选）

如需启用密码找回功能，需要配置 SMTP：

### 1. 修改 Systemd 服务文件

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

### 2. 重载并重启服务

```bash
sudo systemctl daemon-reload
sudo systemctl restart squid-acl-dashboard
```

### 常用邮箱 SMTP 设置

| 邮箱服务商 | SMTP 服务器 | 端口 |
|-----------|------------|------|
| Gmail | smtp.gmail.com | 587 |
| QQ邮箱 | smtp.qq.com | 587 |
| 163邮箱 | smtp.163.com | 25/587 |
| Outlook | smtp.office365.com | 587 |
| 阿里云 | smtp.aliyun.com | 25/465 |

## 配置 Squid

### 1. 创建密码文件

```bash
sudo touch /etc/squid/passwd
sudo chown proxy:proxy /etc/squid/passwd
sudo chmod 640 /etc/squid/passwd
sudo htpasswd -b /etc/squid/passwd admin admin123
```

### 2. 配置 Squid

编辑 `/etc/squid/squid.conf`：

```conf
# 基本配置
http_port 3128

# 认证配置（Ubuntu 路径）
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic children 5
auth_param basic realm Squid Proxy
auth_param basic credentialsttl 2 hours

# ACL 定义
acl authenticated proxy_auth REQUIRED

# 访问控制
http_access allow authenticated
http_access deny all

# DNS 配置
dns_nameservers 8.8.8.8 8.8.4.4
```

**注意**：CentOS/Rocky 系统的认证程序路径为 `/usr/lib64/squid/basic_ncsa_auth`

### 3. 重启 Squid

```bash
sudo systemctl restart squid
sudo systemctl enable squid
```

## 防火墙配置

### 本地防火墙 (ufw)

```bash
# 查看防火墙状态
sudo ufw status

# 开放 5001 端口（管理面板）
sudo ufw allow 5001/tcp

# 开放 3128 端口（Squid 代理）
sudo ufw allow 3128/tcp

# 启用防火墙
sudo ufw enable
```

### 云服务器安全组

如果服务器部署在云环境（阿里云、腾讯云、AWS、Azure等），还需要在**控制台的安全组/防火墙**中开放以下端口：

| 端口 | 用途 | 建议配置 |
|-----|------|---------|
| 5001 | Web 管理面板 | 限制为管理员 IP |
| 3128 | Squid 代理 | 根据业务需求开放 |
| 22 | SSH | 限制为管理 IP |

## 排障指南

### 1. 无法访问管理面板

**现象**：浏览器无法打开 `http://<服务器IP>:5001`

**排查步骤**：

```bash
# 1. 检查服务状态
sudo systemctl status squid-acl-dashboard

# 2. 检查端口监听（应该显示 0.0.0.0:5001）
sudo netstat -tlnp | grep 5001
# 或
sudo ss -tlnp | grep 5001

# 3. 检查防火墙
sudo ufw status

# 4. 查看应用日志
sudo journalctl -u squid-acl-dashboard -f

# 5. 本地测试
curl http://127.0.0.1:5001/
```

**常见原因**：
- **服务未启动**：检查 `systemctl status`，查看日志中的错误
- **端口未监听**：确认 Gunicorn 绑定的是 `0.0.0.0:5001` 而不是 `127.0.0.1:5001`
- **防火墙拦截**：检查 ufw 状态和云服务器安全组
- **端口冲突**：检查是否有其他程序占用 5001 端口

### 2. 服务启动失败 (status=203/EXEC)

**现象**：`systemctl status` 显示 `status=203/EXEC`

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

### 3. 数据库锁定错误

**现象**：日志中出现 `sqlite3.OperationalError: database is locked`

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

### 4. "未找到 squid 命令" 错误

**现象**：在管理面板点击"检查语法"或"重载配置"时提示"未找到 squid 命令"

**原因**：Squid 命令不在系统的 PATH 环境变量中

**解决**：
```bash
# 1. 查找 squid 命令位置
which squid
# 或
find /usr -name "squid" -type f 2>/dev/null

# 常见路径：
# - Ubuntu: /usr/sbin/squid
# - CentOS: /usr/sbin/squid

# 2. 创建软链接到 PATH
sudo ln -s /usr/sbin/squid /usr/local/bin/squid

# 3. 或者修改应用环境变量
sudo systemctl edit squid-acl-dashboard
# 添加：
[Service]
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# 4. 重启服务
sudo systemctl daemon-reload
sudo systemctl restart squid-acl-dashboard
```

### 5. Squid 认证失败

**现象**：代理连接时提示认证失败

**排查**：
```bash
# 1. 检查密码文件
sudo cat /etc/squid/passwd

# 2. 检查文件权限
ls -la /etc/squid/passwd

# 3. 检查认证程序路径
ls -la /usr/lib/squid/basic_ncsa_auth
# 或
ls -la /usr/lib64/squid/basic_ncsa_auth

# 4. 手动测试认证
echo "admin:admin123" | /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
# 输出 OK 表示成功
```

### 5. 忘记密码邮件发送失败但前端显示成功

**现象**：邮件发送失败（日志显示 `Connection unexpectedly closed`），但前端显示"邮件已发送"

**原因**：前端模板显示固定文本，没有根据实际发送结果显示状态

**解决**：
- 已修复：后端添加 `email_sent` 标志传递给前端
- 已修复：前端模板根据发送状态显示不同消息
- 如果仍然遇到问题，请检查 SMTP 配置是否正确

### 6. 忘记管理员密码

```bash
cd /opt/squid_acl_dashboard
source venv/bin/activate
python3 -c "
from werkzeug.security import generate_password_hash
import sqlite3
conn = sqlite3.connect('squid_acl.db')
cursor = conn.cursor()
new_pass = generate_password_hash('newpassword')
cursor.execute('UPDATE users SET password = ? WHERE username = ?', (new_pass, 'admin'))
conn.commit()
conn.close()
print('密码已重置为: newpassword')
"
```

## 命令行工具

### 1. 密码重置工具 (reset_password.py)

当邮件找回功能不可用时，root 用户可以通过命令行重置用户密码。

**使用方法：**

```bash
# 进入安装目录
cd /opt/squid_acl_dashboard

# 重置指定用户密码
sudo python3 reset_password.py <用户名> <新密码>

# 示例：重置 admin 密码
sudo python3 reset_password.py admin newpassword123

# 列出所有用户
sudo python3 reset_password.py --list

# 显示帮助
sudo python3 reset_password.py --help
```

**功能特点：**
- ✅ 自动检测用户是否存在
- ✅ 显示所有用户列表（当用户名不存在时）
- ✅ 密码长度检查和安全提示
- ✅ 详细的操作结果反馈

---

### 2. 更新工具 (update.sh)

用于从 GitHub 拉取最新代码并自动更新系统。

**使用方法：**

```bash
# 进入安装目录
cd /opt/squid_acl_dashboard

# 常规更新（会提示确认）
sudo ./update.sh

# 强制更新（跳过确认）
sudo ./update.sh --force

# 仅备份当前版本
sudo ./update.sh --backup

# 从备份恢复（更新失败时使用）
sudo ./update.sh --restore

# 查看当前版本信息
sudo ./update.sh --version

# 显示帮助
sudo ./update.sh --help
```

**功能特点：**
- ✅ 自动备份当前版本（保留最近10个备份）
- ✅ 自动更新 Python 依赖
- ✅ 更新失败自动回滚
- ✅ 保留数据库和配置文件
- ✅ 自动检查服务状态

---

## 常用命令

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

## 生产环境建议

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

## 项目结构

```
/opt/squid_acl_dashboard/
├── app.py              # 主应用文件
├── squid_acl.db        # SQLite 数据库
├── venv/               # Python 虚拟环境
├── ip_lists/           # IP 列表文件目录
└── logs/               # 日志目录
```

## 技术栈

- **后端**: Flask + Flask-Login + Gunicorn
- **数据库**: SQLite
- **代理**: Squid
- **认证**: NCSA Basic Auth

## 开源协议

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v1.0.0
- ✅ 初始版本发布
- ✅ 用户管理功能
- ✅ IP 分组管理
- ✅ Squid 配置同步
- ✅ 访问日志记录
- ✅ 一键安装脚本
