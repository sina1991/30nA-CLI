# اجرای تست‌ها

از ریشه مخزن اجرا کنید.

```bash
clear
python3 -m unittest discover -s tests -v
```

تست‌ها CLI را با subprocess اجرا می‌کنند. تست تعاملی از PTY، تست توسعه‌پذیری از یک package موقت و تست نصب از PREFIX و XDG_DATA_HOME ایزوله استفاده می‌کند. اجرای Pipe و redirection در Bash واقعی انجام می‌شود. تست Host یک ssh آزمایشی در PATH می‌گذارد که آرگومان‌ها را ثبت می‌کند و موفقیت یا خطا برمی‌گرداند.
