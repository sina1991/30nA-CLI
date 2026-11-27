# 30na -host

داده‌ها در `$XDG_DATA_HOME/30na/hosts.db` یا `~/.local/share/30na/hosts.db` نگه‌داری می‌شوند. `-add -ip ADDRESS -ssh` ابتدا آدرس را ثبت می‌کند و سپس به آن وصل می‌شود. IP مستندات نمونه است.

- [-add](add/README.md) — ثبت IPv4، IPv6 یا Domain Name در SQLite؛ ثبت تکراری خطاست
- [-remove](remove/README.md) — حذف یک آدرس ثبت‌شده
- [-list](list/README.md) — نمایش فهرست مرتب‌شدهٔ آدرس‌ها و دامنه‌ها
- [-ssh](ssh/README.md) — اتصال با OpenSSH به آدرس ثبت‌شده
- [-domain](domain/README.md) — نام دیگر -ip برای تعیین دامنه
- [-ip](ip/README.md) — تعیین آدرس برای ثبت، حذف یا اتصال
- [-help](help/README.md) — راهنمای سوییچ‌ها و مثال‌های Agent
