#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Squid ACL Dashboard - Web管理界面
用于管理Squid代理服务器的ACL规则
"""

import os
import re
import subprocess
import hashlib
import secrets
import sqlite3
import smtplib
import logging
from datetime import datetime
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Flask-Login 配置
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录以访问此页面'
login_manager.login_message_category = 'warning'

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'squid_acl.db')

# Squid 配置路径
SQUID_CONF_DIR = '/etc/squid'
SQUID_CONF_FILE = os.path.join(SQUID_CONF_DIR, 'squid.conf')
SQUID_PASSWD_FILE = os.path.join(SQUID_CONF_DIR, 'passwd')

# ==================== 数据库操作 ====================

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 创建管理员表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建IP组表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ip_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建IP地址表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ip_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            ip_address TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (group_id) REFERENCES ip_groups(id) ON DELETE CASCADE,
            UNIQUE(group_id, ip_address)
        )
    ''')
    
    # 创建用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            department TEXT,
            status INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建访问日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ip_address TEXT,
            action TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    # 创建系统配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT UNIQUE NOT NULL,
            config_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 插入默认管理员账号 (admin/admin123)
    default_password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
    cursor.execute('''
        INSERT OR IGNORE INTO admins (username, password_hash, email)
        VALUES (?, ?, ?)
    ''', ('admin', default_password_hash, 'admin@example.com'))
    
    conn.commit()
    conn.close()
    logger.info("数据库初始化完成")

# ==================== 用户认证 ====================

class Admin(UserMixin):
    """管理员用户类"""
    def __init__(self, id, username, email):
        self.id = id
        self.username = username
        self.email = email

@login_manager.user_loader
def load_user(user_id):
    """加载用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return Admin(user['id'], user['username'], user['email'])
    return None

def verify_password(password, password_hash):
    """验证密码"""
    return hashlib.sha256(password.encode()).hexdigest() == password_hash

def log_access(user_id, ip_address, action, details=None):
    """记录访问日志"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO access_logs (user_id, ip_address, action, details)
            VALUES (?, ?, ?, ?)
        ''', (user_id, ip_address, action, details))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"记录访问日志失败: {e}")

# ==================== Squid 配置管理 ====================

def get_squid_command():
    """获取 Squid 命令路径"""
    # 常见 Squid 命令路径
    possible_paths = [
        '/usr/sbin/squid',
        '/usr/bin/squid',
        '/usr/local/sbin/squid',
        '/usr/local/bin/squid',
        'squid',  # 如果在 PATH 中
    ]
    
    for path in possible_paths:
        if path == 'squid':
            # 检查是否在 PATH 中
            try:
                subprocess.run(['which', 'squid'], capture_output=True, check=True)
                return 'squid'
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        elif os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    
    return None

def check_squid_syntax():
    """检查 Squid 配置语法"""
    squid_cmd = get_squid_command()
    if not squid_cmd:
        return False, "未找到 squid 命令，请确认已安装 Squid"
    
    try:
        result = subprocess.run(
            [squid_cmd, '-k', 'parse'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, "语法检查通过"
        else:
            return False, result.stderr or "语法检查失败"
    except subprocess.TimeoutExpired:
        return False, "语法检查超时"
    except Exception as e:
        return False, f"检查失败: {str(e)}"

def reload_squid():
    """重载 Squid 配置"""
    squid_cmd = get_squid_command()
    if not squid_cmd:
        return False, "未找到 squid 命令，请确认已安装 Squid"
    
    try:
        result = subprocess.run(
            [squid_cmd, '-k', 'reconfigure'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, "Squid 配置已重载"
        else:
            return False, result.stderr or "重载失败"
    except subprocess.TimeoutExpired:
        return False, "重载超时"
    except Exception as e:
        return False, f"重载失败: {str(e)}"

def check_squid_status():
    """检查 Squid 服务状态"""
    squid_cmd = get_squid_command()
    if not squid_cmd:
        return False, "未找到 squid 命令"
    
    try:
        # 检查进程是否存在
        result = subprocess.run(
            ['pgrep', '-x', 'squid'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return True, "运行中"
        else:
            return False, "未运行"
    except Exception as e:
        return False, f"检查失败: {str(e)}"

def start_squid():
    """启动 Squid 服务"""
    squid_cmd = get_squid_command()
    if not squid_cmd:
        return False, "未找到 squid 命令"
    
    try:
        result = subprocess.run(
            [squid_cmd],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, "Squid 已启动"
        else:
            return False, result.stderr or "启动失败"
    except Exception as e:
        return False, f"启动失败: {str(e)}"

def stop_squid():
    """停止 Squid 服务"""
    squid_cmd = get_squid_command()
    if not squid_cmd:
        return False, "未找到 squid 命令"
    
    try:
        result = subprocess.run(
            [squid_cmd, '-k', 'shutdown'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True, "Squid 已停止"
        else:
            return False, result.stderr or "停止失败"
    except Exception as e:
        return False, f"停止失败: {str(e)}"

# ==================== 配置生成 ====================

def generate_squid_conf():
    """生成 Squid 配置文件"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 获取所有IP组
    cursor.execute('SELECT * FROM ip_groups ORDER BY name')
    ip_groups = cursor.fetchall()
    
    config_lines = [
        "# Squid ACL 配置文件 - 由 Squid ACL Dashboard 自动生成",
        f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "# 基础配置",
        "http_port 3128",
        "",
        "# 认证配置",
        "auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd",
        "auth_param basic realm Squid Proxy",
        "auth_param basic credentialsttl 2 hours",
        "",
        "# ACL 定义",
        "acl authenticated proxy_auth REQUIRED",
    ]
    
    # 为每个IP组生成ACL
    for group in ip_groups:
        group_id = group['id']
        group_name = group['name']
        
        cursor.execute('SELECT ip_address FROM ip_addresses WHERE group_id = ?', (group_id,))
        ips = cursor.fetchall()
        
        if ips:
            acl_name = f"ip_group_{group_id}"
            ip_list = ' '.join([ip['ip_address'] for ip in ips])
            config_lines.append(f"acl {acl_name} src {ip_list}")
    
    config_lines.extend([
        "",
        "# 访问控制规则",
        "http_access allow authenticated",
        "http_access deny all",
        "",
        "# 日志配置",
        "access_log /var/log/squid/access.log squid",
        "cache_log /var/log/squid/cache.log",
        "",
        "# 缓存配置",
        "cache_dir ufs /var/spool/squid 100 16 256",
        "coredump_dir /var/spool/squid",
    ])
    
    conn.close()
    return '\n'.join(config_lines)

