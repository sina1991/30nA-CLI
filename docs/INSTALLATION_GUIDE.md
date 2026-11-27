# نصب در Linux

Python 3.10 یا جدیدتر با sqlite3، Bash، GNU coreutils و OpenSSH Client لازم است. بازیابی Tunnel به Linux با memfd_create نیاز دارد. برای نصب سراسری دستورهای README را اجرا کنید. برای نصب شخصی پس از clone از ریشه مخزن اجرا کنید.

```bash
clear
PREFIX="$HOME/.local" ./install.sh
export PATH="$HOME/.local/bin:$PATH"
30na -help
```

برای دسترسی در نشست‌های بعد، خط export را در تنظیمات shell خود نگه دارید. برای به‌روزرسانی روی همان branch، ابتدا git pull --ff-only و سپس همان فرمان نصب را اجرا کنید. نصب، نسخه جدید را در PREFIX/lib/30na قرار می‌دهد و لینک PREFIX/bin/30na را تعویض می‌کند. نسخه‌های قبلی روی دیسک می‌مانند. داده هر کاربر در مسیر جداگانه ذخیره می‌شود.

## Bootstrap کامل روی Ubuntu 22.04 و جدیدتر

```bash
clear
installer=$(mktemp)
curl -fsSL https://raw.githubusercontent.com/sina1991/30nA-CLI/main/install.sh -o "$installer" &&
bash "$installer" --bootstrap
rm -f -- "$installer"
```

با root اجرا شود. دریافت اولیه به curl یا wget و اینترنت نیاز دارد. Bootstrap در /root/30nA-CLI از origin رسمی main دریافت می‌کند یا checkout موجود را فقط با fast-forward به‌روز می‌کند؛ تغییر محلی، branch دیگر یا origin متفاوت باعث توقف می‌شود. سپس نصاب checkout را اجرا می‌کند. نصب از checkout به‌خودی‌خود Git pull انجام نمی‌دهد.

در نصب عادی Ubuntu، apt-get update و نصب بسته‌های مفقود (Git، CA، Python، Tk، OpenSSH Client، iproute2، nano، ncurses، xauth و برای root، OpenSSH Server) انجام می‌شود. Upgrade سراسری OS انجام نمی‌شود. سرویس SSH با sshd -t بررسی می‌شود؛ socket activation موجود حفظ می‌شود، سرویس فعال Restart نمی‌شود. در صورت وجود هر دو فایل /root/30na_windows و /root/30na_windows.pub مالکیت/نوع فایل و مجوز بررسی/اصلاح و جفت‌کلید توسط Host Agent اعتبارسنجی و محلی کپی می‌شود. فایل مفقود/ناقص، کلید نامعتبر یا تغییر سیاست SSH گزارش می‌شود. نبود هر دو فایل مانع نصب نیست؛ بدون آن‌ها Onboarding جدید ممکن نیست. هیچ کلیدی دریافت یا تولید خودکار نمی‌شود.

INSTALL_DEPS=0 حالت نصب فقط فایل برنامه است: بدون apt، فعال‌سازی SSH یا آماده‌سازی کلید. Onboarding Remote از همین حالت استفاده می‌کند تا سرویس فعال تغییر نکند؛ پیش‌نیازهای آن Remote باید قبلاً فراهم باشند. نصب بسته‌های مفقود ممکن است طبق سیاست بسته‌ها سرویس ایجاد/فعال کند؛ هیچ تضمین عدم تغییر سیستم برای نصب بسته وجود ندارد.

## پیش‌نیازهای سه رابط روی Ubuntu 22.04 و جدیدتر

اسکریپت با Python سیستم در /usr/bin/python3 کار می‌کند و launcher نصب‌شده نیز همان مفسر را به کار می‌برد. برای نصب بسته‌های سیستمی از root یا sudo استفاده می‌کند. نصب شخصی با PREFIX فقط مقصد فایل‌های برنامه را تغییر می‌دهد. اجرای INSTALL_DEPS=0 ./install.sh فقط پیش‌نیازهای CLI را بررسی و فایل برنامه را نصب می‌کند؛ بدون تغییر SSH یا کلیدها.

| بخش | نیاز |
|---|---|
| نصب | Bash و GNU coreutils، برای دریافت سورس Git |
| CLI و Host | Python 3.10+، sqlite3 از کتابخانه استاندارد، openssh-client |
| TUI | curses از Python سیستم، اطلاعات ترمینال ncurses-base، نشست تعاملی با TERM معتبر |
| GUI | python3-tk شامل Tk/ttk و دسترسی به نمایشگر |
| نمایش پنجره از طریق SSH | xauth روی سرور، X server روی کلاینت و X11 forwarding فعال در اتصال و مجاز در sshd |

## ارتقای نسخه و Service Agent

پیش از ارتقا، Sessionهای فعال را بررسی و برای توقف آن‌ها برنامه‌ریزی کنید. Supervisor قبلی ممکن است همچنان کد Release قدیمی را اجرا کند. با همان کاربر و XDG_DATA_HOME که برنامه را اجرا می‌کند، سرویس را متوقف کنید؛ این کار همه Tunnelها را می‌بندد و قصد بازیابی را حذف می‌کند. سپس روی main به‌روزرسانی و نصب کنید.

```bash
clear
git switch main
git pull --ff-only
python3 -m thirtyna.runtime.service shutdown
sudo ./install.sh
```

برای نصب شخصی، خط آخر را با PREFIX="$HOME/.local" ./install.sh جایگزین کنید. پایگاه داده Host حفظ می‌شود. برای عیب‌یابی نسخه یا Tunnel به [راهنمای عیب‌یابی](TROUBLESHOOTING_GUIDE.md) مراجعه کنید.

برای تست نمایش واقعی پنجره، از داخل یک نشست Desktop یا SSH با X11 forwarding اجرا کنید.

```bash
clear
30na -menu -dir /var -gui
```

در اتصال عادی SSH می‌توانید از -tui استفاده کنید. اگر روی Windows از X11 forwarding استفاده می‌کنید، ابتدا X server کلاینت را اجرا کنید و نشست SSH را با پشتیبانی X11 باز کنید. مقدار DISPLAY را SSH تنظیم می‌کند. نصب‌کننده تنظیمات sshd را ویرایش نمی‌کند.

برای Port Agent ابزار ss از بسته iproute2 لازم است؛ نصب‌کننده Ubuntu آن را در پیش‌نیازها بررسی می‌کند.

برای نصب Remote با SSH، [Host Onboarding](HOST_ONBOARDING.md) را ببینید. نصب از checkout تمیز Git نشانگر .revision را در Release ذخیره می‌کند.
