# راهنمای دستورها

برای راهنمای عمومی 30na -help و برای راهنمای هر Agent سوییچ -help را پس از نام آن وارد کنید. نتیجه در stdout، خطا و درخواست ورودی در stderr نوشته می‌شود. Exit Code صفر موفقیت، ۲ خطای ورودی یا وضعیت Host و ۱ خطای عملیاتی است.

## Calculator

هر عملیات دو عدد صحیح یا اعشاری علامت‌دار می‌گیرد. عملیات ترکیبی به ترتیب add، sub، mul، div چاپ می‌شوند. برای ترکیب چند عملیات، هر جفت عدد را کنار سوییچ خودش بنویسید. محاسبات با Decimal و دقت پیش‌فرض ۲۸ رقم معنادار انجام می‌شوند.

```bash
clear
30na -calc -add 10 20
30na -calc -sub 20 10
30na -calc -mul 10 20
30na -calc -div 20 10
echo '1.2 3' | 30na -calc -add
30na -calc -add < numbers.txt
```

در ترمینال با اجرای 30na -calc -add هر دو عدد را در یک خط با فاصله وارد کنید.

## System

هر فیلد را مستقل یا همراه فیلدهای دیگر انتخاب کنید. خروجی به ترتیب زیر است.

```bash
clear
30na -sys -hostname -os -kernel -uptime -cpu -ram -disk
```

فیلدها به‌ترتیب نام میزبان، نام توزیع، نسخه Kernel، زمان روشن بودن به ثانیه، مدل یا معماری CPU، کل RAM و فضای کل، مصرفی و آزاد فایل‌سیستم ریشه را نشان می‌دهند.

## Host

```bash
clear
30na -host -add -ip 192.0.2.1
30na -host -list
30na -host -remove -ip 192.0.2.1
```

IP نمونه را برای اتصال با IP سرور خود جایگزین کنید. IPv4، IPv6 و Domain Name کامل (ASCII یا Punycode) پذیرفته می‌شوند. گزینه -domain نام دیگر -ip است. نام دامنه به حروف کوچک تبدیل می‌شود و نقطه انتهایی حذف می‌شود. ثبت دامنه نیاز به DNS آنلاین ندارد. اتصال و تشخیص مقصد بر عهده OpenSSH است. با حذف مقدار پس از -ip، ورودی از ترمینال، Pipe یا فایل خوانده می‌شود. برای اتصال به Host ثبت‌شده از 30na -host -ssh -ip ADDRESS استفاده کنید. برای ثبت و سپس اتصال، 30na -host -add -ip ADDRESS -ssh را اجرا کنید. خطای ثبت از اجرای SSH جلوگیری می‌کند. خطای اتصال بعد از ثبت، Host را در فهرست نگه می‌دارد. OpenSSH تنظیمات معمول کاربر را می‌خواند و در ورودی غیرتعاملی با BatchMode=yes اجرا می‌شود.

## Tunnel — Local / Remote

شناسه ۱ همیشه سرور اجراکننده برنامه است و نیازی به ثبت ندارد. Remote ID از ۲ شروع می‌شود و با حذف Hostهای دیگر تغییر نمی‌کند. هنگام ارتقا، شناسه Hostهای موجود یک بار به ترتیب آدرس تخصیص می‌یابد؛ سپس پایدار است. ابتدا شماره واقعی Remote را در فهرست ببینید؛ شماره ۳ و آدرس‌های زیر نمونه‌اند.

```bash
clear
30na -host -list -ids
30na -tunnel -forward -local-port 8080 -remote-id 3 -remote-port 443
30na -tunnel -reverse -local-port 8080 -remote-id 3 -remote-port 443
30na -tunnel -forward -localhost -id 1 -local-port 8080 -remote-ip 192.0.2.10 -remote-port 443
30na -tunnel -reverse -local-port 8080 -remote-domain ssh.example.test -remote-port 443
30na -tunnel -list
30na -tunnel -stop -id TUNNEL_ID
```

در هر دو حالت Local Port پورت ورودی و Remote Port پورت سرویس مقصد است. در Forward اتصال SSH از Local آغاز می‌شود؛ در Reverse از Remote. پیش‌فرض Bind برابر Loopback است؛ با -ip آدرس IPv4 متعلق به Local را صریحاً انتخاب کنید تا روی همان رابط شنونده ایجاد شود. Reverse جدید به Host Onboarding موفق، دسترسی root و SSH روی پورت 22 سرور Local نیاز دارد. [جزئیات](REMOTE_TUNNEL_ARCHITECTURE.md).

با -remote-ip یا -remote-domain آدرس Remote مشخص می‌شود و Host Agent آن را در صورت نیاز ثبت می‌کند. با -remote-id فقط Host ثبت‌شده انتخاب می‌شود. هر دو روش به تنظیم صحیح User، SSH Port، کلید و Host Key معتبر نیاز دارند. رمز عبور یا کلید در برنامه ذخیره نمی‌شود. سوییچ قدیمی -listen در قرارداد جدید نام دیگر Local Port است، نه Listener در هر دو جهت. سوییچ‌های Target قدیمی فقط برای سازگاری اسکریپت‌ها حفظ شده‌اند و در منو و Help جدید نمایش داده نمی‌شوند. گزینه -restore فقط برای Forward و Reverse قدیمی باقی است؛ Reverse جدید با Systemd پایدار می‌ماند.

وضعیت ready تأیید Forwarding توسط OpenSSH است، نه تضمین دسترسی به سرویس مقصد. برای Stop، از Tunnel ID خروجی استفاده کنید، نه Host ID. جزئیات: [معماری Tunnel](layer1-tunnel.md).

## مرکز کنترل TUI

```bash
clear
30na -menu -tui
```

برای دسترسی به Calculator، System، Host، Tunnel، Files و Help از [راهنمای مرکز کنترل](TUI_GUIDE.md) استفاده کنید.

## Systemd Service Agent

```bash
clear
30na -service -help
30na -service -active
30na -service -list
30na -service -installed
30na -service -workers
30na -service -status -unit ssh.service
30na -service -logs -unit ssh.service
```

عملیات تغییر وضعیت را تنها با مجوز مناسب و پس از بررسی تأثیر آن روی اتصال SSH انجام دهید. [راهنمای Service Agent](SYSTEMD_SERVICE_GUIDE.md).

### IP سرور محلی

```bash
clear
30na -sys -ip
```

بدون ثبت Host، آدرس‌های Interface محلی را نمایش می‌دهد. برای تشخیص IP عمومی پشت NAT از این خروجی نتیجه‌گیری نکنید.

## Port Agent

```bash
clear
30na -port -list
30na -port -all
30na -port -summary
30na -port -check 5555
```

[راهنمای Port Agent](PORT_AGENT_GUIDE.md).

آزادسازی اضطراری Port فقط با پروتکل و مالک صریح انجام می‌شود؛ ابتدا -check را اجرا کنید. [راهنمای -force](PORT_AGENT_GUIDE.md).

## افزودن و آماده‌سازی Remote

```bash
clear
30na -host -add -domain ssh.example.test -onboard
30na -host -add -domain ssh.example.test -onboard -password
```

[راهنمای Host Onboarding](HOST_ONBOARDING.md).

## کشف Tunnelهای خارجی

```bash
clear
30na -tunnel -discover
30na -tunnel -discover -remote-id 2
```

بررسی خواندنی سرویس‌های شناخته‌شده Local/Remote؛ [جزئیات و محدودیت‌ها](REMOTE_TUNNEL_ARCHITECTURE.md).
