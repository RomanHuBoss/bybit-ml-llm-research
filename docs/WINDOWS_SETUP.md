# Установка на Windows 11 x64

## 1. Python

Рекомендуется Python 3.11 x64.

```powershell
py -3.11 --version
```

Если Python 3.11 не установлен, можно использовать актуальный Python 3.12, но проект тестировался под 3.11-совместимый стек зависимостей.

## 2. PostgreSQL

Установите PostgreSQL 15/16/17 для Windows. Создайте базу:

```sql
CREATE DATABASE bybit_lab;
CREATE USER bybit_lab_user WITH PASSWORD 'change_me';
GRANT ALL PRIVILEGES ON DATABASE bybit_lab TO bybit_lab_user;
```

Если при создании таблиц возникает ошибка прав на схему public:

```sql
GRANT ALL ON SCHEMA public TO bybit_lab_user;
ALTER SCHEMA public OWNER TO bybit_lab_user;
```

## 3. Виртуальное окружение

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

## 4. .env

```powershell
copy .env.example .env
notepad .env
```

CryptoPanic-ключ не обязателен. По умолчанию:

```env
USE_CRYPTOPANIC=false
CRYPTOPANIC_TOKEN=
```

## 5. Инициализация БД

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
```

## 6. Запуск

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_windows.ps1
```

Открыть:

```text
http://127.0.0.1:8000
```

## 7. Ollama / LLM

Установите Ollama отдельно. Затем скачайте модель:

```powershell
ollama pull llama3.1:8b
```

Проверьте endpoint:

```powershell
curl http://127.0.0.1:11434/api/generate -d '{"model":"llama3.1:8b","prompt":"test","stream":false}'
```

Для RTX 3060 12GB лучше начинать с 7B/8B quantized-модели.

## 8. Рекомендуемый порядок работы

1. `Sync universe` — обновить ликвидность Bybit и выбрать hybrid universe.
2. `Sync market` — загрузить свечи/funding/OI.
3. `Sync sentiment` — загрузить Fear&Greed, GDELT, RSS и рассчитать market_microstructure.
4. `Build signals` — построить rule-based сигналы.
5. `Backtest` — проверить стратегию.
6. `Train ML` — обучить модель на выбранном символе.
7. `Rank candidates` — выбрать лучшие paper-trading кандидаты.

## 9. Live trading

Проект не отправляет реальные ордера. Это сделано намеренно. Добавление live-trading требует отдельного аудита API-ключей, лимитов, ошибок исполнения, ликвидаций и kill-switch.
