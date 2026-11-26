# 30nA-CLI

ابزار شخصی Linux با سه Agent مستقل برای محاسبات، خواندن اطلاعات سیستم و مدیریت فهرست IPها و اتصال با OpenSSH.

## نصب از GitHub

```bash
clear
git clone --branch feat/initial-cli https://github.com/sina1991/30nA-CLI.git
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
