# Squid ACL Dashboard

高校网络代理访问控制系统（开源演示版）

## 功能特性

- 访问日志实时采集与多维统计
- ABCD 四类终端分级授权管控
- 配置管理界面（IP分组/白名单/用户/squid.conf）
- 管理员登录认证（登录/改密/找回密码）
- 自动数据清理（180天前记录）

## ABCD 管控机制

| 分组 | IP来源 | 密码 | 访问范围 |
|------|--------|------|---------|
| A类  | VIP白名单 | 免密 | 互联网全通 |
| B类  | 员工账号 | 密码 | 互联网全通 |
| C类  | 受控设备 | 免密 | 仅白名单 |
| D类  | 受控员工 | 密码 | 仅白名单 |
| 其他 | 未授权   | —    | 拒绝访问  |

## 快速部署

```bash
pip install -r requirements.txt
python app.py
# 访问 http://localhost:5001/squid-acl/
```

默认管理员：`admin` / `admin@123`

## 目录结构

```
squid_acl_dashboard/
├── app.py              # 主程序
├── acl_dashboard.db    # SQLite 数据库（gitignore）
├── templates/          # 前端页面
├── etc/squid/          # Squid 配置示例
│   ├── squid.conf
│   ├── ip_group_[a-d].txt
│   ├── passwd
│   └── allow.txt
└── logs/              # 运行时日志（gitignore）
```

## ⚠️ 开源声明

本版本中所有 IP、域名、用户名等数据均为**随机生成的示例数据**，不代表任何真实机构或人员。
