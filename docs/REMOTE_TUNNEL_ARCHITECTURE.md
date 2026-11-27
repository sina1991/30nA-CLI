# Remote tunnel architecture and inventory

مرجع طراحی، منطق دو VPS در مخزن 30nA-Tunnel در revision 7e3a39eab3cfe82ce7b949daba6c1f89bfa08a51 است؛ وابستگی اجرایی به آن ایجاد نشده است.

| Role | Forward | Reverse |
|---|---|---|
| SSH client / service | Local gateway | Remote destination |
| SSH server | Remote destination | Local gateway |
| Listener | Local Port | Local Port |
| Destination | Remote loopback:Remote Port | Remote loopback:Remote Port |

جهت جریان کاربر در هر دو حالت Local → Remote است. قرارداد فعلی worker برای Reverse قدیمی این جهت را ندارد؛ به‌صورت خودکار تغییر یا تبدیل نمی‌شود. موتور Reverse جدید برای قرارداد شماره‌دار در این شاخه پیاده‌سازی شده است؛ رکوردهای قدیمی با legacy_topology=yes نمایش داده می‌شوند.

## مرحله اول: مشاهده سرویس‌های موجود

```bash
clear
30na -tunnel -discover
30na -tunnel -discover -remote-id 2
```

منوی Tunnel گزینه Discover external SSH tunnel services دارد. این دستور با کلید مدیریت ثبت‌شده و Host Key معتبر، فقط inventory می‌خواند. برنامه روی Remote فایل یا Unit نمی‌نویسد و حتی برای مشاهده نیاز به نصب نسخه 30nA روی Remote ندارد؛ Python3، systemctl و ss لازم‌اند. محدوده جستجو فقط نام‌های شناخته‌شده ssh-tunnel-*, stm-r-*, nt-*, gr02-iran-reverse و 30na-tunnel-* و ExecStart مستقیم SSH با یک -L یا -R و مقصد 127.0.0.1 است. همه Tunnelهای ممکن قابل کشف نیستند.

Machine ID هش‌شده، IPهای رابط، آدرس SSH و نتیجه DNS برای تطبیق پیشنهادی Host استفاده می‌شوند. Alias تاییدشده Local به ID 1 نگاشت می‌شود؛ شناسه‌های Remote تکراری به‌صورت AMBIGUOUS گزارش می‌شوند. هیچ تطبیق DNS جایگزین احراز هویت نیست. سرویس فعال به معنی اتصال سالم نیست؛ MATCHED_PID یعنی Listener Forward با MainPID همخوان است، SSHD_OBSERVED یعنی Listener با مالک sshd برای Reverse مشاهده شد (مالکیت دقیق Tunnel اثبات نشده است). ABSENT، UNKNOWN و UNVERIFIED_OWNER_OR_BIND نیز گزارش می‌شوند. هیچ تست TCP فعال یا تغییر پورت انجام نمی‌شود. مالکیت همه Unitهای کشف‌شده external است، نه 30nA؛ Stop قدیمی آن‌ها را حذف نمی‌کند.

حداکثر 16 Remote در هر بررسی و 64 Unit شناخته‌شده در هر Host؛ خطا و داده ناقص به‌صورت UNKNOWN/PARTIAL و Exit 1 گزارش می‌شود. حالت COMPLETE فقط پوشش بررسی پشتیبانی‌شده است، نه سلامت Tunnel.

## Reverse مدیریت‌شده

```bash
clear
30na -tunnel -reverse -ip 192.0.2.1 -local-port 5555 -remote-id 2 -remote-port 443
30na -tunnel -list
30na -tunnel -delete -id TUNNEL_ID
```

آدرس نمونه را با IPv4 واقعی Local جایگزین کنید. موتور ابتدا با کلید مدیریت معتبر به Remote وصل می‌شود و Machine ID، root و پورت Local را بررسی می‌کند. کلید اختصاصی روی Remote ساخته می‌شود. حساب محدود ntr-ID روی Local با Match User و PermitListen دقیق، MaxSessions 0 و AllowTcpForwarding remote ایجاد می‌شود. فقط public key مبادله می‌شود. sshd -t و sshd -T قبل از reload بررسی می‌شوند. تغییر فقط برای حساب اختصاصی است؛ هیچ سرویس قبلی Stop یا Restart نمی‌شود. Root، Ubuntu/systemd، SSH پورت 22 و IPv4 قابل دسترس Local لازم‌اند؛ برای Local ID 1 پیش‌فرض Loopback است و اگر چند IP وجود دارد باید -ip مشخص شود. IPv6 و SSH port سفارشی Local در این نسخه پشتیبانی نمی‌شوند.

روی Remote واحد 30na-tunnel-ID.service با Restart=always و Host Key صریح Local ساخته و فعال می‌شود. Listener روی Local Port باید به حساب اختصاصی تعلق داشته باشد تا ready گزارش شود؛ این تأیید انتقال end-to-end به Xray نیست. Stop واحد را متوقف و از Boot غیرفعال می‌کند. Delete واحد، فایل‌ها و حساب همان ID را پاک می‌کند. شکست cleanup باعث حفظ رکورد می‌شود. Reverse جدید مستقل از عمر Worker است و -restore نمی‌گیرد؛ Forward پایدار با گزینهٔ -persistent ایجاد می‌شود. فهرست ترکیبی است و Legacy Reverse به‌صورت خودکار تبدیل نمی‌شود.

آزمون‌های orchestration با منابع شبیه‌سازی‌شده، parser واقعی sshd و انتقال TCP با OpenSSH واقعی loopback انجام می‌شوند. اجرای کامل root provisioning روی دو VPS واقعی و سلامت VPN کاربر نیاز به پذیرش عملیاتی دارند. هیچ Tunnel خارجی به‌طور خودکار Adopt نمی‌شود.

اگر فایل‌های sshd_config.d در سیاست مؤثر sshd خوانده نشوند، موتور فقط همان Match User محدود به شناسه Reverse را به انتهای sshd_config اضافه می‌کند؛ هیچ wildcard یا تنظیم عمومی جدیدی فعال نمی‌شود. مالکیت و مجوز فایل حفظ می‌شود و جایگزینی اتمی است. سیاست مؤثر پیش از Reload اعتبارسنجی می‌شود. هنگام Delete یا rollback فقط بلوک دقیق همان شناسه حذف می‌شود؛ در صورت تغییر دستی بلوک، cleanup متوقف و رکورد حفظ می‌شود.
