# Задача: GitHub init + deploy foundation на Yandex Cloud сервер

## Контекст

Проект HammerTrade сейчас существует локально, но в нём ещё не инициирован git.

Сервер уже создан в Yandex Cloud.

```text
Server IP: 103.76.52.4
Access: SSH by key
```

Цель этой задачи — подготовить проект к нормальной разработке и деплою:

1. инициировать git в локальном проекте;
2. создать безопасный `.gitignore`;
3. подготовить репозиторий к публикации в GitHub;
4. запушить код в новый GitHub-репозиторий `HammerTrade`;
5. подключиться к серверу;
6. установить системные зависимости;
7. склонировать проект на сервер;
8. создать Python virtualenv;
9. установить зависимости;
10. создать безопасный `.env` на сервере вручную;
11. проверить, что проект запускается и тесты проходят;
12. подготовить основу для будущего paper-trading daemon.

---

## Важные ограничения безопасности

Строго запрещено:

- коммитить `.env`;
- коммитить токены;
- печатать токены в консоль;
- добавлять `.env` в архивы;
- добавлять `.env` в manifest;
- отключать TLS verification;
- устанавливать или доверять Russian Trusted Root CA;
- использовать `curl -k`;
- делать live trading;
- делать sandbox orders;
- добавлять broker execution;
- запускать реальные заявки.

На сервере пока разрешён только research / paper-ready режим. Реальных заявок быть не должно.

---

## Что нужно узнать перед началом

Перед выполнением проверь у пользователя:

1. URL нового GitHub-репозитория `HammerTrade`.
2. Рабочую SSH-команду для подключения к серверу.

Например, пользователь может сказать:

```bash
ssh ubuntu@103.76.52.4
```

или:

```bash
ssh yc-user@103.76.52.4
```

или у него может быть alias в `~/.ssh/config`.

Не угадывай SSH username. Если рабочая SSH-команда неизвестна — остановись и попроси пользователя прислать команду, которой он реально подключается.

---

# Часть 1. Проверить локальный проект перед git init

В корне проекта выполнить:

```bash
pwd
ls -la
```

Проверить, что это действительно корень HammerTrade и там есть:

```text
src/
scripts/
configs/
requirements.txt
README.md
tests/
```

Если проект находится не в корне — остановиться и сообщить пользователю.

---

# Часть 2. Создать безопасный `.gitignore`

Создать или обновить `.gitignore`.

Минимальный набор:

```gitignore
# secrets
.env
.env.*
!.env.example

# python
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# virtualenv
.venv/
venv/
env/

# IDE / OS
.idea/
.vscode/
.DS_Store

# runtime outputs
data/raw/
data/paper/
out/
reports/
archives/
logs/

# local DB / state
*.sqlite
*.sqlite3
*.db

# large temp files
*.tmp
*.bak

# notebook checkpoints
.ipynb_checkpoints/
```

Важно: `data/instruments/futures_specs.csv` может содержать полезный кэш спецификаций, но для начала лучше не коммитить runtime data целиком. Если нужно сохранить структуру папок, использовать `.gitkeep`.

---

# Часть 3. Создать `.env.example`

Создать `.env.example` без реальных токенов:

```env
# T-Bank Invest API tokens
READONLY_TOKEN=
SANDBOX_TOKEN=

# Runtime mode
ENVIRONMENT=prod

# Logging
LOG_LEVEL=INFO
```

Реальные токены не добавлять.

---

# Часть 4. Сохранить структуру runtime-директорий

Так как `data/raw`, `out`, `reports`, `archives`, `logs` будут в `.gitignore`, создать `.gitkeep` там, где нужна структура:

```bash
mkdir -p data/instruments data/raw/tbank data/paper out reports archives/latest archives/old logs
touch data/instruments/.gitkeep
touch data/raw/.gitkeep
touch data/raw/tbank/.gitkeep
touch data/paper/.gitkeep
touch out/.gitkeep
touch reports/.gitkeep
touch archives/.gitkeep
touch archives/latest/.gitkeep
touch archives/old/.gitkeep
touch logs/.gitkeep
```

