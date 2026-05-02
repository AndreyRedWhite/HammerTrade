# Задача: Isolated CA bundle для T-Bank API на сервере + connectivity check

## Контекст

Проект HammerTrade уже развёрнут:

```text
Server IP: 103.76.52.4
Project path: /opt/hammertrade
Runtime: /opt/hammertrade/.venv
```

На сервере Yandex Cloud TLS-проверка T-Bank API падает:

```text
SSL certificate problem: self-signed certificate in certificate chain
```

Причина: `invest-public-api.tbank.ru` отдаёт цепочку сертификатов через:

```text
Russian Trusted Root CA
Russian Trusted Sub CA
*.tbank.ru
```

Пользователь НЕ хочет добавлять этот root CA глобально в систему и НЕ хочет отключать TLS verification.

Но пользователь готов использовать эту цепочку **только для процесса HammerTrade**, так как сервер будет одноцелевым под trading/research/paper/sandbox.

---

## Главная цель

Сделать изолированную поддержку Russian Trusted Root CA **только для HammerTrade-процесса**, не меняя системный trust store.

Нужно:

1. создать отдельный CA bundle внутри проекта;
2. добавить туда стандартные системные CA + Russian Trusted Root CA;
3. настроить переменные окружения только для проекта / будущего systemd-сервиса;
4. добавить connectivity checker;
5. проверить, что T-Bank API доступен через этот bundle;
6. задокументировать риски, rollback и правила безопасности.

---

## Важные ограничения безопасности

Строго запрещено:

- ставить Russian Trusted Root CA глобально в систему;
- выполнять `sudo update-ca-certificates` для Russian CA;
- отключать TLS verification;
- использовать `curl -k`;
- использовать `verify=False`;
- менять T-Bank SDK так, чтобы он игнорировал TLS ошибки;
- печатать токены в консоль;
- коммитить `.env`;
- коммитить реальные токены;
- добавлять live trading / broker execution;
- добавлять реальные заявки в рамках этой задачи.

Допустимо:

- создать отдельный CA bundle в `/opt/hammertrade/certs/`;
- использовать переменные окружения только для процесса HammerTrade:
  - `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`;
  - при необходимости `SSL_CERT_FILE`;
  - при необходимости `REQUESTS_CA_BUNDLE`;
- использовать этот bundle для connectivity check;
- сохранить placeholder `.crt.example` или README-инструкцию, но НЕ коммитить сам root CA, если он был скачан/получен на сервере.

---

# Часть 1. Структура certs

Создать директорию:

```text
certs/
```

В `.gitignore` добавить:

```gitignore
# local CA bundles / certificates
certs/*.pem
certs/*.crt
certs/*.cer
!certs/README.md
!certs/.gitkeep
```

Создать:

```text
certs/.gitkeep
certs/README.md
```

`certs/README.md` должен объяснять:

```markdown
# Certificates

This directory is for local runtime CA bundles.

Do not commit real CA certificates or combined CA bundles.

On servers where T-Bank API is served via Russian Trusted Root CA, create a local combined CA bundle and point only HammerTrade process to it via:

GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/opt/hammertrade/certs/tbank-combined-ca.pem

Do not install Russian Trusted Root CA globally.
Do not disable TLS verification.
```

---

# Часть 2. Скрипт сборки isolated CA bundle

Создать скрипт:

```text
scripts/build_tbank_ca_bundle.sh
```

Он должен:

1. принимать путь к Russian Trusted Root CA файлу;
2. брать системный CA bundle;
3. создавать combined bundle в `certs/tbank-combined-ca.pem`;
4. выставлять права `600` или `640`;
5. не требовать sudo;
6. не менять системный trust store.

Пример запуска:

```bash
bash scripts/build_tbank_ca_bundle.sh \
  --russian-root-ca /opt/hammertrade/certs/russian-trusted-root-ca.crt \
  --output /opt/hammertrade/certs/tbank-combined-ca.pem
```

## Поведение скрипта

Скрипт должен искать системный CA bundle по типичным путям:

```text
/etc/ssl/certs/ca-certificates.crt
/etc/pki/tls/certs/ca-bundle.crt
/etc/ssl/cert.pem
```

Для Ubuntu обычно:

```text
/etc/ssl/certs/ca-certificates.crt
```

Если системный bundle не найден — понятная ошибка.

