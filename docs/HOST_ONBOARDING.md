# ثبت Host و ورود با SSH Key

1. [پیش‌نیاز](#prerequisites)
2. [ثبت Host](#enroll)
3. [ورود مجدد](#login)
4. [رفع خطا](#diagnostics)

<a id="prerequisites"></a>
## ۱. پیش‌نیاز

روی کنترلر، جفت‌کلید معتبر `30na_windows` و `30na_windows.pub` را در Home کاربر اجراکننده قرار دهید. برای root این مسیر `/root` است. برنامه جفت‌کلید را بررسی و نسخه‌ای با مجوز محدود در `~/.ssh/30na-management/` نگهداری می‌کند. مقصد باید SSH فعال و Machine ID معتبر داشته باشد. برای ساخت Reverse، پیش‌نیازهای [معماری Tunnel](REMOTE_TUNNEL_ARCHITECTURE.md) نیز لازم‌اند.

<a id="enroll"></a>
## ۲. ثبت Host

اگر کلید عمومی از قبل مجاز و Host Key در `known_hosts` معتبر است:

```bash
clear
30na -host -add -domain uk5.30na.top -onboard
```

برای اولین ثبت تعاملی در صورت نیاز به تأیید Host Key یا Password:

```bash
clear
30na -host -add -domain uk5.30na.top -onboard -password
```

Fingerprint را پیش از پذیرش از یک مسیر معتبر بررسی کنید. OpenSSH رمز را در ترمینال می‌گیرد. در صورت نیاز، `ssh-copy-id` فقط کلید عمومی را در حساب مقصد ثبت می‌کند. Host Agent بعد از تأیید ورود با همان کلید در حالت غیرتعاملی، ID را ذخیره می‌کند. ثبت مجدد همان آدرس ID را حفظ می‌کند. عملیات ثبت فقط به SSH و خواندن Machine ID روی مقصد نیاز دارد و نسخهٔ برنامهٔ مقصد را تغییر نمی‌دهد.

<a id="login"></a>
## ۳. ورود مجدد

```bash
clear
30na -host -list -ids
30na -host -ssh -domain uk5.30na.top
```

برای ایجاد Tunnel، ID نمایش‌داده‌شده را در `-remote-id` بدهید. [راهنمای Tunnel](layer1-tunnel.md).

<a id="diagnostics"></a>
## ۴. رفع خطا

| خطا | بررسی |
| --- | --- |
| Host Key ناشناخته | Fingerprint مقصد را از کنسول معتبر بررسی کنید و ثبت تعاملی را اجرا کنید. |
| Host Key تغییر کرده | ابتدا تغییر کلید یا بازسازی ماشین را از کنسول مقصد تأیید کنید. |
| شکست ورود غیرتعاملی | حساب SSH، مجوزهای `authorized_keys` و سیاست احراز هویت مقصد را بررسی کنید. |
| مقصد همان ماشین Local است | آدرس مقصد را بررسی کنید. ID شمارهٔ ۱ برای Local رزرو شده است. |
| کلید عمومی کپی شد ولی ثبت شکست خورد | ممکن است کلید عمومی در مقصد ثبت شده باشد. پس از رفع علت، همان دستور ثبت را تکرار کنید. |

`-add` بدون `-onboard` آدرس را آفلاین ذخیره می‌کند.
