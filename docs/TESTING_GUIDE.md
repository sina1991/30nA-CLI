# اجرای تست‌ها

از ریشه مخزن اجرا کنید.

```bash
clear
python3 -m unittest discover -s tests -v
```

تست‌ها CLI را با subprocess اجرا می‌کنند. تست تعاملی از PTY، تست توسعه‌پذیری از یک package موقت و تست نصب از PREFIX و XDG_DATA_HOME ایزوله استفاده می‌کند. اجرای Pipe و redirection در Bash واقعی انجام می‌شود. تست Host یک ssh آزمایشی در PATH می‌گذارد که آرگومان‌ها را ثبت می‌کند و موفقیت یا خطا برمی‌گرداند.

## CI و Tunnel

Workflow در `.github/workflows/ci.yml` روی PR به main و Push به main، مجموعه کامل unittest را در Ubuntu اجرا می‌کند. نتیجه را برای SHA دقیق بررسی کنید. وجود Workflow به‌تنهایی به معنی اجرای موفق نیست. تست‌های Mock و Real SSH جدا هستند. CI با THIRTYNA_REAL_SSH=1 و نصب openssh-server یک sshd ایزوله روی Loopback با کلید موقت اجرا می‌کند. برای اجرای محلی Real SSH به کاربر غیر root، sudo بدون رمز برای sshd آزمایشی و مسیر /run/sshd نیاز است. بدون opt-in، تست‌های Real SSH با Skip مشخص می‌شوند. برای تست محلی از همان دستور بالا استفاده کنید.

تست‌های Recovery علاوه بر حالت پیش‌فرض بدون بازیابی، Opt-in، لغو بازیابی پس از توقف صریح، لغو مجوز Host، درخواست‌های هم‌زمان و انتقال داده واقعی بعد از Crash را بررسی می‌کنند. اجرای CI باید بدون Skip باشد. برای ارتقا از نسخه‌ای با Service Agent قدیمی، ابتدا سرویس را متوقف کنید؛ این کار Sessionهای فعال را قطع می‌کند.

## CI Gate کامل

```bash
clear
THIRTYNA_REAL_SSH=1 /usr/bin/python3 tests/run_ci.py
```

این دستور در محیط دارای پیش‌نیازهای Real SSH اجرا می‌شود. مجموعه خالی، Skip، Expected Failure، خطا یا تست ناموفق باعث Exit Code غیرصفر می‌شود. CI پس از تست پاک بودن Working Tree را نیز بررسی می‌کند. وضعیت اجرای واقعی را در GitHub Actions و PR بررسی کنید؛ Branch Protection مستقل از Workflow است.
