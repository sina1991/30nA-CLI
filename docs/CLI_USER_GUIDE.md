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

IP نمونه را برای اتصال با IP سرور خود جایگزین کنید. IPv4 و IPv6 پذیرفته می‌شوند. با حذف مقدار پس از -ip، ورودی از ترمینال، Pipe یا فایل خوانده می‌شود. برای اتصال به Host ثبت‌شده از 30na -host -ssh -ip ADDRESS استفاده کنید. برای ثبت و سپس اتصال، 30na -host -add -ip ADDRESS -ssh را اجرا کنید. خطای ثبت از اجرای SSH جلوگیری می‌کند. خطای اتصال بعد از ثبت، Host را در فهرست نگه می‌دارد. OpenSSH تنظیمات معمول کاربر را می‌خواند و در ورودی غیرتعاملی با BatchMode=yes اجرا می‌شود.

## Tunnel

```bash
clear
30na -tunnel -help
30na -tunnel -forward -ip 192.0.2.1 -listen 8080 -target 127.0.0.1 -target-port 80
30na -tunnel -reverse -ip 192.0.2.1 -listen 8080 -target 127.0.0.1 -target-port 80
30na -tunnel -list
30na -tunnel -stop -id TUNNEL_ID
```

آدرس `-ip` باید پیش‌تر در Host Agent ثبت شده باشد. در Forward پورت روی Loopback محلی و در Reverse درخواست Loopback به میزبان SSH ارسال می‌شود؛ سرور باید GatewayPorts=no را اعمال کند. احراز هویت SSH باید غیرتعاملی باشد. خروجی `state=starting` به‌معنی انتظار برای تأیید OpenSSH است. با `-list` وضعیت `ready` (تأیید Forwarding، نه دسترسی قطعی به Target) یا `failed` و `reason` را بررسی کنید. با `-stop` اتصال یا رکورد خطا را حذف کنید. جزئیات در [مستند معماری Tunnel](layer1-tunnel.md) آمده است.

برای بازیابی خودکار بعد از Crash شدن Tunnel Worker، گزینه `-restore` را هنگام ایجاد Tunnel اضافه کنید. بازیابی فقط برای Session آماده و در طول عمر همان Service Agent انجام می‌شود. توقف صریح، بازیابی را لغو می‌کند. قطع عادی SSH یا Restart کامل Service Agent باعث اتصال مجدد خودکار نمی‌شود.

وضعیت failed در خروجی -list یک رکورد خطا است و به معنی موفقیت اتصال نیست؛ Exit Code صفر -list فقط موفق بودن عملیات فهرست را نشان می‌دهد. برای تشخیص Reasonها و ارتقا، [راهنمای عیب‌یابی](TROUBLESHOOTING_GUIDE.md) را ببینید.
