# مدیریت Forward و Reverse با 30nA-CLI

1. [نصب و ثبت Host](#setup)
2. [ایجاد Tunnel](#create)
3. [مدیریت Tunnel](#manage)
4. [تست و عیب‌یابی](#test)

<a id="setup"></a>
## ۱. نصب و ثبت Host

روی کنترلر Ubuntu، [نصب Bootstrap](INSTALLATION_GUIDE.md) را انجام دهید. جفت‌کلید محلی را طبق [راهنمای Host](HOST_ONBOARDING.md) آماده کنید. دستور زیر را با دامنهٔ مقصد خود اجرا کنید و شمارهٔ ثبت‌شده را یادداشت کنید.

```bash
clear
30na -host -add -domain server.example.com -onboard -password
30na -host -list -ids
```

مقصد سرویس TCP را روی Loopback ارائه می‌دهد. مثال زیر فرض می‌کند مقصد با ID شمارهٔ `2` ثبت شده است. Forward پایدار به root روی کنترلر و ورود مستقیم SSH با کلید مدیریت به root مقصد روی پورت ۲۲ نیاز دارد. Reverse همچنین به root، Python 3 و systemd روی مقصد و امکان اتصال SSH از مقصد به کنترلر روی پورت ۲۲ نیاز دارد.

<a id="create"></a>
## ۲. ایجاد Tunnel

شمارهٔ Host و هر دو پورت را با مقادیر خودتان جایگزین کنید. از یک پورت ورودی آزاد استفاده کنید. `-localhost` ورودی را به همان ماشین محدود می‌کند. برای دسترسی سایر ماشین‌ها، به‌جای آن `-ip` و IPv4 اختصاص‌یافته به رابط Local را وارد کنید.

| حالت | آغازکنندهٔ SSH | محل Listener | مقصد |
| --- | --- | --- | --- |
| Forward | Local | Local Port | Loopback مقصد روی Remote Port |
| Reverse | Remote | Local Port | Loopback مقصد روی Remote Port |

Forward پایدار:

```bash
clear
30na -tunnel -forward -persistent -localhost -remote-id 2 -local-port 18080 -remote-port 9000
```

Reverse پایدار:

```bash
clear
30na -tunnel -reverse -localhost -remote-id 2 -local-port 18081 -remote-port 9000
```

در Reverse با Listener روی Loopback، اگر یک IPv4 عمومی در کنار آدرس‌های خصوصی Docker وجود داشته باشد، همان IPv4 عمومی برای اتصال SSH انتخاب می‌شود. Listener همچنان روی Loopback می‌ماند. اگر آدرس مناسب یکتا نباشد، برنامه خطای انتخاب آدرس می‌دهد. Forward با `-persistent` و Reverse شماره‌دار برای شروع خودکار در Boot واحد systemd دارند. Forward معمولی همچنان برای اتصال موقت در دسترس است.

<a id="manage"></a>
## ۳. مدیریت Tunnel

ابتدا ID و Unit را بخوانید:

```bash
clear
30na -tunnel -list
```

برای Tunnel پایدار، هر دستور زیر مستقل است. `TUNNEL_ID` را از خروجی کپی کنید. Stop راه‌اندازی خودکار را غیرفعال می‌کند. Start دوباره آن را فعال می‌کند و Delete منابع اختصاصی همان Tunnel را حذف می‌کند.

```bash
clear
30na -tunnel -stop -id TUNNEL_ID
30na -tunnel -start -id TUNNEL_ID
30na -tunnel -restart -id TUNNEL_ID
```

```bash
clear
30na -tunnel -delete -id TUNNEL_ID
```

<a id="test"></a>
## ۴. تست و عیب‌یابی

- وضعیت `ready` یعنی Listener متعلق به Tunnel روی پورت مورد انتظار مشاهده شده است. از کلاینت پروتکل واقعی سرویس برای ارسال درخواست به Listener و بررسی پاسخ مقصد استفاده کنید. برای سرویس HTTP، برای مثال از `curl --fail http://127.0.0.1:18080/` استفاده کنید.
- در آزمون Boot، همین درخواست را پس از راه‌اندازی مجدد ماشین آغازکنندهٔ SSH تکرار کنید. برای Forward این ماشین Local و برای Reverse این ماشین Remote است.
- اگر پورت ورودی اشغال است، مالک را با `30na -port -check PORT -tcp` بررسی کنید و پورت آزاد انتخاب کنید.
- اگر Tunnel آماده نمی‌شود، `journalctl -u UNIT -n 30 --no-pager` را روی آغازکنندهٔ SSH اجرا کنید. برای Reverse، مالکیت و پیکربندی مؤثر `sshd` روی Local را هم بررسی کنید. [عیب‌یابی](TROUBLESHOOTING_GUIDE.md) · [معماری Reverse](REMOTE_TUNNEL_ARCHITECTURE.md)
