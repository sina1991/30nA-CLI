# عیب‌یابی CLI و Tunnel

## وضعیت اتصال

```bash
clear
30na -host -list
30na -tunnel -list
```

- starting: احراز هویت یا Forwarding در حال انجام است؛ انتظار محدود است.
- ready: OpenSSH راه‌اندازی Forwarding را تأیید کرده است. دسترسی Target، مجوز برنامه مقصد و سلامت جریان داده را جداگانه بررسی کنید.
- failed: راه‌اندازی یا فرایند SSH ناموفق بوده است. Reason علت دسته‌بندی‌شده است. رکورد با -stop -id حذف می‌شود؛ هیچ سیگنالی به PID چاپ‌شده ارسال نکنید.

| Reason | اقدام |
|---|---|
| authentication_failed | کلید، User و Port در تنظیمات OpenSSH را بررسی کنید. SSH باید غیرتعاملی باشد. |
| host_key_failed | هویت واقعی سرور و known_hosts را با منبع قابل اعتماد بررسی کنید؛ بررسی Host Key را غیرفعال نکنید. |
| connection_failed / startup_timeout | مسیر شبکه، دسترسی SSH و تنظیمات اتصال را بررسی کنید. |
| port_collision / forwarding_rejected | پورت آزاد و سیاست AllowTcpForwarding و GatewayPorts=no در سرور مجاز خود را بررسی کنید. هیچ Foreign Listener را متوقف نکنید. |
| forwarding_command_failed / ssh_exited | نسخه OpenSSH، تنظیمات مجاز و وضعیت SSH را بررسی و در صورت نیاز یک Session جدید ایجاد کنید. |
| host_not_registered / restoration_start_failed | ثبت Host، دسترسی Worker و شرایط بازیابی را بررسی کنید. |
| restoration_storage_failed / recovery_rate_limit / recovery_worker_start_failed | بازیابی خودکار تضمین نشده است؛ علت را بررسی کنید و در صورت نیاز Session را صریحاً از نو بسازید. |

## بازیابی و توقف

```bash
clear
30na -tunnel -stop -id TUNNEL_ID
```

گزینه -restore فقط برای Crash شدن Tunnel Worker و Session آماده در طول عمر Service Agent است. قطع عادی SSH، توقف صریح، Restart سرویس یا Reboot باعث بازیابی خودکار نمی‌شود. جریان TCP قبلی قابل بازگردانی نیست. بازیابی مجدد نیازمند ثبت Host و احراز هویت است.

## ناسازگاری نسخه

اگر پیام Restart Service Agent ظاهر شد، ابتدا Sessionهای فعال را بررسی کنید. فرمان زیر از ریشه Checkout و با همان کاربر و XDG_DATA_HOME اجرا می‌شود؛ همه Sessionها را قطع می‌کند.

```bash
clear
python3 -m thirtyna.runtime.service shutdown
```

سپس نصب/ارتقا را مطابق [راهنمای نصب](INSTALLATION_GUIDE.md) انجام دهید. تنظیمات sshd یا Firewall به‌صورت خودکار تغییر نمی‌کند. در گزارش خطا، SHA، سیستم‌عامل، Exit Code و Reason را بدون کلید خصوصی یا داده محرمانه ذکر کنید.

## Host Key

در خطای host_key_failed، اتصال مستقیم با Host Agent و همان کاربر/تنظیمات OpenSSH را بررسی کنید. Fingerprint را از کنسول معتبر سرور یا مدیر آن تأیید کنید. در صورت تغییر کلید، دلیل تغییر را پیش از اصلاح known_hosts بررسی کنید. بررسی هویت را غیرفعال نکنید. بعد از احراز هویت غیرتعاملی موفق Tunnel را دوباره ایجاد کنید.
