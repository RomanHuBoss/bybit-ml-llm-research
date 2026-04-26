# Установка на Windows 11 x64

Основной способ установки теперь общий для Windows/Linux: `install.py` и `run.py`. PowerShell-скрипты в `scripts/` сохранены как legacy-вариант.

## 1. Python

Рекомендуется Python 3.11+ x64.

```powershell
python --version
```

Если используется Python Launcher:

```powershell
py -3.11 --version
```

## 2. PostgreSQL

Установите PostgreSQL 15/16/17 для Windows. Создайте базу:

```sql
CREATE USER bybit_lab_user WITH PASSWORD 'change_me';
CREATE DATABASE bybit_lab OWNER bybit_lab_user;
GRANT ALL PRIVILEGES ON DATABASE bybit_lab TO bybit_lab_user;
```

Если при создании таблиц возникает ошибка прав на схему public:

```sql
GRANT ALL ON SCHEMA public TO bybit_lab_user;
ALTER SCHEMA public OWNER TO bybit_lab_user;
```

## 3. Установка зависимостей

```powershell
python install.py
```

Скрипт создает `.venv`, ставит зависимости из `requirements.txt` и создает `.env` из `.env.example`, если `.env` еще отсутствует.

Если нужно использовать конкретный интерпретатор:

```powershell
python install.py --python "C:\Path\To\python.exe"
```

## 4. .env

```powershell
notepad .env
```

Проверьте PostgreSQL-параметры:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=bybit_lab
POSTGRES_USER=bybit_lab_user
POSTGRES_PASSWORD=change_me
```

CryptoPanic-ключ не обязателен. По умолчанию:

```env
USE_CRYPTOPANIC=false
CRYPTOPANIC_TOKEN=
```

## 5. Инициализация БД

```powershell
python run.py db-check
python run.py init-db
```


Если при `init-db` появляется `UnicodeDecodeError: 'utf-8' codec can't decode byte ...`, сначала выполните:

```powershell
python run.py db-check
```

Чаще всего это неверный пароль/пользователь, отсутствующая база или незапущенный PostgreSQL, а `psycopg2` на Windows показывает ошибку кодировки вместо исходного текста PostgreSQL. Для локальной разработки используйте ASCII-пароль, например `change_me`, и сохраняйте `.env` в UTF-8.

## 6. Запуск

```powershell
python run.py
```

Открыть:

```text
http://127.0.0.1:8000
```

## 7. Диагностика и тесты

```powershell
python run.py doctor
python run.py check
```

## 8. Legacy PowerShell helper'ы

Старый способ по-прежнему доступен:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1
```

## 9. Ollama / LLM

Установите Ollama отдельно. Затем скачайте модель:

```powershell
ollama pull llama3.1:8b
```

Проверьте endpoint:

```powershell
curl http://127.0.0.1:11434/api/generate -d '{"model":"llama3.1:8b","prompt":"test","stream":false}'
```

Для RTX 3060 12GB лучше начинать с 7B/8B quantized-модели.

## 10. Рекомендуемый порядок работы

1. `Sync universe` — обновить ликвидность Bybit и выбрать hybrid universe.
2. `Sync market` — загрузить свечи/funding/OI.
3. `Sync sentiment` — загрузить Fear&Greed, GDELT, RSS и рассчитать market_microstructure.
4. `Build signals` — построить rule-based сигналы.
5. `Backtest` — проверить стратегию.
6. `Train ML` — обучить модель на выбранном символе.
7. `Rank candidates` — выбрать лучшие paper-trading кандидаты.

## 11. Live trading

Проект не отправляет реальные ордера. Это сделано намеренно. Добавление live-trading требует отдельного аудита API-ключей, лимитов, ошибок исполнения, ликвидаций и kill-switch.

## Если в консоли были pandas warning

В старых ревизиях при построении сигналов могли повторяться предупреждения pandas про `read_sql_query` и `fillna`:

```text
UserWarning: pandas only supports SQLAlchemy connectable ...
FutureWarning: Downcasting object dtype arrays on .fillna ...
```

Это не означало падение сервера, но засоряло логи и могло скрывать настоящие ошибки. В текущей ревизии предупреждения устранены:

- чтение DataFrame из PostgreSQL выполняется через DB-API cursor;
- признак `is_eligible` приводится к безопасному boolean-типу без deprecated downcasting.

Проверка после обновления:

```powershell
python run.py check
python run.py test
```

Ожидаемо: `15 passed`.