Если `.gitignore` полностью исключает директорию, `.gitkeep` не попадёт в git. Если нужно коммитить `.gitkeep`, настрой `.gitignore` точечно.

---

# Часть 5. Проверить, что секреты не попадут в git

До `git add` выполнить:

```bash
find . -maxdepth 3 -name ".env*" -print
```

Проверить:

```bash
git status --short
```

После `git add` обязательно проверить:

```bash
git status --short
```

Убедиться, что нет:

```text
.env
.env.local
data/raw/*.csv
out/*.csv
reports/*.md
archives/*.zip
logs/*
```

Если `.env` попал в staged — немедленно убрать:

```bash
git reset .env
```

---

# Часть 6. Инициировать git

Если `.git` ещё нет:

```bash
git init
```

Настроить main branch:

```bash
git branch -M main
```

Добавить файлы:

```bash
git add .
```

Проверить staged files:

```bash
git status --short
```

Если всё безопасно:

```bash
git commit -m "Initial HammerTrade research platform"
```

---

# Часть 7. Подключить GitHub remote

Пользователь должен заранее создать новый GitHub-репозиторий:

```text
HammerTrade
```

Желательно private.

Получить у пользователя SSH URL репозитория, например:

```text
git@github.com:<username>/HammerTrade.git
```

Не угадывать username.

Добавить remote:

```bash
git remote add origin <GITHUB_SSH_URL>
```

Если remote уже есть:

```bash
git remote -v
```

и при необходимости заменить:

```bash
git remote set-url origin <GITHUB_SSH_URL>
```

Запушить:

```bash
git push -u origin main
```

---

# Часть 8. Подготовить сервер

Подключиться к серверу рабочей SSH-командой пользователя.

Например:

```bash
ssh <WORKING_SSH_COMMAND>
```

Не угадывать username. Использовать только команду, которую подтвердил пользователь.

На сервере выполнить:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git tmux ufw sqlite3 ca-certificates curl
```

Создать директорию:

```bash
sudo mkdir -p /opt/hammertrade
sudo chown "$USER":"$USER" /opt/hammertrade
```

Перейти:

```bash
cd /opt/hammertrade
```

---

# Часть 9. Склонировать проект на сервер

На сервере:

```bash
git clone <GITHUB_SSH_URL> .
```

Если на сервере ещё не настроен SSH-доступ к GitHub, есть два варианта.

## Вариант A. Настроить deploy key

На сервере:

```bash
ssh-keygen -t ed25519 -C "hammertrade-yandex-server" -f ~/.ssh/hammertrade_github -N ""
cat ~/.ssh/hammertrade_github.pub
```

Пользователь должен добавить публичный ключ в GitHub repo:

```text
GitHub -> HammerTrade -> Settings -> Deploy keys -> Add deploy key
```

Достаточно read-only deploy key.

Создать `~/.ssh/config`:

```sshconfig
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/hammertrade_github
  IdentitiesOnly yes
```

Проверить:

```bash
ssh -T git@github.com
```

Потом:

```bash
git clone <GITHUB_SSH_URL> .
```

## Вариант B. Временно скопировать проект через rsync

Если GitHub deploy key пока не готов, можно временно скопировать проект:

```bash
rsync -av --exclude ".git" --exclude ".env" --exclude ".venv" --exclude "data/raw" --exclude "out" --exclude "reports" --exclude "archives" --exclude "logs" ./ <SSH_USER>@103.76.52.4:/opt/hammertrade/
```

Но основной путь — GitHub deploy key.

---

# Часть 10. Создать virtualenv на сервере

На сервере:

```bash
cd /opt/hammertrade
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Проверить:

```bash
python --version
pip --version
```

---

# Часть 11. Создать `.env` на сервере

На сервере:

```bash
cd /opt/hammertrade
cp .env.example .env
chmod 600 .env
nano .env
```

В `.env` вручную вставить только нужные токены:

