# 30nA-CLI

ابزار شخصی Linux با چهار Agent مستقل برای محاسبات، خواندن اطلاعات سیستم و مدیریت فهرست IPها و اتصال با OpenSSH.

## نصب از GitHub

```bash
clear
git clone --branch feat/menu-interfaces https://github.com/sina1991/30nA-CLI.git
cd 30nA-CLI
sudo ./install.sh
```

```bash
clear
30na -help
30na -calc -add 10 20
30na -sys -hostname -kernel
30na -host -list
```

[نصب](docs/INSTALLATION_GUIDE.md) · [دستورات](docs/CLI_USER_GUIDE.md) · [معماری](docs/ARCHITECTURE_GUIDE.md) · [توسعه Agent](docs/AGENT_DEVELOPMENT_GUIDE.md) · [تست](docs/TESTING_GUIDE.md) · [وضعیت](docs/DEVELOPMENT_STATUS.md)

## Menu Agent

| دستور | رابط |
|---|---|
| `30na -menu` | فهرست منوها با انتخاب شماره |
| `30na -menu -dir /var` | پیمایش مستقیم با شماره |
| `30na -menu -dir /var -tui` | فلش و Enter در ترمینال |
| `30na -menu -dir /var -gui` | پنجره مستقل Tk با ماوس |

بدون مسیر، پیمایش از دایرکتوری جاری آغاز می‌شود. گزینهٔ `..` والد را باز می‌کند. Back هنگام ورود از فهرست اصلی به همان فهرست برمی‌گردد و هنگام اجرای مستقیم از برنامه خارج می‌شود. پیمایش فقط پوشه‌ها را نمایش می‌دهد و مسیر Shell را تغییر نمی‌دهد.

حالت شماره‌ای به Python استاندارد نیاز دارد. برای حالت TUI یک ترمینال تعاملی با curses و برای GUI یک نشست گرافیکی با Tk لازم است. روی Ubuntu، `install.sh` پیش‌نیازهای هر سه رابط، از جمله `python3-tk` و `xauth` را بررسی و در صورت نیاز نصب می‌کند. در نشست SSH تعاملی بدون DISPLAY، دستور -gui خودکار رابط تمام‌صفحهٔ کیبوردی را باز می‌کند. برای رابط جهت‌دار از -tui استفاده کنید.

ماژول‌های مستقل `numbered`، `terminal` و `window` فقط رابط را نمایش می‌دهند. برای افزودن یک منوی جدید یک مدل با title، items و open(target) بسازید و در MENUS در thirtyna/menus/model.py ثبت کنید.

### پیمایش با کیبورد در Termius

با `30na -menu -dir /var -tui` رابط تمام‌صفحه باز می‌شود. ↑ و ↓ برای انتخاب، Enter یا → برای ورود، ← برای والد و Home، End و Page Up/Down برای حرکت سریع هستند. با / بخشی از نام پوشه را وارد کنید، با Enter فیلتر را اعمال کنید و سپس پوشه را باز کنید. Esc ابتدا فیلتر را پاک می‌کند و سپس به منوی قبلی برمی‌گردد. q خروج است.
