# وضعیت توسعه Layer 1

این صفحه نقشه راه و شواهد تاریخی است؛ وضعیت واقعی Branch، Commit و PR را از GitHub بررسی کنید.

| مؤلفه | وضعیت |
|---|---|
| CLI Discovery، Calculator، System، Menu | پیاده‌سازی‌شده |
| Host Agent / Service Agent / Port Agent | ادغام‌شده در PR #3 |
| Tunnel Agent Integration | ادغام‌شده در PR #4 با پذیرش مشروط |
| Tunnel Startup Readiness & Failure Reporting | ادغام‌شده در PR #6؛ CI 35/35 موفق |
| Session Restoration Policy | PR #7؛ بازیابی Opt-in محدود و تست واقعی |
| CI Automation | ادغام‌شده در PR #5؛ CI اولیه 27/27 موفق |
| Final Integration & Acceptance | PR #7؛ CI شاخه اصلی 47/47 موفق |
| Domain Name Support | توسعه افزایشی؛ CI همین PR را بررسی کنید |

## شواهد تاریخی
- PR #3: گزارش 19/19 تست موفق.
- PR #4: گزارش 27/27 تست موفق (8 Integration، 19 Regression)، و Forward/Reverse و انتقال داده با OpenSSH واقعی در محیط Loopback ایزوله.
- تست‌های Tunnel شامل Mock و Real SSH اختیاری هستند؛ CI اجرای Real SSH را فعال می‌کند. نتیجه تاریخی جایگزین تست Commit جدید نیست.
- PR #6: 35/35 تست موفق شامل 13 Mock و 3 Real SSH؛ Readiness با پاسخ OpenSSH تأیید می‌شود.
- پذیرش تاریخی PR #4 مشروط بود: وضعیت starting اثبات آمادگی اتصال نیست؛ خطای تأخیری احراز هویت تأیید نشده؛ Session پس از Crash بازیابی نمی‌شود؛ OpenSSH مالک پورت‌های Forwarding است.
- تقدم Commit/Push بر Regression در مأموریت قبلی انحراف ثبت‌شده بود. تست‌های بعدی روی SHA نهایی طبق گزارش موفق بودند.

## ترتیب ادامه
CI و Readiness ادغام شده‌اند. بازیابی محدود بعد از Crash، رفع ریسک هم‌زمانی IPC و تست تکمیلی در تغییر جدید؛ پذیرش نهایی وابسته به CI و وضعیت GitHub است. بعد از تغییر قراردادها مستندات CLI و معماری را به‌روز کنید. راهنمای فشرده ایجنت‌ها: [AGENTS.md](../AGENTS.md).

مرجع شواهد و محدوده نهایی: [RELEASE_ACCEPTANCE.md](RELEASE_ACCEPTANCE.md). راهنمای رفع خطا و ارتقا در [TROUBLESHOOTING_GUIDE.md](TROUBLESHOOTING_GUIDE.md) و [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) قرار دارد.

## Endpoint model

Local ID 1, stable remote IDs, fixed local/remote ports. Validate current PR CI.

نسخه قبلی PR #10 با 85/85 CI تأیید شده است. تغییر قرارداد Tunnel در PR جدید با تست جداگانه بررسی می‌شود.

## Host onboarding

Host onboarding verifies the management key over SSH before saving the host. It requires no 30nA installation on the peer.

## Remote topology

PR #12: 105/105 passed on tested merge tree. External tunnel inventory is a separate read-only phase; new two-VPS provisioning remains pending. See [design](REMOTE_TUNNEL_ARCHITECTURE.md).

## Two-VPS reverse

PR #13 discovery: 111/111 on tested merge tree. New numbered reverse dispatches to the remote systemd engine; exact final PR CI required. Production two-VPS acceptance remains pending.

## Bootstrap installer

Automated Ubuntu prerequisites, clean main checkout/update and root SSH/key preparation; dependency-free peer deployment remains unchanged. CI required for exact head.


## Release candidate preparation

Host additions require verified key-only SSH from the current controller. Enrollment prepares an Ed25519 management identity on a fresh controller and configures ordinary root SSH login. Tunnel destinations must already be registered and pass SSH verification. Temporary Forward remains a compatibility CLI path; the primary menu creates persistent Forward and Reverse services. The first tagged release candidate is v1.0.0-rc.1, published only after successful main Linux regression. Final multi-machine chain and reboot validation remain the operator acceptance step.
