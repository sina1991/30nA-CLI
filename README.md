# 30nA-CLI

Tunnel Agent: `30na -tunnel -help` (OpenSSH Forward/Reverse, confirmed readiness, failure reporting, opt-in worker crash recovery). See [Tunnel documentation](docs/layer1-tunnel.md).

ابزار شخصی Linux با Agentهای مستقل برای محاسبات، خواندن اطلاعات سیستم و مدیریت فهرست IPها و نام دامنه‌ها و اتصال با OpenSSH.

## نصب از GitHub

برای نصب یا به‌روزرسانی کامل روی Ubuntu با کاربر root، تنها اسکریپت نصاب را دریافت و اجرا کنید (curl یا wget برای دریافت اولیه لازم است).

```bash
clear
(
  installer=$(mktemp) || exit 1
  trap 'rm -f -- "$installer"' EXIT
  curl -fsSL https://raw.githubusercontent.com/sina1991/30nA-CLI/main/install.sh -o "$installer" &&
  bash "$installer" --bootstrap
)
```

نصاب Git، پیش‌نیازها، checkout تمیز main، SSH و آماده‌سازی کلیدهای موجود را مدیریت می‌کند. بدون کلید هم نصب برنامه ممکن است؛ برای Onboarding جفت‌کلید را امن منتقل کنید. هیچ Upgrade سراسری OS یا Restart عمدی سرویس فعال انجام نمی‌شود. برای نصب از checkout موجود همچنان ./install.sh قابل استفاده است.

```bash
clear
30na -help
30na -calc -add 10 20
30na -sys -hostname -kernel
30na -host -list -ids
```

[نصب](docs/INSTALLATION_GUIDE.md) · [دستورات](docs/CLI_USER_GUIDE.md) · [معماری](docs/ARCHITECTURE_GUIDE.md) · [توسعه Agent](docs/AGENT_DEVELOPMENT_GUIDE.md) · [تست](docs/TESTING_GUIDE.md) · [وضعیت](docs/DEVELOPMENT_STATUS.md)

## فهرست راهنماها

| کار | راهنما |
| --- | --- |
| نصب روی Ubuntu تازه و به‌روزرسانی | [نصب](docs/INSTALLATION_GUIDE.md) |
| ثبت Host، کلید عمومی و ورود مجدد | [Host و SSH](docs/HOST_ONBOARDING.md) |
| ایجاد و مدیریت Forward و Reverse پایدار | [راهنمای عملی Tunnel](docs/TUNNEL_QUICKSTART.md) |
| توپولوژی، پورت‌ها و کشف Tunnel موجود | [معماری Tunnel](docs/REMOTE_TUNNEL_ARCHITECTURE.md) |
| عیب‌یابی و پذیرش | [عیب‌یابی](docs/TROUBLESHOOTING_GUIDE.md) · [تست](docs/TESTING_GUIDE.md) |

## Menu Agent

منوی مرکزی تمام ایجنت‌ها با TUI و Status Bar:

```bash
clear
30na -menu -tui
```

[راهنمای مرکز کنترل و میانبرها](docs/TUI_GUIDE.md)

| دستور | رابط |
|---|---|
| `30na -menu -tui` | مرکز کنترل همه ایجنت‌ها |
| `30na -menu` | فهرست منوها با انتخاب شماره |
| `30na -menu -dir /var` | پیمایش مستقیم با شماره |
| `30na -menu -dir /var -tui` | فلش و Enter در ترمینال |
| `30na -menu -dir /var -gui` | پنجره مستقل Tk با ماوس |

بدون مسیر، پیمایش از دایرکتوری جاری آغاز می‌شود. گزینهٔ `..` والد را باز می‌کند. Back هنگام ورود از فهرست اصلی به همان فهرست برمی‌گردد و هنگام اجرای مستقیم از برنامه خارج می‌شود. پیمایش فقط پوشه‌ها را نمایش می‌دهد و مسیر Shell را تغییر نمی‌دهد.

