# Squid 管理面板

一个基于 Flask 的 Web 管理界面，用于管理 Squid 代理服务器的访问控制列表（ACL）。支持 ABCD 四类终端分级授权管控、访问日志实时采集与多维统计、配置管理等功能。

---

## 功能特性

- **访问日志实时采集**：自动解析 Squid 访问日志，支持多维统计分析
- **四类终端分级授权**：
  - A 类：VIP（免密 + 全网通）
  - B 类：普通员工（密码 + 全网通）
  - C 类：受限设备/哑终端（免密 + 仅白名单）
  - D 类：受限员工（密码 + 仅白名单）
- **Web 配置管理**：通过浏览器管理 IP 分组、白名单、用户账号和 Squid 配置
- **管理员认证**：支持密码修改、密码重置功能
- **忘记密码**：支持通过邮件找回密码（需配置 SMTP）
- **数据持久化**：SQLite 数据库存储，支持历史数据导入

---

## 快速安装（推荐）

### Ubuntu 一键安装脚本

支持 Ubuntu 20.04/22.04/24.04，自动完成所有配置。

```bash
# 下载安装脚本
wget https://raw.githubusercontent.com/vampireh/squid_acl_dashboard_open/master/install.sh

# 添加执行权限
chmod +x install.sh

# 运行安装（必须使用 root）
sudo ./install.sh
```

安装过程中会提示输入：
- 安装目录（默认：`/opt/squid_acl_dashboard`）
- 监听端口（默认：`5001`）
- 管理员邮箱（用于接收密码重置邮件）
- SMTP 服务器配置（用于忘记密码功能）

安装完成后，访问 `http://服务器IP:5001/squid-acl`，使用默认账号 `admin` / `admin@123` 登录。

---

## 手动部署指南

如需手动部署或自定义配置，请参考以下步骤。

### 一、环境要求

- **操作系统**：CentOS 7/8、Rocky Linux、AlmaLinux、Ubuntu 20.04+
- **Python**：3.8 或更高版本
- **Squid**：4.x 或 5.x
- **内存**：建议 2GB+
- **磁盘**：建议 20GB+

---

### 二、安装 Python 环境

#### CentOS/Rocky Linux

```bash
# 安装 Python 3 和 pip
sudo yum install -y python3 python3-pip python3-devel

# 验证安装
python3 --version
pip3 --version
```

#### Ubuntu/Debian

```bash
# 安装 Python 3 和 pip
sudo apt update
sudo apt install -y python3 python3-pip python3-venv python3-dev

# 验证安装
python3 --version
pip3 --version
```

---

### 三、安装 Squid

#### CentOS/Rocky Linux

```bash
# 安装 Squid
sudo yum install -y squid

# 安装 httpd-tools（用于 htpasswd 命令）
sudo yum install -y httpd-tools

# 启动并设置开机自启
sudo systemctl enable squid
sudo systemctl start squid
```

#### Ubuntu/Debian

```bash
# 安装 Squid
sudo apt update
sudo apt install -y squid apache2-utils

# 启动并设置开机自启
sudo systemctl enable squid
sudo systemctl start squid
```

---

### 四、部署管理面板

#### 1. 创建应用目录

```bash
# 创建应用目录
sudo mkdir -p /opt/squid_acl_dashboard
sudo mkdir -p /opt/squid_acl_dashboard/logs

# 设置目录权限
sudo chown -R $USER:$USER /opt/squid_acl_dashboard
```

#### 2. 上传项目文件

将项目文件上传到 `/opt/squid_acl_dashboard` 目录：

```bash
# 项目文件结构
/opt/squid_acl_dashboard/
├── app.py                  # 主程序
├── requirements.txt        # Python 依赖
├── cleanup_old_data.py     # 数据清理脚本
├── import_history.py       # 历史数据导入脚本
├── templates/              # HTML 模板
│   ├── index.html
│   ├── login.html
│   ├── detail.html
│   ├── proxy_index.html
│   ├── proxy_ips.html
│   ├── proxy_users.html
│   ├── proxy_conf.html
│   ├── proxy_allow.html
│   ├── settings.html
│   └── forgot.html
└── etc/
    └── squid/              # Squid 配置文件
        ├── squid.conf      # 主配置
        ├── allow.txt       # 白名单
        ├── passwd          # 用户密码
        ├── ip_group_a.txt  # A 类 IP
        ├── ip_group_b.txt  # B 类 IP
        ├── ip_group_c.txt  # C 类 IP
        └── ip_group_d.txt  # D 类 IP
```

#### 3. 安装 Python 依赖

```bash
cd /opt/squid_acl_dashboard

# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

**requirements.txt 内容示例：**

```
Flask>=2.0.0
Werkzeug>=2.0.0
Flask-Login>=0.6.0
```

#### 4. 配置 Squid

复制配置文件到 Squid 配置目录：

```bash
# 备份原配置
sudo cp /etc/squid/squid.conf /etc/squid/squid.conf.bak

