# توسعه Agent

در thirtyna/agents یک فایل Python با نام عمومی بسازید. نام‌های آغازشده با زیرخط برای کد خصوصی هستند. قرارداد اجرایی به شکل زیر است.

```python
from thirtyna.core import parser

SWITCH = "-example"
NAME = "Example Agent"

def run(argv):
    cli = parser(SWITCH, NAME + " prints a message.",
                 "Example: 30na -example hello. Input: one argument.")
    cli.add_argument("message")
    args = cli.parse_args(argv)
    print(args.message)
```

سوییچ یکتا انتخاب کنید. برای خطای کاربر UsageError و برای خطای عملیاتی RuntimeError ایجاد کنید. None یا صفر نشان‌دهنده موفقیت است. برای ورودی جایگزین از input_value استفاده کنید. در تست، Registry، Help، خروجی و Exit Code را از ورودی CLI بررسی کنید. test_extension نمونه ماژول موقت را هنگام اجرا می‌سازد. پس از اضافه کردن Agent، نصب را دوباره اجرا کنید.