حالت شماره‌ای به Python استاندارد نیاز دارد. برای حالت TUI یک ترمینال تعاملی با curses و برای GUI یک نشست گرافیکی با Tk لازم است. روی Ubuntu، `install.sh` پیش‌نیازهای هر سه رابط، از جمله `python3-tk` و `xauth` را بررسی و در صورت نیاز نصب می‌کند. در نشست SSH تعاملی بدون DISPLAY، دستور -gui خودکار رابط تمام‌صفحهٔ کیبوردی را باز می‌کند. برای رابط جهت‌دار از -tui استفاده کنید.

ماژول‌های مستقل `numbered`، `terminal` و `window` فقط رابط را نمایش می‌دهند. برای افزودن یک منوی جدید یک مدل با title، items و open(target) بسازید و در MENUS در thirtyna/menus/model.py ثبت کنید.

### مدیریت فایل در Termius

با `30na -menu -dir /var -tui` مدیر فایل باز می‌شود. در عرض ۸۰ ستون یا بیشتر هر دو پنل هم‌زمان دیده می‌شوند. در عرض کمتر، Tab بین دو پنل جابه‌جا می‌شود. پنل فعال مبدأ و پنل دیگر مقصد کپی و انتقال است. هر دو ابتدا در مسیر شروع باز می‌شوند.

| کلید | عملکرد |
|---|---|
| Tab، g | تعویض پنل، رفتن به مسیر دلخواه |
| ↑ ↓، Page Up/Down، Home/End | انتخاب فایل یا پوشه |
| Enter یا →، ← | ورود به پوشه، رفتن به والد |
| c، m | کپی یا انتقال به پنل دیگر؛ Enter نام فعلی را نگه می‌دارد |
| r، n، d | تغییر نام، ساخت فایل خالی، ساخت پوشه |
| x | حذف فایل، لینک یا پوشهٔ خالی پس از تایپ DELETE |
| /، Ctrl+L | فیلتر نام، بازخوانی مسیر |
| ?، Esc، q | راهنمای کلیدها، لغو یا بازگشت، خروج |

مقصد موجود بازنویسی نمی‌شود. کپی پوشه بازگشتی است و لینک‌ها به شکل لینک کپی می‌شوند. برای کپی کنار فایل اصلی، در پنل مقصد همان مسیر را نگه دارید و نام تازه بدهید. مجوز، اندازه و تاریخ آخرین تغییر مورد انتخاب‌شده در پایین صفحه نمایش داده می‌شود.

## راهنمای سوییچ‌ها

- [-help](docs/switches/help/README.md)
- [-calc](docs/switches/calc/README.md)
- [-sys](docs/switches/sys/README.md)
- [-host](docs/switches/host/README.md)
- [-menu](docs/switches/menu/README.md)
- [-tunnel](docs/switches/tunnel/README.md)

## شروع توسعه

برای ورود سریع ایجنت‌های جدید، ابتدا [AGENTS.md](AGENTS.md) و [وضعیت توسعه](docs/DEVELOPMENT_STATUS.md) را بخوانید. سپس فقط فایل‌های مرتبط با مأموریت را بررسی کنید.

## شواهد و عیب‌یابی

[پذیرش و شواهد CI](docs/RELEASE_ACCEPTANCE.md) · [عیب‌یابی](docs/TROUBLESHOOTING_GUIDE.md) · [GitHub Actions](https://github.com/sina1991/30nA-CLI/actions)

پیش از ارتقای نسخه، Service Agent فعال را مطابق راهنمای نصب متوقف کنید. این کار Sessionهای فعال را قطع می‌کند. بازیابی اختیاری فقط برای Crash شدن Tunnel Worker در طول عمر همان سرویس است.

[راهنمای Domain Name و SSH Service](docs/DOMAIN_SSH_GUIDE.md)

[راهنمای Systemd Service Agent](docs/SYSTEMD_SERVICE_GUIDE.md) · [Dashboard چندپنلی](docs/TUI_GUIDE.md)

[راهنمای Port Agent](docs/PORT_AGENT_GUIDE.md)

[قرارداد جدید Local/Remote و شناسه Host](docs/layer1-tunnel.md)