Если Russian CA файл не найден — понятная ошибка.

Если output directory не существует — создать.

Не печатать содержимое сертификатов.

## Help

Поддержать:

```bash
bash scripts/build_tbank_ca_bundle.sh --help
```

---

# Часть 3. Connectivity checker

Создать Python CLI:

```text
scripts/check_tbank_connectivity.py
```

Цель: проверить, может ли текущая среда безопасно подключиться к T-Bank API.

Запуск:

```bash
python scripts/check_tbank_connectivity.py
```

С bundle:

```bash
GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/opt/hammertrade/certs/tbank-combined-ca.pem \
python scripts/check_tbank_connectivity.py
```

Или:

```bash
python scripts/check_tbank_connectivity.py \
  --ca-bundle /opt/hammertrade/certs/tbank-combined-ca.pem
```

## Что проверять

Минимум:

1. DNS:

```text
invest-public-api.tbank.ru
```

2. TLS через Python ssl:

```python
ssl.create_default_context(cafile=ca_bundle)
```

или системный контекст, если bundle не задан.

3. Опционально gRPC/T-Bank SDK smoke test:
   - если есть READONLY_TOKEN в `.env`, выполнить безопасный readonly-запрос, например поиск инструмента `SiM6` или получение specs;
   - если токена нет, не падать, а написать:

```text
READONLY_TOKEN not found, skipping SDK check.
```

Важно: не печатать токен.

## Вывод

Успех:

```text
T-Bank connectivity check
=========================

DNS: PASS invest-public-api.tbank.ru -> ...
TLS: PASS
SDK: PASS Future spec SiM6 fetched

Result: PASS
```

Ошибка:

```text
TLS: FAIL self-signed certificate in certificate chain
Result: FAIL
```

Если `--ca-bundle` передан, вывести:

```text
CA bundle: /opt/hammertrade/certs/tbank-combined-ca.pem
```

Не использовать `verify=False`.

---

# Часть 4. .env.example

Обновить `.env.example`.

Добавить:

```env
# Optional isolated CA bundle for gRPC/T-Bank API.
# Use only for HammerTrade process, not system-wide.
GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=
SSL_CERT_FILE=
REQUESTS_CA_BUNDLE=
```

Комментарии должны объяснять:

```text
Do not disable TLS verification.
Do not install Russian Trusted Root CA globally.
```

---

# Часть 5. Server-only env setup

Обновить `docs/deploy_yandex_server.md`.

Добавить раздел:

```markdown
## Isolated CA bundle for T-Bank API
```

Описать:

1. положить Russian Trusted Root CA в:

```text
/opt/hammertrade/certs/russian-trusted-root-ca.crt
```

2. собрать combined bundle:

```bash
cd /opt/hammertrade
bash scripts/build_tbank_ca_bundle.sh \
  --russian-root-ca /opt/hammertrade/certs/russian-trusted-root-ca.crt \
  --output /opt/hammertrade/certs/tbank-combined-ca.pem
```

3. добавить в `/opt/hammertrade/.env`:

```env
GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/opt/hammertrade/certs/tbank-combined-ca.pem
SSL_CERT_FILE=/opt/hammertrade/certs/tbank-combined-ca.pem
REQUESTS_CA_BUNDLE=/opt/hammertrade/certs/tbank-combined-ca.pem
```

4. проверить:

```bash
cd /opt/hammertrade
source .venv/bin/activate
set -a
source .env
set +a
python scripts/check_tbank_connectivity.py --ca-bundle /opt/hammertrade/certs/tbank-combined-ca.pem
```

5. rollback:

```bash
rm /opt/hammertrade/certs/tbank-combined-ca.pem
# remove GRPC_DEFAULT_SSL_ROOTS_FILE_PATH / SSL_CERT_FILE / REQUESTS_CA_BUNDLE from .env
```

## Важное предупреждение в документации

Добавить явно:

```markdown
This setup intentionally trusts Russian Trusted Root CA only for the HammerTrade process through an isolated CA bundle.

Do not install this CA globally with update-ca-certificates.

Do not use this server for personal browsing, email, password managers, or unrelated services.

At the current stage store only READONLY_TOKEN for paper/research. Sandbox token may be added later only when sandbox orders are implemented.
```

---

# Часть 6. systemd-ready env

Пока paper daemon ещё не реализован, но подготовить пример.

Создать:

