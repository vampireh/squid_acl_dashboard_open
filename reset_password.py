#!/usr/bin/env python3
"""
Squid ACL Dashboard - 密码重置工具
用于 root 用户在命令行重置用户密码（当邮件找回功能不可用时）

使用方法:
    python3 reset_password.py <用户名> <新密码>
    
示例:
    python3 reset_password.py admin newpassword123
    python3 reset_password.py user01 mypassword
"""

import sys
import os
import sqlite3
from werkzeug.security import generate_password_hash

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'squid_acl.db')


def reset_password(username, new_password):
    """重置指定用户的密码"""
    
    # 检查数据库文件是否存在
    if not os.path.exists(DB_PATH):
        print(f"❌ 错误：数据库文件不存在: {DB_PATH}")
        return False
    
    try:
        # 连接数据库
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 检查用户是否存在
        cursor.execute('SELECT id, username, email FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if not user:
            print(f"❌ 错误：用户 '{username}' 不存在")
            
            # 显示所有用户列表
            cursor.execute('SELECT username, email, is_admin FROM users')
            users = cursor.fetchall()
            if users:
                print("\n📋 现有用户列表:")
                print("-" * 50)
                print(f"{'用户名':<20} {'邮箱':<25} {'管理员'}")
                print("-" * 50)
                for u in users:
                    admin_flag = "是" if u[2] else "否"
                    print(f"{u[0]:<20} {u[1] or 'N/A':<25} {admin_flag}")
                print("-" * 50)
            else:
                print("⚠️  数据库中没有用户")
            
            conn.close()
            return False
        
        # 生成新密码哈希
        hashed_password = generate_password_hash(new_password)
        
        # 更新密码
        cursor.execute(
            'UPDATE users SET password = ? WHERE username = ?',
            (hashed_password, username)
        )
        conn.commit()
        
        # 验证更新
        cursor.execute('SELECT id FROM users WHERE username = ? AND password = ?', 
                      (username, hashed_password))
        if cursor.fetchone():
            print(f"✅ 密码重置成功！")
            print(f"   用户名: {username}")
            print(f"   新密码: {new_password}")
            print(f"   用户ID: {user[0]}")
            print(f"   邮箱: {user[2] or 'N/A'}")
            conn.close()
            return True
        else:
            print("❌ 错误：密码更新失败")
            conn.close()
            return False
            
    except sqlite3.Error as e:
        print(f"❌ 数据库错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 错误: {e}")
        return False


def list_users():
    """列出所有用户"""
    
    if not os.path.exists(DB_PATH):
        print(f"❌ 错误：数据库文件不存在: {DB_PATH}")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, username, email, is_admin, created_at FROM users ORDER BY id')
        users = cursor.fetchall()
        
        if not users:
            print("⚠️  数据库中没有用户")
            conn.close()
            return
        
        print("\n📋 用户列表:")
        print("-" * 80)
        print(f"{'ID':<5} {'用户名':<20} {'邮箱':<30} {'管理员':<8} {'创建时间'}")
        print("-" * 80)
        
        for user in users:
            admin_flag = "是" if user[3] else "否"
            created_at = user[4] if user[4] else "N/A"
            email = user[2] if user[2] else "N/A"
            print(f"{user[0]:<5} {user[1]:<20} {email:<30} {admin_flag:<8} {created_at}")
        
        print("-" * 80)
        print(f"总计: {len(users)} 个用户\n")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ 错误: {e}")


def show_help():
    """显示帮助信息"""
    help_text = """
╔══════════════════════════════════════════════════════════════════╗
║           Squid ACL Dashboard - 密码重置工具                      ║
╚══════════════════════════════════════════════════════════════════╝

用法:
    python3 reset_password.py <用户名> <新密码>     重置指定用户密码
    python3 reset_password.py --list               列出所有用户
    python3 reset_password.py --help               显示此帮助信息

示例:
    # 重置 admin 用户的密码
    python3 reset_password.py admin newpassword123
    
    # 重置普通用户密码
    python3 reset_password.py user01 mypassword
    
    # 查看所有用户
    python3 reset_password.py --list

注意:
    • 此脚本需要 root 权限运行
    • 数据库路径: /opt/squid_acl_dashboard/squid_acl.db
    • 密码修改后立即生效，无需重启服务
"""
    print(help_text)


def main():
    # 检查参数
    if len(sys.argv) < 2:
        print("❌ 错误：参数不足")
        print("\n使用方法: python3 reset_password.py <用户名> <新密码>")
        print("          python3 reset_password.py --help")
        sys.exit(1)
    
    # 处理选项
    if sys.argv[1] in ['--help', '-h', 'help']:
        show_help()
        sys.exit(0)
    
    if sys.argv[1] in ['--list', '-l', 'list']:
        list_users()
        sys.exit(0)
    
    # 重置密码
    if len(sys.argv) < 3:
        print("❌ 错误：请提供新密码")
        print("\n使用方法: python3 reset_password.py <用户名> <新密码>")
        sys.exit(1)
    
    username = sys.argv[1]
    new_password = sys.argv[2]
    
    # 密码长度检查
    if len(new_password) < 6:
        print("⚠️  警告：密码长度小于 6 位，建议设置更复杂的密码")
        response = input("是否继续? (y/N): ")
        if response.lower() != 'y':
            print("已取消")
            sys.exit(0)
    
    # 执行密码重置
    success = reset_password(username, new_password)
    
    if success:
        print("\n💡 提示：用户现在可以使用新密码登录了")
        sys.exit(0)
    else:
        print("\n❌ 密码重置失败")
        sys.exit(1)


if __name__ == '__main__':
    main()
