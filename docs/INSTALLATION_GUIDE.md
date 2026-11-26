# نصب در Linux

Python 3.10 یا جدیدتر با sqlite3، Bash، GNU coreutils و OpenSSH Client لازم است. برای نصب سراسری دستورهای README را اجرا کنید. برای نصب شخصی پس از clone از ریشه مخزن اجرا کنید.

```bash
clear
PREFIX="$HOME/.local" ./install.sh
export PATH="$HOME/.local/bin:$PATH"
30na -help
```

برای دسترسی در نشست‌های بعد، خط export را در تنظیمات shell خود نگه دارید. برای به‌روزرسانی روی همان branch، ابتدا git pull --ff-only و سپس همان فرمان نصب را اجرا کنید. نصب، نسخه جدید را در PREFIX/lib/30na قرار می‌دهد و لینک PREFIX/bin/30na را تعویض می‌کند. نسخه‌های قبلی روی دیسک می‌مانند. داده هر کاربر در مسیر جداگانه ذخیره می‌شود.
