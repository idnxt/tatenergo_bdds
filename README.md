# tatenergo_bdds

Система обработки и аналитики данных начислений ЖКУ (ТАТЭНЕРГОСБЫТ).

## Быстрый старт (Windows 10/11)

### 1. PostgreSQL portable

Скачайте ZIP-архив PostgreSQL для Windows (без установщика):
- https://www.enterprisedb.com/download-postgresql-binaries
- Версия: 15.x или 16.x, платформа: Windows x86-64

Распакуйте содержимое архива в папку `pgsql\` внутри папки проекта.
Должна получиться структура:
```
tatenergo_bdds\
    pgsql\
        bin\
            pg_ctl.exe
            postgres.exe
            ...
        lib\
        share\
```

### 2. Python

Установите Python 3.11-3.13: https://python.org/downloads/

При установке отметьте **"Add Python to PATH"**.

### 3. Запуск

Запустите `start.bat` двойным кликом.

При первом запуске автоматически:
- создаётся виртуальное окружение и устанавливаются зависимости
- инициализируется кластер PostgreSQL
- создаётся база данных и применяются миграции
- открывается браузер на http://127.0.0.1:8000

### 4. Работа с приложением

- **Импорт → Загрузить файл** — загрузка ежемесячного файла начислений
- **Отчёты → Сводка** — аналитика по выбранному периоду

### 5. Остановка

Нажмите **Ctrl+C** в окне с приложением, или запустите `stop.bat`.

---

## Портабельный релиз (перенос на другую машину)

Скопируйте всю папку `tatenergo_bdds\` целиком (включая `pgsql\` и `pgdata\`).
На новой машине нужен только Python — запустите `start.bat`.

Если переносите **без данных** (чистая установка) — копируйте без `pgdata\`.

---

## Структура проекта

```
tatenergo_bdds/
├── app/
│   ├── main.py              # FastAPI приложение
│   ├── config.py            # Конфигурация
│   ├── db/
│   │   ├── engine.py        # Подключение к БД
│   │   ├── models.py        # SQLAlchemy модели
│   │   └── migrations/      # SQL-миграции
│   ├── modules/
│   │   ├── importer/        # Модуль импорта файлов
│   │   └── reports/         # Модуль отчётов
│   └── templates/           # Jinja2 шаблоны
├── data/                    # Папка для входящих файлов
├── pgsql/                   # PostgreSQL portable (не в git)
├── pgdata/                  # Данные БД (не в git)
├── venv/                    # Виртуальное окружение (не в git)
├── init_db.py               # Инициализация БД
├── start.bat                # Запуск
├── stop.bat                 # Остановка
└── requirements.txt
```

---

## Формат входного файла

- Кодировка: ANSI (cp1251)
- Заголовок: две строки `#FILESUM` и `#TYPE`
- Разделитель полей: `;`
- Разделитель субполей: `:`
- Блок поставщиков: начинается с `Oplata:`
- Блок приборов учёта: начинается с `Pu:`

Актуальный (текущий) файл доступен по адресу: http://www.tatenergosbyt.ru/about/partners/ (Реестры по ЖКУ: Сводный реестр начислений с показаниями за ...)
Или по прямой ссылке: https://tatenergosbyt.ru/about/partners/archfl/fileLS/Accruals_Counters.zip

Архивы с 2021.06: https://t.me/tatenergo_database

---

## .gitignore

```
pgsql/
pgdata/
venv/
data/
tmp/
__pycache__/
*.pyc
.env
```
