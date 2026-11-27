# Remote tunnel architecture and inventory

مرجع طراحی، منطق دو VPS در مخزن 30nA-Tunnel در revision 7e3a39eab3cfe82ce7b949daba6c1f89bfa08a51 است؛ وابستگی اجرایی به آن ایجاد نشده است.

| Role | Forward | Reverse |
|---|---|---|
| SSH client / service | Local gateway | Remote destination |
| SSH server | Remote destination | Local gateway |
| Listener | Local Port | Local Port |
| Destination | Remote loopback:Remote Port | Remote loopback:Remote Port |

جهت جریان کاربر در هر دو حالت Local → Remote است. قرارداد فعلی worker برای Reverse قدیمی این جهت را ندارد؛ به‌صورت خودکار تغییر یا تبدیل نمی‌شود. جایگزینی ساخت Tunnel هنوز پیاده‌سازی نشده است.

## مرحله اول: مشاهده سرویس‌های موجود

```bash
clear
30na -tunnel -discover
30na -tunnel -discover -remote-id 2
```

منوی Tunnel گزینه Discover external SSH tunnel services دارد. این دستور با کلید مدیریت ثبت‌شده و Host Key معتبر، فقط inventory می‌خواند. برنامه روی Remote فایل یا Unit نمی‌نویسد و حتی برای مشاهده نیاز به نصب نسخه 30nA روی Remote ندارد؛ Python3، systemctl و ss لازم‌اند. محدوده جستجو فقط نام‌های شناخته‌شده ssh-tunnel-*, stm-r-*, nt-*, gr02-iran-reverse و 30na-tunnel-* و ExecStart مستقیم SSH با یک -L یا -R و مقصد 127.0.0.1 است. همه Tunnelهای ممکن قابل کشف نیستند.

Machine ID هش‌شده، IPهای رابط، آدرس SSH و نتیجه DNS برای تطبیق پیشنهادی Host استفاده می‌شوند. Alias تاییدشده Local به ID 1 نگاشت می‌شود؛ شناسه‌های Remote تکراری به‌صورت AMBIGUOUS گزارش می‌شوند. هیچ تطبیق DNS جایگزین احراز هویت نیست. سرویس فعال به معنی اتصال سالم نیست؛ MATCHED_PID یعنی Listener Forward با MainPID همخوان است، SSHD_OBSERVED یعنی Listener با مالک sshd برای Reverse مشاهده شد (مالکیت دقیق Tunnel اثبات نشده است). ABSENT، UNKNOWN و UNVERIFIED_OWNER_OR_BIND نیز گزارش می‌شوند. هیچ تست TCP فعال یا تغییر پورت انجام نمی‌شود. مالکیت همه Unitهای کشف‌شده external است، نه 30nA؛ Stop قدیمی آن‌ها را حذف نمی‌کند.

حداکثر 16 Remote در هر بررسی و 64 Unit شناخته‌شده در هر Host؛ خطا و داده ناقص به‌صورت UNKNOWN/PARTIAL و Exit 1 گزارش می‌شود. حالت COMPLETE فقط پوشش بررسی پشتیبانی‌شده است، نه سلامت Tunnel.

## مرحله بعد: ساخت مدیریت‌شده

- بعد از پذیرش Onboarding و کشف خواندنی، مدل پایدار دو VPS با کلید اختصاصی تولیدشده روی SSH client، حساب محدود روی SSH server و کنترل Host Key دقیق.
- اعتبارسنجی سیاست sshd و پورت قبل از تغییر، عدم توقف سرویس خارجی، ثبت مالکیت و مراحل rollback در داده پایدار.
- واحد Systemd اختصاصی روی SSH client واقعی، تایید Listener و تست انتقال TCP مستقل. در Reverse Listener روی Local است.
- حذف فقط منابع متعلق به Tunnel جدید، حفظ رکورد cleanup در صورت شکست. تست OpenSSH واقعی با دو endpoint ایزوله، و تست Systemd/sshd policy بدون تغییر سرور عملیاتی.
