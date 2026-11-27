# Domain Name و سرویس SSH

مقدار -domain یا -ip در Host و Tunnel می‌تواند IP یا نام کامل DNS باشد. نام دامنه ASCII/Punycode به حروف کوچک و بدون نقطه نهایی ذخیره می‌شود. URL، user@domain، hostname تک‌بخشی و domain:port پذیرفته نمی‌شوند. نام دامنه در SQLite موجود ذخیره می‌شود؛ Migration لازم نیست. DNS در زمان اتصال توسط OpenSSH انجام می‌شود و ثبت یک نام به معنی مجاز شدن IPهای آن یا اعتبارسنجی مالکیت نیست. تنظیمات SSH و تأیید Host Key همچنان ضروری‌اند.

## ثبت و اتصال

```bash
clear
30na -host -add -domain ssh.example.test
30na -host -ssh -domain ssh.example.test
30na -tunnel -forward -domain ssh.example.test -listen 5555 -target 127.0.0.1 -target-port 443
30na -tunnel -list
```

## تنظیم User

در فایل ~/.ssh/config کاربر اجراکننده برنامه، نام کاربری و در صورت نیاز Port و IdentityFile را تعیین کنید. مثال (فایل تنظیمات است، دستور Shell نیست):

```sshconfig
Host ssh.example.test
    User root
    Port 22
    StrictHostKeyChecking yes
```

از حساب غیر root در صورت امکان استفاده کنید. Host Key را پیش از اتصال غیرتعاملی از منبع مطمئن تأیید کنید.

## Systemd مستقل از 30na

OpenSSH مستقیماً نام دامنه می‌پذیرد. این مثال یک خط ExecStart برای Unit مستقل است؛ دامنه نمونه را جایگزین کنید. Listener پیش‌فرض توصیه‌شده فقط محلی است:

```systemd
ExecStart=/usr/bin/ssh -N -T -c aes128-gcm@openssh.com -o BatchMode=yes -o ServerAliveInterval=60 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -L 127.0.0.1:5555:127.0.0.1:443 root@ssh.example.test
```

اگر عمداً Listener را روی 0.0.0.0 باز می‌کنید، دسترسی به پورت را با Firewall و کنترل دسترسی مقصد محدود کنید. سرویس مستقل تابع سیاست بازیابی و ثبت Host در 30na نیست. این پروژه Unit Systemd ایجاد یا فعال نمی‌کند و تنظیمات Firewall یا sshd را تغییر نمی‌دهد. برای جلوگیری از درخواست رمز در Service، کلید SSH مجاز و known_hosts برای کاربر اجراکننده سرویس ضروری است.