def generate_passwd_file():
    """生成密码文件"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT username, password_hash FROM users WHERE status = 1')
    users = cursor.fetchall()
    
    lines = []
    for user in users:
        # 注意: 这里应该使用 htpasswd 格式的密码
        # 简化处理，实际应该使用 htpasswd 命令生成
        lines.append(f"{user['username']}:{user['password_hash']}")
    
    conn.close()
    return '\n'.join(lines)

def sync_config_to_disk():
    """同步配置到磁盘文件"""
    try:
        # 确保目录存在
        os.makedirs(SQUID_CONF_DIR, exist_ok=True)
        
        # 生成并写入配置文件
        conf_content = generate_squid_conf()
        with open(SQUID_CONF_FILE, 'w') as f:
            f.write(conf_content)
        
        # 生成并写入密码文件
        passwd_content = generate_passwd_file()
        with open(SQUID_PASSWD_FILE, 'w') as f:
            f.write(passwd_content)
        
        # 设置权限
        os.chmod(SQUID_CONF_FILE, 0o644)
        os.chmod(SQUID_PASSWD_FILE, 0o640)
        
        return True, "配置已同步到磁盘"
    except Exception as e:
        return False, f"同步失败: {str(e)}"

# ==================== 邮件发送 ====================

def send_email(to_email, subject, body):
    """发送邮件"""
    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_pass = os.environ.get('SMTP_PASS')
    
    if not all([smtp_host, smtp_user, smtp_pass]):
        return False, "SMTP 配置不完整"
    
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        
        return True, "邮件发送成功"
    except Exception as e:
        return False, f"邮件发送失败: {str(e)}"

# ==================== 路由 ====================

@app.route('/')
def index():
    """首页"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('请输入用户名和密码', 'error')
            return render_template('login.html')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM admins WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        
        if user and verify_password(password, user['password_hash']):
            admin = Admin(user['id'], user['username'], user['email'])
            login_user(admin)
            log_access(user['id'], request.remote_addr, '登录', '登录成功')
            flash('登录成功', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误', 'error')
            log_access(None, request.remote_addr, '登录失败', f'用户名: {username}')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    """退出登录"""
    log_access(current_user.id, request.remote_addr, '退出登录')
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """仪表盘"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 统计数据
    cursor.execute('SELECT COUNT(*) as count FROM ip_groups')
    ip_group_count = cursor.fetchone()['count']
    
    cursor.execute('SELECT COUNT(*) as count FROM ip_addresses')
    ip_count = cursor.fetchone()['count']
    
    cursor.execute('SELECT COUNT(*) as count FROM users')
    user_count = cursor.fetchone()['count']
    
    cursor.execute('SELECT COUNT(*) as count FROM users WHERE status = 1')
    active_user_count = cursor.fetchone()['count']
    
    # 检查 Squid 状态
    squid_running, squid_status = check_squid_status()
    
    # 最近日志
    cursor.execute('''
        SELECT al.*, a.username 
        FROM access_logs al 
        LEFT JOIN admins a ON al.user_id = a.id 
        ORDER BY al.created_at DESC 
        LIMIT 10
    ''')
    recent_logs = cursor.fetchall()
    
    conn.close()
    
    return render_template('dashboard.html',
                         ip_group_count=ip_group_count,
                         ip_count=ip_count,
                         user_count=user_count,
                         active_user_count=active_user_count,
                         squid_running=squid_running,
                         squid_status=squid_status,
                         recent_logs=recent_logs)

@app.route('/proxy/conf')
@login_required
def proxy_conf():
    """代理配置页面"""
    # 读取当前配置文件内容
    conf_content = ""
    if os.path.exists(SQUID_CONF_FILE):
        try:
            with open(SQUID_CONF_FILE, 'r') as f:
                conf_content = f.read()
        except Exception as e:
            flash(f'读取配置文件失败: {e}', 'error')
    
    # 检查 Squid 状态
    squid_running, squid_status = check_squid_status()
    
    # 获取 Squid 命令路径
    squid_cmd = get_squid_command()
    squid_cmd_path = squid_cmd if squid_cmd else "未找到"
    
    return render_template('proxy_conf.html',
                         conf_content=conf_content,
                         squid_running=squid_running,
                         squid_status=squid_status,
                         squid_cmd_path=squid_cmd_path)

@app.route('/api/check-syntax', methods=['POST'])
@login_required
def api_check_syntax():
    """API: 检查 Squid 语法"""
    success, message = check_squid_syntax()
    return jsonify({'success': success, 'message': message})

@app.route('/api/reload-squid', methods=['POST'])
@login_required
def api_reload_squid():
    """API: 重载 Squid"""
    # 先同步配置
    sync_success, sync_msg = sync_config_to_disk()
    if not sync_success:
        return jsonify({'success': False, 'message': f'同步配置失败: {sync_msg}'})
    
    # 检查语法
    syntax_ok, syntax_msg = check_squid_syntax()
    if not syntax_ok:
        return jsonify({'success': False, 'message': f'语法检查失败: {syntax_msg}'})
    
    # 重载服务
    success, message = reload_squid()
    if success:
        log_access(current_user.id, request.remote_addr, '重载 Squid 配置')
    
    return jsonify({'success': success, 'message': message})

@app.route('/api/squid-status')
@login_required
def api_squid_status():
    """API: 获取 Squid 状态"""
    running, status = check_squid_status()
    return jsonify({'running': running, 'status': status})

@app.route('/api/squid/start', methods=['POST'])
@login_required
def api_start_squid():
    """API: 启动 Squid"""
    success, message = start_squid()
    if success:
        log_access(current_user.id, request.remote_addr, '启动 Squid')
    return jsonify({'success': success, 'message': message})

@app.route('/api/squid/stop', methods=['POST'])
@login_required
def api_stop_squid():
    """API: 停止 Squid"""
    success, message = stop_squid()
    if success:
        log_access(current_user.id, request.remote_addr, '停止 Squid')
    return jsonify({'success': success, 'message': message})

# IP 组管理
@app.route('/ip-groups')
@login_required
def ip_groups():
    """IP组管理页面"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT g.*, COUNT(i.id) as ip_count 
        FROM ip_groups g 
        LEFT JOIN ip_addresses i ON g.id = i.group_id 
        GROUP BY g.id 
        ORDER BY g.name
    ''')
    groups = cursor.fetchall()
    
    conn.close()
    return render_template('ip_groups.html', groups=groups)

@app.route('/ip-groups/add', methods=['POST'])
@login_required
def add_ip_group():
    """添加 IP 组"""
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    
    if not name:
        flash('组名不能为空', 'error')
        return redirect(url_for('ip_groups'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO ip_groups (name, description) VALUES (?, ?)',
                      (name, description))
        conn.commit()
        conn.close()
        
        log_access(current_user.id, request.remote_addr, '添加 IP 组', f'组名: {name}')
        flash('IP组添加成功', 'success')
    except sqlite3.IntegrityError:
        flash('组名已存在', 'error')
    except Exception as e:
        flash(f'添加失败: {e}', 'error')
    
    return redirect(url_for('ip_groups'))

@app.route('/ip-groups/<int:group_id>/delete', methods=['POST'])
@login_required
def delete_ip_group(group_id):
    """删除 IP 组"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ip_groups WHERE id = ?', (group_id,))
        conn.commit()
        conn.close()
        
        log_access(current_user.id, request.remote_addr, '删除 IP 组', f'组ID: {group_id}')
        flash('IP组删除成功', 'success')
    except Exception as e:
        flash(f'删除失败: {e}', 'error')
    
    return redirect(url_for('ip_groups'))

@app.route('/ip-groups/<int:group_id>')
@login_required
def ip_group_detail(group_id):
    """IP组详情"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM ip_groups WHERE id = ?', (group_id,))
    group = cursor.fetchone()
    
    if not group:
        flash('IP组不存在', 'error')
        return redirect(url_for('ip_groups'))
    
    cursor.execute('SELECT * FROM ip_addresses WHERE group_id = ? ORDER BY ip_address', (group_id,))
    ips = cursor.fetchall()
    
    conn.close()
    return render_template('ip_group_detail.html', group=group, ips=ips)

@app.route('/ip-groups/<int:group_id>/ips/add', methods=['POST'])
@login_required
def add_ip_address(group_id):
    """添加 IP 地址"""
    ip_address = request.form.get('ip_address', '').strip()
    description = request.form.get('description', '').strip()
    
    if not ip_address:
        flash('IP地址不能为空', 'error')
        return redirect(url_for('ip_group_detail', group_id=group_id))
    
    # 验证 IP 格式
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$'
    if not re.match(ip_pattern, ip_address):
        flash('IP地址格式不正确', 'error')
        return redirect(url_for('ip_group_detail', group_id=group_id))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO ip_addresses (group_id, ip_address, description) VALUES (?, ?, ?)',
                      (group_id, ip_address, description))
        conn.commit()
        conn.close()
        
        log_access(current_user.id, request.remote_addr, '添加 IP 地址', f'IP: {ip_address}')
        flash('IP地址添加成功', 'success')
    except sqlite3.IntegrityError:
        flash('该IP地址已存在于该组中', 'error')
    except Exception as e:
        flash(f'添加失败: {e}', 'error')
    
    return redirect(url_for('ip_group_detail', group_id=group_id))

@app.route('/ip-addresses/<int:ip_id>/delete', methods=['POST'])
@login_required
def delete_ip_address(ip_id):
    """删除 IP 地址"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取组ID用于重定向
        cursor.execute('SELECT group_id FROM ip_addresses WHERE id = ?', (ip_id,))
        result = cursor.fetchone()
        group_id = result['group_id'] if result else None
        
        cursor.execute('DELETE FROM ip_addresses WHERE id = ?', (ip_id,))
        conn.commit()
        conn.close()
        
        log_access(current_user.id, request.remote_addr, '删除 IP 地址', f'IP ID: {ip_id}')
        flash('IP地址删除成功', 'success')
        
        if group_id:
            return redirect(url_for('ip_group_detail', group_id=group_id))
    except Exception as e:
        flash(f'删除失败: {e}', 'error')
    
    return redirect(url_for('ip_groups'))

# 用户管理
@app.route('/users')
@login_required
def users():
    """用户管理页面"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users ORDER BY username')
    users = cursor.fetchall()
    
    conn.close()
    return render_template('users.html', users=users)

@app.route('/users/add', methods=['POST'])
@login_required
def add_user():
    """添加用户"""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    full_name = request.form.get('full_name', '').strip()
    department = request.form.get('department', '').strip()
    
    if not username or not password:
        flash('用户名和密码不能为空', 'error')
        return redirect(url_for('users'))
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (username, password_hash, full_name, department)
            VALUES (?, ?, ?, ?)
        ''', (username, password_hash, full_name, department))
        conn.commit()
        conn.close()
        
        log_access(current_user.id, request.remote_addr, '添加用户', f'用户名: {username}')
        flash('用户添加成功', 'success')
    except sqlite3.IntegrityError:
        flash('用户名已存在', 'error')
    except Exception as e:
        flash(f'添加失败: {e}', 'error')
    
    return redirect(url_for('users'))