```text
deploy/systemd/hammertrade-paper.example.service
```

Пример:

```ini
[Unit]
Description=HammerTrade Paper Trader
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/hammertrade
EnvironmentFile=/opt/hammertrade/.env
ExecStart=/opt/hammertrade/.venv/bin/python scripts/run_paper_trader.py --ticker SiM6 --class-code SPBFUT --timeframe 1m --profile balanced --direction-filter SELL
Restart=always
RestartSec=10
User=hammertrade

[Install]
WantedBy=multi-user.target
```

Важно: `run_paper_trader.py` может пока не существовать. В README написать, что это template for future MVP.

---

# Часть 7. README

Обновить README Deployment section.

Добавить коротко:

```markdown
### T-Bank TLS on some Russian networks

Some Russian networks/clouds may serve T-Bank API certificate chain via Russian Trusted Root CA.

HammerTrade does not install this CA globally and does not disable TLS verification.

If needed, create an isolated CA bundle and point only HammerTrade process to it with:

GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/opt/hammertrade/certs/tbank-combined-ca.pem
```

---

# Часть 8. Tests

Добавить unit-тесты без реального T-Bank API.

## tests/test_tbank_connectivity_cli.py

Проверить:

1. `--help` работает;
2. отсутствующий `--ca-bundle` даёт понятную ошибку;
3. если `.env` без токена — SDK check skipped, не падать;
4. функция DNS/TLS-check может быть замокана.

## tests/test_ca_bundle_script.py

Если bash тесты уже есть — добавить smoke:

```bash
bash scripts/build_tbank_ca_bundle.sh --help
bash -n scripts/build_tbank_ca_bundle.sh
```

Если bash тестов нет, достаточно проверить через pytest subprocess.

Не запускать реальные T-Bank API calls в тестах.

---

# Часть 9. Проверка на сервере

После реализации запушить изменения в GitHub.

На сервере:

```bash
cd /opt/hammertrade
git pull
source .venv/bin/activate
pip install -r requirements.txt
```

Пользователь вручную положит Russian Trusted Root CA файл в:

```text
/opt/hammertrade/certs/russian-trusted-root-ca.crt
```

Если файл уже есть, использовать его.

Собрать bundle:

```bash
bash scripts/build_tbank_ca_bundle.sh \
  --russian-root-ca /opt/hammertrade/certs/russian-trusted-root-ca.crt \
  --output /opt/hammertrade/certs/tbank-combined-ca.pem
```

Добавить переменные в `.env`.

Проверить:

```bash
set -a
source .env
set +a
python scripts/check_tbank_connectivity.py --ca-bundle /opt/hammertrade/certs/tbank-combined-ca.pem
```

Ожидаемый результат:

```text
Result: PASS
```

Если FAIL — вывести понятную диагностику.

---

# Definition of Done

Задача выполнена, если:

1. Есть `certs/README.md`.
2. Реальные сертификаты не коммитятся.
3. `.gitignore` исключает `certs/*.pem`, `certs/*.crt`, `certs/*.cer`.
4. Есть `scripts/build_tbank_ca_bundle.sh`.
5. Есть `scripts/check_tbank_connectivity.py`.
6. `.env.example` содержит опциональные переменные для isolated CA bundle.
7. `docs/deploy_yandex_server.md` обновлён инструкцией.
8. Есть пример systemd unit:
   - `deploy/systemd/hammertrade-paper.example.service`.
9. README обновлён.
10. Тесты проходят:

```bash
pytest
```

11. Bash-синтаксис валиден:

```bash
bash -n scripts/build_tbank_ca_bundle.sh
```

12. Russian Trusted Root CA не установлен глобально.
13. TLS verification не отключалась.
14. Токены не печатались и не коммитились.

---

# Отчёт после выполнения

После реализации напиши:

```text
Что добавлено:
...

Как собрать isolated CA bundle:
...

Какие переменные добавить в .env:
...

Как проверить T-Bank connectivity:
...

Как rollback:
...

Что проверено:
...

Что НЕ делалось:
...
```

В блоке "Что НЕ делалось" обязательно указать:

```text
- Russian Trusted Root CA не устанавливался глобально;
- TLS verification не отключалась;
- verify=False / curl -k не использовались;
- реальные токены не печатались;
- live trading не добавлялся;
- sandbox orders не добавлялись;
- broker execution не добавлялся.
```
