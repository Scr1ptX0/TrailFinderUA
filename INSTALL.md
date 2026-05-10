# Інструкція з встановлення TrailFinder UA

## Системні вимоги

| Компонент | Мінімальна версія |
|-----------|------------------|
| Python | 3.11+ |
| PostgreSQL | 14+ |
| PostGIS | 3.0+ |
| RAM | 4 GB (8 GB рекомендовано для граф-будування) |
| ОС | Windows 10/11 · Ubuntu 22.04+ · macOS 13+ |

---

## Крок 1 — PostgreSQL + PostGIS

### Windows

1. Завантажити інсталятор PostgreSQL з https://www.postgresql.org/download/windows/
2. Під час інсталяції **обов'язково** вибрати компонент **Stack Builder**
3. Після встановлення запустити Stack Builder → обрати сервер → **Spatial Extensions → PostGIS**

Перевірка:
```sql
-- Запустити в pgAdmin або psql
SELECT postgis_version();
-- Повинно вивести: 3.x.x ...
```

### Linux (Ubuntu/Debian)
```bash
sudo apt install postgresql postgresql-contrib postgis
sudo systemctl start postgresql
```

### macOS
```bash
brew install postgresql postgis
brew services start postgresql
```

---

## Крок 2 — Створення бази даних

```sql
-- У psql або pgAdmin:
CREATE USER trailuser WITH PASSWORD 'trailpass123';
CREATE DATABASE trailfinder_db OWNER trailuser;
\c trailfinder_db
CREATE EXTENSION postgis;
CREATE EXTENSION postgis_topology;
GRANT ALL PRIVILEGES ON DATABASE trailfinder_db TO trailuser;
```

---

## Крок 3 — Python-оточення

```bash
# Рекомендується створити virtual environment
python -m venv .venv

# Активація (Windows)
.venv\Scripts\activate

# Активація (Linux/macOS)
source .venv/bin/activate

# Встановлення залежностей
pip install -r requirements.txt
```

> **Windows + GeoDjango:** бібліотеки GDAL/GEOS підтягуються автоматично
> з пакетів `pyogrio` та `shapely` — окремий інсталятор GDAL **не потрібен**.

---

## Крок 4 — Змінні середовища

Скопіюйте шаблон і заповніть:
```bash
cp .env.example .env
```

Мінімальний `.env`:
```
DB_NAME=trailfinder_db
DB_USER=trailuser
DB_PASSWORD=trailpass123
DB_HOST=localhost
DB_PORT=5432
DJANGO_SECRET_KEY=your-secret-key-here-change-me
DJANGO_DEBUG=True
```

Згенерувати секретний ключ:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## Крок 5 — Міграції

```bash
python manage.py migrate
```

Очікуваний вивід:
```
Operations to perform:
  Apply all migrations: admin, auth, contenttypes, sessions, trails, users
Running migrations:
  Applying trails.0001_initial... OK
  ...
  Applying trails.0004_add_highway_type... OK
```

---

## Крок 6 — Імпорт даних OSM

> Потрібне підключення до Інтернету. Час: ~5–15 хвилин.

```bash
# Повний імпорт (рекомендується для першого запуску)
python manage.py import_osm_trails --clear
```

Прогрес:
```
Pass 1 — fetching hiking trails …
  Raw elements: ~5000
Pass 2 — fetching roads & paths …
  Raw elements: ~139000
Total ways: ~144000, POIs: ~4400
Saving ways to DB …
Import complete.
```

---

## Крок 7 — Суперкористувач

```bash
python manage.py createsuperuser
```

---

## Крок 8 — Запуск

```bash
python manage.py runserver
```

Відкрити у браузері:
- **Застосунок:** http://127.0.0.1:8000
- **Адміністрування:** http://127.0.0.1:8000/admin

---

## Перевірка роботи

```bash
# Тест API — список маршрутів
curl http://127.0.0.1:8000/api/trails/map/?type=trail

# Тест побудови маршруту
curl -X POST http://127.0.0.1:8000/api/route/build/ \
  -H "Content-Type: application/json" \
  -d '{"start":[48.3,24.0],"end":[48.5,24.3],"weights":{"w1":1,"w2":1.5,"w3":1}}'
```

---

## Можливі проблеми

### `ImproperlyConfigured: Could not find the GDAL library`
**Windows:** Встановіть `pyogrio` і `shapely` через pip — вони включають GDAL/GEOS:
```bash
pip install pyogrio shapely
```

### `connection to server on socket failed`
Перевірте, що PostgreSQL запущений:
```bash
# Windows
net start postgresql-x64-17

# Linux
sudo systemctl status postgresql
```

### Перший запит маршруту займає ~30–60 сек
Нормальна поведінка — граф (~500K вузлів) будується у фоновому потоці
при старті сервера. Наступні запити — миттєві.

### `CommandError: All Overpass API attempts failed`
Overpass API може бути перевантажений. Спробуйте через 5–10 хвилин або
використайте дзеркало: встановіть `OVERPASS_URL` у `import_osm_trails.py`
на `https://overpass.kumi.systems/api/interpreter`.

---

## Структура URL

| URL | Опис |
|-----|------|
| `/` | Головна карта |
| `/trails/` | Список маршрутів |
| `/trails/<id>/` | Деталі маршруту |
| `/route-builder/` | Побудова маршруту |
| `/users/login/` | Вхід |
| `/users/register/` | Реєстрація |
| `/users/profile/` | Профіль |
| `/admin/` | Django Admin |
| `/api/` | REST API |
