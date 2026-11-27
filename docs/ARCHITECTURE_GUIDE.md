# معماری

فایل اجرایی 30na کنترل را به thirtyna.core.main می‌دهد. discover با pkgutil ماژول‌های عمومی thirtyna.agents را پیدا می‌کند و از SWITCH هر ماژول یک Registry می‌سازد. Dispatcher نخستین آرگومان را برای انتخاب Agent مصرف می‌کند و بقیه را به run می‌دهد. تنظیم argparse در Core مشترک است و تعریف سوییچ‌ها در خود Agent انجام می‌شود.

input_value در TTY یک خط و در حالت غیرتعاملی تا EOF می‌خواند. خروجی عادی Agent با print به stdout می‌رود. Core خطای UsageError و خطاهای عملیاتی را به stderr و Exit Code تبدیل می‌کند.

Host برای هر فراخوانی یک اتصال SQLite باز می‌کند. کلید اصلی جدول، متن استانداردشده IP یا Domain Name کامل است. اعتبارسنجی مشترک در thirtyna/address.py انجام می‌شود و جدول اصلی حفظ شده و جدول مکمل host_ids برای شماره‌های پایدار افزوده شده است. تراکنش پیش از فراخوانی OpenSSH پایان می‌یابد. مسیر پایگاه داده XDG_DATA_HOME/30na/hosts.db و مسیر پیش‌فرض ~/.local/share/30na/hosts.db است.

## Tunnel Agent

Tunnel Agent پردازش Worker مستقل در همان Service Agent دارد و سوکت کنترل خود را از Port Agent مشترک دریافت می‌کند. ثبت Host و شناسه Remote با درخواست‌های احرازشده lookup و exists بررسی می‌شوند و هیچ دسترسی مستقیمی به پایگاه داده Host ندارد. اجرای SSH به‌صورت subprocess بدون Shell است. Forward با OpenSSH `-L` و Reverse با `-R` اجرا می‌شود. توقف Worker موجب پاکسازی پردازش‌های SSH می‌شود. جزئیات در [layer1-tunnel.md](layer1-tunnel.md) است.

### Tunnel lifecycle and recovery

Tunnel Worker یک ControlMaster مستقل برای هر Session ایجاد می‌کند. فقط پاسخ موفق درخواست Forwarding معیار Ready است. Service Agent اطلاعات اتصال احرازشده Host Worker را از کانال خصوصی ارث‌رسیده در اختیار Tunnel قرار می‌دهد؛ Tunnel مستقیماً از IPC احرازشده Host مجوز می‌گیرد و درخواست بازگشتی به Supervisor ندارد. بازیابی اختیاری Sessionهای آماده با memfd موقت در حافظه و محدودیت نرخ انجام می‌شود. توقف صریح Worker یا Service Agent، قصد بازیابی را حذف می‌کند. جزئیات در [layer1-tunnel.md](layer1-tunnel.md).
