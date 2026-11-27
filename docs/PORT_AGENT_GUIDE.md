# Port Inspection Agent

ایجنت عمومی -port مستقل از تخصیص‌دهنده داخلی Port Worker است. با ss از iproute2، Socketهای محلی را در Network Namespace جاری مشاهده می‌کند. هیچ اتصال یا پورتی را تصاحب نمی‌کند و هیچ PID یا سرویس خارجی را متوقف نمی‌کند.

```bash
clear
30na -port -list
30na -port -all
30na -port -list -tcp
30na -port -list -udp
30na -port -summary
30na -port -check 5555
30na -port -check 443 -tcp
```

-list شامل Listenerهای TCP و UDP بدون اتصال است؛ -all شامل سایر وضعیت‌های Socket نیز می‌شود. -check همه وضعیت‌های محلی را برای یک شماره پورت بررسی می‌کند. نبودن رکورد، تضمین امکان Bind نیست. مالک و PID از ss و نام Unit سرویس از cgroup همان PID در صورت دسترسی استخراج می‌شود؛ ? به معنی نامعلوم یا عدم دسترسی است. شمارنده T/U در Status Bar تعداد شماره پورت‌های متمایز TCP/UDP در -list است، نه تعداد Socket یا سرویس. مشاهده Snapshot با Refresh به‌روز می‌شود؛ تغییر Tunnel یا Systemd مقدار شمارنده را نامعلوم می‌کند. برای توقف سرویس شناخته‌شده از Agent سرویس‌ها و تأیید صریح استفاده کنید. دسترسی root برای دیدن مالک بعضی Socketها ضروری است؛ ابزار به‌صورت خودکار sudo اجرا نمی‌کند. مالک گزارش‌شده ممکن است در فاصله مشاهده تغییر کند.