```env
READONLY_TOKEN=<реальный readonly token>
SANDBOX_TOKEN=
ENVIRONMENT=prod
LOG_LEVEL=INFO
```

Не печатать содержимое `.env` в чат или лог.

---

# Часть 12. Проверить T-Bank TLS на сервере

На сервере выполнить:

```bash
curl -v https://invest-public-api.tbank.ru
```

И:

```bash
openssl s_client -connect invest-public-api.tbank.ru:443 -servername invest-public-api.tbank.ru -showcerts
```

Нужно проверить, что нет ошибки:

```text
self signed certificate in certificate chain
```

Если ошибка есть:

- не добавлять Russian Trusted Root CA;
- не отключать TLS verification;
- не использовать `curl -k`;
- сообщить пользователю, что сеть сервера непригодна для безопасного подключения к T-Bank API.

---

# Часть 13. Проверить проект на сервере

На сервере:

```bash
cd /opt/hammertrade
source .venv/bin/activate
pytest
```

Если тесты тяжёлые, можно хотя бы:

```bash
python scripts/run_research_wizard.py --dry-run
python scripts/compare_research_runs.py --help
python scripts/run_full_research_pipeline.sh --help
```

---

# Часть 14. Подготовить server bootstrap notes

Создать файл:

```text
docs/deploy_yandex_server.md
```

Содержимое:

```markdown
# Deploy HammerTrade to Yandex Cloud VM

## Server

IP: 103.76.52.4

## Directory

/opt/hammertrade

## Runtime

Python venv:

/opt/hammertrade/.venv

## Environment

.env is created manually on server and is never committed.

## Basic commands

```bash
cd /opt/hammertrade
source .venv/bin/activate
pytest
```

## Pull updates

```bash
cd /opt/hammertrade
git pull
source .venv/bin/activate
pip install -r requirements.txt
```

## TLS check

```bash
curl -v https://invest-public-api.tbank.ru
openssl s_client -connect invest-public-api.tbank.ru:443 -servername invest-public-api.tbank.ru -showcerts
```

## Security

Do not install Russian Trusted Root CA.
Do not disable TLS verification.
Do not store live trading token on server at this stage.
```
```

---

# Часть 15. README

Обновить README:

Добавить раздел:

```markdown
## Deployment
```

Кратко:

- project is deployed to `/opt/hammertrade`;
- use `.env.example`;
- never commit `.env`;
- server uses readonly token for paper/research;
- real orders are not implemented.

---

# Definition of Done

Задача выполнена, если:

1. В проекте есть `.gitignore`.
2. В проекте есть `.env.example`.
3. Git локально инициирован.
4. Первый commit создан.
5. Remote GitHub подключён.
6. Код запушен в GitHub `main`.
7. Сервер доступен по SSH.
8. На сервере установлены системные зависимости.
9. Проект склонирован в `/opt/hammertrade`.
10. На сервере создан `.venv`.
11. `pip install -r requirements.txt` выполнен успешно.
12. `.env` создан на сервере вручную и не попал в git.
13. T-Bank TLS проверен на сервере.
14. `pytest` или минимальные smoke-tests прошли на сервере.
15. Добавлен `docs/deploy_yandex_server.md`.
16. README обновлён.
17. Реальные заявки / sandbox orders / broker execution не добавлены.

---

# Отчёт после выполнения

После выполнения напиши:

```text
Что сделано локально:
...

Что запушено в GitHub:
...

GitHub remote:
...

Что сделано на сервере:
...

Где лежит проект на сервере:
...

Как обновлять проект на сервере:
...

Как запускать smoke-test:
...

Результат TLS-проверки T-Bank API на сервере:
...

Что НЕ делалось:
...
```

В блоке "Что НЕ делалось" обязательно указать:

```text
- live trading не добавлялся;
- sandbox orders не добавлялись;
- broker execution не добавлялся;
- реальные торговые токены не добавлялись;
- .env не коммитился;
- TLS verification не отключалась;
- Russian Trusted Root CA не устанавливался.
```
