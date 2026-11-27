# وضعیت توسعه Layer 1

این صفحه نقشه راه و شواهد تاریخی است؛ وضعیت واقعی Branch، Commit و PR را از GitHub بررسی کنید.

| مؤلفه | وضعیت |
|---|---|
| CLI Discovery، Calculator، System، Menu | پیاده‌سازی‌شده |
| Host Agent / Service Agent / Port Agent | ادغام‌شده در PR #3 |
| Tunnel Agent Integration | ادغام‌شده در PR #4 با پذیرش مشروط |
| Tunnel Startup Readiness & Failure Reporting | باز |
| Session Restoration Policy | باز؛ بدون بازیابی خودکار در نسخه فعلی |
| CI Automation | Workflow پیشنهادی؛ نتیجه اجرا باید از GitHub بررسی شود |
| Final Integration & Acceptance | باز |

## شواهد تاریخی
- PR #3: گزارش 19/19 تست موفق.
- PR #4: گزارش 27/27 تست موفق (8 Integration، 19 Regression)، و Forward/Reverse و انتقال داده با OpenSSH واقعی در محیط Loopback ایزوله.
- تست‌های خودکار فعلی Tunnel از Mock SSH استفاده می‌کنند. نتیجه تاریخی جایگزین تست Commit جدید نیست.
- پذیرش PR #4 مشروط بود: وضعیت starting اثبات آمادگی اتصال نیست؛ خطای تأخیری احراز هویت تأیید نشده؛ Session پس از Crash بازیابی نمی‌شود؛ OpenSSH مالک پورت‌های Forwarding است.
- تقدم Commit/Push بر Regression در مأموریت قبلی انحراف ثبت‌شده بود. تست‌های بعدی روی SHA نهایی طبق گزارش موفق بودند.

## ترتیب ادامه
ابتدا CI برای اعتبارسنجی تغییرات؛ سپس Readiness و گزارش خطا، سیاست Session Restoration، بررسی امنیت/پایداری و تست واقعی OpenSSH، و پذیرش نهایی. بعد از تغییر قراردادها مستندات CLI و معماری را به‌روز کنید. راهنمای فشرده ایجنت‌ها: [AGENTS.md](../AGENTS.md).
