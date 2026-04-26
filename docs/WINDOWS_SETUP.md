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

Ожидаемо: `24 passed`.

## Если в консоли был joblib/loky warning про wmic

При обучении ML на Windows может появляться предупреждение:

```text
UserWarning: Could not find the number of physical cores ...
[WinError 2] Не удается найти указанный файл
wmic CPU Get NumberOfCores /Format:csv
```

Это не означает, что `/api/ml/train` упал: в показанном сценарии сервер вернул `200 OK`. Причина в том, что `joblib/loky` пытается определить физические ядра через `wmic`, а в современных Windows эта утилита может отсутствовать.

В текущей ревизии проект задает `LOKY_MAX_CPU_COUNT` до импорта `sklearn/joblib`. По умолчанию берется число логических ядер. Чтобы ограничить ML-нагрузку вручную, добавьте в `.env`:

```env
ML_MAX_CPU_COUNT=4
```

Проверка:

```powershell
python run.py doctor
python run.py check
```

Ожидаемо: `24 passed`.

## Если warning `joblib/loky` про `wmic` всё еще появляется

Полностью остановите старый сервер и запустите проект из корня:

```powershell
cd C:\AITrading\BybitResearchLabAI
python run.py
```

В проект добавлен `sitecustomize.py`, который Python импортирует автоматически, когда корень проекта находится в `sys.path`. При запуске из другой рабочей папки или из внешней службы этот файл может не подхватиться. В таком случае задайте переменную окружения вручную:

```powershell
setx LOKY_MAX_CPU_COUNT 4
```

Затем откройте новый терминал и перезапустите сервер.

### Если warning joblib/loky про wmic всё ещё появляется

Используйте запуск через проектный launcher:

```powershell
python run.py
```

Launcher передает `LOKY_MAX_CPU_COUNT` в дочерний процесс Uvicorn, включая `--reload`. Автоматический дефолт меньше числа логических ядер, потому что значение, равное `os.cpu_count()`, в некоторых версиях joblib/loky не отключает проверку физических ядер через отсутствующий `wmic`.

Для прямого запуска можно задать переменную вручную до старта сервера:

```powershell
$env:LOKY_MAX_CPU_COUNT="4"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Если `/api/llm/brief` падает на datetime JSON serialization

В актуальной версии добавлена защита от этой ошибки. PostgreSQL-строки, pandas/numpy значения, `datetime`, `Decimal` и похожие типы нормализуются перед формированием LLM-промпта. После обновления архива полностью перезапустите сервер, чтобы `app.llm` был импортирован заново.

## Обновленный торговый интерфейс

Фронтенд переработан из технической таблицы в decision cockpit для ручного оператора. Главный экран теперь сначала показывает итоговый статус кандидата (`ПРОВЕРИТЬ`, `НАБЛЮДАТЬ`, `ЗАПРЕТ`), оценку, направление, план сделки, risk/reward, ограничения позиции, причины сигнала и стоп-факторы. Служебные таблицы universe/ranking/signals перенесены в раскрываемый блок технических деталей, чтобы не мешать принятию решения.

Важно: интерфейс не отправляет ордера и не создает ботов автоматически. Статус `ПРОВЕРИТЬ` означает только, что кандидата можно передать оператору на ручную проверку стакана, новостей, риска портфеля и актуальности цены.



## Новый рабочий экран оператора

После запуска `python run.py` откройте `http://127.0.0.1:8000`. Основной экран теперь построен вокруг ручного решения:

1. Слева находится порядок работы и скрытый блок операций с данными.
2. Сверху в центре показан итоговый статус выбранного сетапа: `НЕТ ВХОДА`, `НАБЛЮДАТЬ`, `К ПРОВЕРКЕ`.
3. Красный пункт в чек‑листе означает отмену входа.
4. Trade ticket нужен только для ручной сверки entry/SL/TP/R/R.
5. Технические детали, журнал и график бэктеста находятся в раскрываемом блоке внизу.

Система по-прежнему не отправляет ордера и не создает ботов автоматически.

## Фоновая LLM-оценка

После запуска сервера фоновый сервис автоматически оценивает top-кандидатов из очереди `research/rank` через локальный Ollama endpoint. Нажимать `LLM brief` для каждого инструмента больше не нужно: интерфейс сам показывает `LLM: готово`, `LLM: анализируется`, `LLM: ошибка` или `LLM: ожидает фонового цикла`.

Для немедленного внеочередного цикла используйте кнопку `Обновить LLM сейчас` или endpoint:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/llm/background/run-now
```

Если Ollama не запущен, приложение продолжает работать, а LLM-статус будет показывать ошибку фонового анализа. Это не включает live-trading и не создает ботов автоматически.