# 复制新配置
sudo cp /opt/squid_acl_dashboard/etc/squid/squid.conf /etc/squid/squid.conf
sudo cp /opt/squid_acl_dashboard/etc/squid/allow.txt /etc/squid/allow.txt
sudo cp /opt/squid_acl_dashboard/etc/squid/passwd /etc/squid/passwd
sudo cp /opt/squid_acl_dashboard/etc/squid/ip_group_*.txt /etc/squid/

# 设置权限
sudo chown -R squid:squid /etc/squid/
sudo chmod 640 /etc/squid/passwd
```

**注意**：如果系统中没有 `squid` 用户，请使用：

```bash
sudo chown -R root:root /etc/squid/
sudo chmod 640 /etc/squid/passwd
```

#### 5. 修改应用配置

编辑 `app.py`，根据实际环境调整以下配置：

**基础配置：**

```python
# 应用目录
BASE_DIR = "/opt/squid_acl_dashboard"

# Squid 访问日志路径（根据实际路径修改）
LOG_PATH = "/var/log/squid/access.log"

# URL 前缀（如需修改访问路径）
URL_PREFIX = "/squid-acl"
```

常见日志路径：
- CentOS/Rocky: `/var/log/squid/access.log`
- Ubuntu: `/var/log/squid/access.log`

**邮件配置（用于忘记密码功能）：**

```python
# ── 邮件找回密码配置 ──────────────────────────────────────────────────────────
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.example.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
FROM_EMAIL = SMTP_USER          # 发件人（与 SMTP_USER 相同）
ADMIN_EMAIL = "admin@example.com"  # 【重要】修改为管理员实际邮箱
```

**配置方式（推荐环境变量）：**

```bash
# 方式一：临时环境变量（当前会话有效）
export SMTP_HOST="smtp.163.com"
export SMTP_PORT="587"
export SMTP_USER="your_email@163.com"
export SMTP_PASS="your_email_password"
export ADMIN_EMAIL="admin@yourdomain.com"

# 方式二：Systemd 服务中配置（推荐）
# 在 /etc/systemd/system/squid-acl-dashboard.service 的 [Service] 部分添加：
# Environment="SMTP_HOST=smtp.163.com"
# Environment="SMTP_USER=your_email@163.com"
# Environment="SMTP_PASS=your_password"
# Environment="ADMIN_EMAIL=admin@yourdomain.com"
```

**常见邮箱 SMTP 配置：**

| 邮箱服务商 | SMTP 服务器 | 端口 | 说明 |
|-----------|------------|------|------|
| 163 邮箱 | smtp.163.com | 587 | 需开启 SMTP 服务，使用授权码 |
| QQ 邮箱 | smtp.qq.com | 587 | 需开启 SMTP 服务，使用授权码 |
| Gmail | smtp.gmail.com | 587 | 需开启两步验证，使用应用专用密码 |
| Outlook | smtp.office365.com | 587 | 使用邮箱密码 |
| 企业邮箱 | smtp.exmail.qq.com | 587 | 腾讯企业邮箱 |

**获取邮箱授权码：**
- **163 邮箱**：登录邮箱 → 设置 → POP3/SMTP/IMAP → 开启 SMTP 服务 → 获取授权码
- **QQ 邮箱**：登录邮箱 → 设置 → 账户 → 开启 SMTP 服务 → 获取授权码

**注意**：如果不配置 SMTP，忘记密码功能将无法发送邮件，但系统仍会生成新密码并在日志中记录（仅用于演示）。

#### 6. 初始化数据库

```bash
cd /opt/squid_acl_dashboard
source venv/bin/activate

# 运行一次应用以初始化数据库
python3 -c "from app import init_db; init_db()"
```

---

### 五、启动管理面板

#### 方式一：开发模式（测试用）

```bash
cd /opt/squid_acl_dashboard
source venv/bin/activate

# 启动应用
python3 app.py
```

默认监听 `127.0.0.1:5001`，访问地址：`http://127.0.0.1:5001/squid-acl`

#### 方式二：生产模式（推荐）

使用 Gunicorn + Nginx 部署：

```bash
# 安装 Gunicorn
pip install gunicorn

# 启动应用（后台运行）
gunicorn -w 4 -b 127.0.0.1:5001 --daemon --access-logfile logs/access.log --error-logfile logs/error.log app:app
```

参数说明：
- `-w 4`：4 个工作进程
- `-b 127.0.0.1:5001`：绑定地址和端口
- `--daemon`：后台运行

#### 方式三：Systemd 服务（推荐用于生产）

创建服务文件：

```bash
sudo tee /etc/systemd/system/squid-acl-dashboard.service << 'EOF'
[Unit]
Description=Squid ACL Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/squid_acl_dashboard
Environment="PATH=/opt/squid_acl_dashboard/venv/bin"
Environment="SECRET_KEY=your-secret-key-here-change-in-production"
# 【邮件配置】根据实际邮箱修改以下配置
Environment="SMTP_HOST=smtp.163.com"
Environment="SMTP_PORT=587"
Environment="SMTP_USER=your_email@163.com"
Environment="SMTP_PASS=your_email_auth_code"
Environment="ADMIN_EMAIL=admin@yourdomain.com"
ExecStart=/opt/squid_acl_dashboard/venv/bin/gunicorn -w 4 -b 127.0.0.1:5001 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

启动服务：

```bash
# 重载 systemd
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start squid-acl-dashboard

