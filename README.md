# 30nA-CLI

ابزار ترمینال Linux برای مدیریت Host، ساخت OpenSSH Forward و Reverse، تست پروفایل‌های Proxy و مدیریت فایل‌ها و سرویس‌ها.

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

## راهنماهای تکمیلی

| موضوع | راهنما |
|---|---|
| منوی ترمینال و مدیریت فایل | [TUI و میانبرها](docs/TUI_GUIDE.md) |
| SSH و نام دامنه | [Domain SSH](docs/DOMAIN_SSH_GUIDE.md) |
| مدیریت سرویس‌ها و مشاهدهٔ پورت‌ها | [Systemd](docs/SYSTEMD_SERVICE_GUIDE.md) · [پورت‌ها](docs/PORT_AGENT_GUIDE.md) |
| بازیابی سرور پس از Rebuild | [سرور ایران](docs/iran%20server%20after%20rebuild.md) · [سرور مقصد](docs/remote%20server%20After%20rebuild.md) |
| شواهد تست و انتشار | [پذیرش Release](docs/RELEASE_ACCEPTANCE.md) · [یادداشت انتشار](docs/RELEASE_NOTES.md) |
| توسعه و ساخت Agent | [AGENTS.md](AGENTS.md) |

## Proxy Profile Test Agent

[تست پروفایل‌ها، تاریخچه و سه فهرست کیفیت](docs/TEST_AGENT_GUIDE.md)

```bash
clear
30na -test -all
```

[ساخت و دریافت کانفیگ Xray و بررسی IP خروجی](docs/XCONF_GUIDE.md)