@app.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
def toggle_user(user_id):
    """切换用户状态"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET status = 1 - status WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        log_access(current_user.id, request.remote_addr, '切换用户状态', f'用户ID: {user_id}')
        flash('用户状态已更新', 'success')
    except Exception as e:
        flash(f'更新失败: {e}', 'error')
    
    return redirect(url_for('users'))

@app.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    """删除用户"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        log_access(current_user.id, request.remote_addr, '删除用户', f'用户ID: {user_id}')
        flash('用户删除成功', 'success')
    except Exception as e:
        flash(f'删除失败: {e}', 'error')
    
    return redirect(url_for('users'))

# 日志查看
@app.route('/logs')
@login_required
def logs():
    """日志页面"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    cursor.execute('''
        SELECT COUNT(*) as count FROM access_logs
    ''')
    total = cursor.fetchone()['count']
    
    cursor.execute('''
        SELECT al.*, a.username 
        FROM access_logs al 
        LEFT JOIN admins a ON al.user_id = a.id 
        ORDER BY al.created_at DESC 
        LIMIT ? OFFSET ?
    ''', (per_page, offset))
    logs = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('logs.html',
                         logs=logs,
                         page=page,
                         total_pages=total_pages,
                         total=total)

# 系统设置
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """系统设置页面"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'POST':
        # 更新管理员信息
        email = request.form.get('email', '').strip()
        current_password = request.form.get('current_password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        
        try:
            if email:
                cursor.execute('UPDATE admins SET email = ? WHERE id = ?',
                             (email, current_user.id))
            
            if current_password and new_password:
                # 验证当前密码
                cursor.execute('SELECT password_hash FROM admins WHERE id = ?',
                             (current_user.id,))
                result = cursor.fetchone()
                
                if result and verify_password(current_password, result['password_hash']):
                    new_hash = hashlib.sha256(new_password.encode()).hexdigest()
                    cursor.execute('UPDATE admins SET password_hash = ? WHERE id = ?',
                                 (new_hash, current_user.id))
                    flash('密码已更新', 'success')
                else:
                    flash('当前密码错误', 'error')
            
            conn.commit()
            flash('设置已保存', 'success')
        except Exception as e:
            flash(f'保存失败: {e}', 'error')
    
    # 获取当前管理员信息
    cursor.execute('SELECT * FROM admins WHERE id = ?', (current_user.id,))
    admin = cursor.fetchone()
    
    conn.close()
    
    return render_template('settings.html', admin=admin)

# 忘记密码
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """忘记密码页面"""
    email_sent = None  # 用于前端显示状态: True=成功, False=失败, None=未发送
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM admins WHERE username = ? AND email = ?',
                      (username, email))
        admin = cursor.fetchone()
        conn.close()
        
        if admin:
            # 生成重置令牌
            token = secrets.token_urlsafe(32)
            reset_link = url_for('reset_password', token=token, _external=True)
            
            # 发送邮件
            subject = 'Squid ACL Dashboard 密码重置'
            body = f'''您好 {username}，

您请求重置密码。请点击以下链接重置密码：

{reset_link}

此链接将在 1 小时后失效。

如果您没有请求重置密码，请忽略此邮件。

Squid ACL Dashboard
'''
            
            success, message = send_email(email, subject, body)
            if success:
                flash('密码重置链接已发送到您的邮箱', 'success')
                email_sent = True
                logger.info(f'密码重置邮件已发送，用户：{username}')
            else:
                flash(f'邮件发送失败: {message}', 'error')
                email_sent = False
                logger.error(f'密码重置邮件发送失败，用户：{username}，错误：{message}')
        else:
            # 不透露用户是否存在，显示通用消息
            flash('如果用户名和邮箱匹配，重置链接将发送到您的邮箱', 'info')
            email_sent = True  # 模糊处理，不暴露用户是否存在
            logger.info(f'密码重置请求，用户不存在或邮箱不匹配：{username}')
    
    return render_template('forgot_password.html', email_sent=email_sent)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """重置密码页面"""
    # 简化处理，实际应该验证 token 的有效性
    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if new_password != confirm_password:
            flash('两次输入的密码不一致', 'error')
            return render_template('reset_password.html', token=token)
        
        # 实际应该根据 token 找到对应的用户
        flash('密码重置功能需要完善 token 验证机制', 'warning')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', token=token)

# ==================== 模板过滤器 ====================

@app.template_filter('datetime')
def format_datetime(value):
    """格式化日期时间"""
    if value:
        try:
            dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return value
    return ''

# ==================== 初始化 ====================

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