# 设置开机自启
sudo systemctl enable squid-acl-dashboard

# 查看状态
sudo systemctl status squid-acl-dashboard
```

---

### 六、配置 Nginx 反向代理（可选）

如需通过域名访问，配置 Nginx：

```bash
sudo tee /etc/nginx/conf.d/squid-acl.conf << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location /squid-acl {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 测试配置
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

---

### 七、重启 Squid 服务

配置完成后，重启 Squid 使配置生效：

```bash
# 检查配置语法
sudo squid -k parse

# 重载配置
sudo systemctl reload squid
# 或
sudo squid -k reconfigure

# 如果重载失败，尝试重启
sudo systemctl restart squid
```

---

### 八、访问管理面板

#### 默认登录信息

- **地址**：`http://your-server-ip:5001/squid-acl`
- **用户名**：`admin`
- **密码**：`admin@123`

**⚠️ 重要**：首次登录后请立即修改默认密码！

---

### 九、防火墙配置

如果无法访问，请检查防火墙：

```bash
# CentOS/Rocky (firewalld)
sudo firewall-cmd --permanent --add-port=5001/tcp
sudo firewall-cmd --reload

# 或使用 Nginx 反向代理时开放 80 端口
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload

# Ubuntu (ufw)
sudo ufw allow 5001/tcp
# 或
sudo ufw allow 'Nginx Full'
```

---

### 十、日常维护

#### 查看日志

```bash
# 应用日志
tail -f /opt/squid_acl_dashboard/logs/app.log

# Gunicorn 访问日志
tail -f /opt/squid_acl_dashboard/logs/access.log

# Squid 日志
tail -f /var/log/squid/access.log
```

#### 数据备份

```bash
# 备份数据库
sudo cp /opt/squid_acl_dashboard/acl_dashboard.db /backup/acl_dashboard.db.$(date +%Y%m%d)

# 备份 Squid 配置
sudo tar czf /backup/squid-config.$(date +%Y%m%d).tar.gz /etc/squid/
```

#### 数据清理

系统会自动清理 30 天前的日志数据。如需手动清理：

```bash
cd /opt/squid_acl_dashboard
source venv/bin/activate
python3 cleanup_old_data.py
```

---

### 十一、故障排查

#### 1. 应用无法启动

```bash
# 检查日志
cat /opt/squid_acl_dashboard/logs/error.log

# 检查端口占用
sudo netstat -tlnp | grep 5001

# 检查权限
ls -la /opt/squid_acl_dashboard/
```

#### 2. Squid 配置错误

```bash
# 检查配置语法
sudo squid -k parse

# 查看 Squid 日志
sudo tail -f /var/log/squid/cache.log
```

#### 3. 日志无法采集

```bash
# 检查日志路径
ls -la /var/log/squid/access.log

# 检查权限
groups
id

# 确保应用有读取权限
sudo chmod 644 /var/log/squid/access.log
```

---

## 目录结构

```
squid_acl_dashboard/
├── app.py                  # Flask 主程序
├── requirements.txt        # Python 依赖
├── cleanup_old_data.py     # 数据清理脚本
├── import_history.py       # 历史数据导入脚本
├── README.md              # 本文件
├── templates/             # HTML 模板
│   ├── index.html         # 首页/仪表盘
│   ├── login.html         # 登录页
│   ├── detail.html        # 详情页
│   ├── proxy_index.html   # 代理管理首页
│   ├── proxy_ips.html     # IP 分组管理
│   ├── proxy_users.html   # 用户管理
│   ├── proxy_conf.html    # 配置管理
│   ├── proxy_allow.html   # 白名单管理
│   ├── settings.html      # 系统设置
│   └── forgot.html        # 密码重置
└── etc/
    └── squid/             # Squid 配置文件
        ├── squid.conf     # 主配置文件
        ├── allow.txt      # 白名单
        ├── passwd         # 用户密码文件
        ├── ip_group_a.txt # A 类 IP 列表
        ├── ip_group_b.txt # B 类 IP 列表
        ├── ip_group_c.txt # C 类 IP 列表
        └── ip_group_d.txt # D 类 IP 列表
```

---

## 安全建议

1. **修改默认密码**：首次登录后立即修改 `admin` 密码
2. **使用 HTTPS**：生产环境配置 SSL 证书
3. **限制访问**：通过防火墙或 Nginx 限制管理面板访问 IP
4. **定期备份**：定期备份数据库和配置文件
5. **更新系统**：及时更新系统和依赖包

---

## 开源协议

本项目仅供学习交流使用。

---

## 免责声明

本项目中的 IP、域名、用户名等数据均为随机生成的示例数据，不代表任何真实机构或人员。使用本项目时请遵守当地法律法规。
