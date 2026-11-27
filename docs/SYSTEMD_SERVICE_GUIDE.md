# Systemd Service Agent

این Agent مستقل از Supervisor داخلی 30nA است و سرویس‌های system scope را با systemctl مدیریت می‌کند. نیازمند Systemd و مجوز کاربر اجراکننده است؛ sudo خودکار، تغییر فایل Unit یا راه‌اندازی سرویس بدون فرمان صریح ندارد. فقط یک نام دقیق با پسوند .service برای عملیات روی Unit پذیرفته می‌شود، نه wildcard یا آرگومان اضافی. عملیات با آرگومان مجزا بدون Shell اجرا می‌شود. وضعیت خروجی واقعی systemctl یا journalctl منتقل می‌شود؛ Status سرویس غیرفعال می‌تواند Exit Code غیرصفر داشته باشد. مهلت هر فرمان ۱۰ ثانیه است و Timeout لزوماً Job سیستم را لغو نمی‌کند.

## دستورات مشاهده

```bash
clear
30na -service -list
30na -service -active
30na -service -installed
30na -service -workers
30na -service -status -unit ssh.service
30na -service -logs -unit ssh.service
```

فهرست -list مربوط به Unitهای loaded است، -installed فایل‌های نصب‌شده و -active Unitهای active را نشان می‌دهد؛ active الزاماً SubState=running نیست. گزینه -workers وضعیت Supervisor و Host/Tunnel Worker را از IPC موجود می‌خواند و Worker متوقف را bootstrap نمی‌کند. Port PID فقط گزارش Supervisor است.

## دستورات تغییر وضعیت

نام نمونه را با سرویس واقعی مجاز خود جایگزین کنید. توقف یا Restart سرویس SSH ممکن است دسترسی راه دور شما را قطع کند. در TUI هر تغییر نیاز به تأیید دارد؛ CLI خود یک فرمان صریح است.

```bash
clear
30na -service -start -unit example.service
30na -service -stop -unit example.service
30na -service -restart -unit example.service
30na -service -reload -unit example.service
30na -service -enable -unit example.service
30na -service -disable -unit example.service
30na -service -daemon-reload
```

Enable/disable وضعیت شروع در Boot را تغییر می‌دهد و معادل Start/Stop نیست. Logs آخرین ۵۰ خط journal قابل دسترسی را نشان می‌دهد. در محیط بدون Systemd خطا گزارش می‌شود. Agent هیچ تنظیمات SSH، Firewall یا Host Key را خودکار تغییر نمی‌دهد.

## فهرست مدیریت‌شده

```bash
clear
30na -service -managed
```

تاریخچه موفق Start/Restart از همین Agent در managed-services.db همان XDG ذخیره می‌شود؛ Stop موفق نام را حذف می‌کند. Dashboard در حالت Hide، اشتراک این تاریخچه با Unitهای Active را نمایش می‌دهد. این تاریخچه مالکیت انحصاری یا وضعیت فعلی را ثابت نمی‌کند. Unitهای قبلی که از خارج برنامه مدیریت شده‌اند، به‌صورت خودکار وارد تاریخچه نمی‌شوند.
