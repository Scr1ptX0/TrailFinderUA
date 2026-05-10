# TrailFinder UA — Геоінформаційна система гірських маршрутів Карпат

> Курсовий / дипломний проект з геоінформаційних систем та веб-розробки

---

## Зміст

1. [Опис проекту](#опис-проекту)
2. [Технологічний стек](#технологічний-стек)
3. [Архітектура системи](#архітектура-системи)
4. [Структура проекту](#структура-проекту)
5. [Функціональні можливості](#функціональні-можливості)
6. [REST API](#rest-api)
7. [Алгоритм маршрутизації](#алгоритм-маршрутизації)
8. [Встановлення та запуск](#встановлення-та-запуск)
9. [Імпорт даних OSM](#імпорт-даних-osm)
10. [Скріншоти](#скріншоти)

---

## Опис проекту

**TrailFinder UA** — це веб-застосунок для пошуку, перегляду та побудови
пішохідних маршрутів Українських Карпат. Система використовує відкриті
геопросторові дані OpenStreetMap та надає:

- інтерактивну карту з накладанням маршрутів і точок інтересу (POI);
- автоматичну побудову оптимального маршруту між двома довільними точками
  на будь-якій дорозі або стежці в межах Карпат;
- класифікацію маршрутів за шкалою SAC (T1–T6);
- систему відгуків та збереження маршрутів для авторизованих користувачів;
- REST API з підтримкою GeoJSON для зовнішніх клієнтів.

**Охоплення даних:** Бескиди → Горгани → Свидовець → Чорногора →
Покутсько-Буковинські Карпати → Мармарош (bbox 47.85–49.0°N, 22.2–25.3°E).

---

## Технологічний стек

| Шар | Технологія |
|-----|-----------|
| Back-end | Python 3.13 · Django 5.1 · GeoDjango |
| База даних | PostgreSQL 17 + PostGIS 3.5 |
| REST API | Django REST Framework 3.15 · djangorestframework-gis |
| Маршрутизація | NetworkX 3.x (граф A\*) · scipy cKDTree |
| Геопросторові дані | OpenStreetMap / Overpass API |
| Картографія | Leaflet.js 1.9.4 · Leaflet.markercluster · OpenTopoMap · ESRI Satellite |
| Front-end | Bootstrap 5.3 · HTMX 1.9 · Font Awesome 6.5 |
| Аутентифікація | Django Auth (сесії) |

---

## Архітектура системи

```
┌─────────────────────────────────────────────────────┐
│                    Браузер (клієнт)                  │
│  Leaflet.js  ←→  Bootstrap/HTMX  ←→  Fetch API      │
└─────────────────┬───────────────────────┬───────────┘
                  │ HTML-сторінки         │ JSON/GeoJSON
┌─────────────────▼───────────────────────▼───────────┐
│                  Django Application                  │
│                                                      │
│  ┌──────────────────┐    ┌────────────────────────┐  │
│  │   HTML Views     │    │     REST API Views     │  │
│  │  (views.py)      │    │   (api_views.py)       │  │
│  └────────┬─────────┘    └──────────┬─────────────┘  │
│           │                         │                 │
│  ┌────────▼─────────────────────────▼─────────────┐  │
│  │               Models (GeoDjango)               │  │
│  │  Trail · POI · TrailNode · TrailReview         │  │
│  └────────────────────────┬────────────────────────┘  │
│                           │                          │
│  ┌────────────────────────▼────────────────────────┐  │
│  │          services/routing.py                    │  │
│  │  TrailGraph (NetworkX DiGraph + scipy cKDTree)  │  │
│  └─────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│         PostgreSQL 17 + PostGIS 3.5                  │
│  trails_trail · trails_poi · trails_trailnode        │
│  trails_trailreview · users_userprofile              │
└──────────────────────────────────────────────────────┘
```

---

## Структура проекту

```
trailfinder/
├── config/                     # Конфігурація Django
│   ├── settings.py             # Налаштування (БД, GeoDjango, DRF, CDN)
│   ├── urls.py                 # Головний роутер URL
│   └── wsgi.py
│
├── trails/                     # Основний Django-застосунок
│   ├── models.py               # Trail, POI, TrailNode, TrailReview
│   ├── views.py                # HTML-вʼюхи (home, list, detail, route_builder)
│   ├── api_views.py            # REST API вʼюхи
│   ├── api_urls.py             # URL-маршрути API
│   ├── serializers.py          # GeoJSON-серіалізатори (DRF-GIS)
│   ├── utils.py                # Формула Найсміта, haversine, SAC_NUMERIC
│   ├── apps.py                 # AppConfig — warm-up графу при старті
│   ├── services/
│   │   └── routing.py          # TrailGraph: A* + scipy cKDTree
│   └── management/commands/
│       └── import_osm_trails.py  # OSM → PostGIS (Overpass API)
│
├── users/                      # Аутентифікація
│   ├── models.py               # UserProfile (розширення AbstractUser)
│   ├── views.py                # login, register, profile, logout
│   └── urls.py
│
├── templates/
│   ├── base.html               # Загальний шаблон (navbar, Leaflet CDN)
│   ├── route_builder.html      # Побудова маршруту
│   └── trails/
│       ├── home.html           # Головна карта
│       ├── list.html           # Список маршрутів з фільтрами
│       └── detail.html         # Деталі маршруту + відгуки
│
├── requirements.txt            # Python-залежності
├── .env.example                # Шаблон змінних середовища
└── manage.py
```

---

## Функціональні можливості

### Карта (/)
- Інтерактивна карта Leaflet з шарами: Топографічна (OpenTopoMap),
  Стандартна (OSM), Супутник (ESRI WorldImagery)
- Накладання всіх активних маршрутів у вигляді кольорових ліній (SAC-кольори)
- Кластеризація POI (Leaflet.markercluster) — немає гальмування при 4000+ точках
- Клік на маршрут → popup з назвою та SAC-класом

### Список маршрутів (/trails/)
- HTMX-фільтрація за SAC-шкалою, макс. відстанню, макс. набором висоти
- Пагінація (12 карток на сторінку)

### Деталі маршруту (/trails/<id>/)
- Карта з відображенням лише цього маршруту + POI в радіусі 500 м
- Статистика: відстань, набір висоти, час за формулою Найсміта
- Збереження маршруту (AJAX, тільки для авторизованих)
- Відгуки зі зірками та фото (AJAX POST)

### Побудова маршруту (/route-builder/)
- Клік на будь-яку точку карти → встановлення старту / фінішу
- Маршрутизація по стежках і дорогах (476 стежок + 139K доріг)
- Три перемикачі шарів: Стежки · Дороги (lazy load) · POI
- Повзунки вагових коефіцієнтів w1 (відстань), w2 (висота), w3 (складність)
- Відображення фактичної прив'язки (snap) до найближчої дороги

### Аутентифікація
- Реєстрація / логін / профіль / вихід
- Збережені маршрути у профілі

---

## REST API

Базовий префікс: `/api/`

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/api/trails/map/?type=trail` | GeoJSON маршрутів (без пагінації) |
| GET | `/api/trails/map/?type=road` | GeoJSON доріг |
| GET | `/api/trails/` | Список маршрутів (пагінація, фільтри) |
| GET | `/api/trails/<id>/` | Деталі маршруту |
| GET/POST | `/api/trails/<id>/reviews/` | Відгуки |
| POST | `/api/trails/<id>/save/` | Toggle збереження |
| GET | `/api/pois/nearby/?lat=&lon=&radius_m=` | POI в радіусі |
| POST | `/api/route/build/` | Побудова маршруту |

### Приклад запиту до `/api/route/build/`

```json
POST /api/route/build/
Content-Type: application/json

{
  "start":   [48.3, 24.0],
  "end":     [48.5, 24.3],
  "weights": { "w1": 1.0, "w2": 1.5, "w3": 1.0 }
}
```

### Відповідь

```json
{
  "type": "Feature",
  "geometry": {
    "type": "LineString",
    "coordinates": [[24.001, 48.301], ...]
  },
  "properties": {
    "distance_km": 12.345,
    "estimated_time_h": 2.47,
    "snap_start": [48.301, 24.001],
    "snap_end":   [48.498, 24.298],
    "snap_start_m": 45,
    "snap_end_m": 87
  }
}
```

---

## Алгоритм маршрутизації

Реалізовано в `trails/services/routing.py`.

### Побудова графу (`TrailGraph.build_from_db`)

1. Завантажує всі `Trail` об'єкти з БД (~140K записів).
2. Дискретизує геометрію кожного маршруту:
   - Стежки (highway_type=`trail`): крок 30 м
   - Дороги (highway_type=`road`): крок 100 м
3. Координати округлюються до 5 знаків (~1 м) — автоматичне злиття
   вузлів-перехресть, що мають однакові координати в OSM.
4. Будує `scipy.spatial.cKDTree` для O(log N) просторових запитів.
5. Зшиває кінцеві точки суміжних маршрутів:
   - Стежки: радіус 100 м
   - Дороги: радіус 8 м (тільки реальні перехрестя)

**Результат:** ~500K вузлів, ~1.2M ребер, будується за ~30 с у фоновому потоці.

### Пошук маршруту (A\*)

```
edge_cost(u, v) = w1 × dist_m + w2 × elev_diff + w3 × sac_numeric × 100
heuristic(u, v) = haversine_distance(u, v)        # допустима евристика
```

- Прив'язка точок до графу: O(log N) через `cKDTree.query`
- Пошук шляху: `networkx.astar_path` з динамічними ваговими коефіцієнтами
- Радіус snap: максимум 5 км (поза цим діапазоном — помилка з підказкою)

---

## Встановлення та запуск

> Детальна покрокова інструкція — у файлі **[INSTALL.md](INSTALL.md)**

### Короткий старт

```bash
# 1. Клонувати / розпакувати проект
cd trailfinder

# 2. Встановити залежності
pip install -r requirements.txt

# 3. Налаштувати .env
cp .env.example .env
# відредагувати .env (DB_PASSWORD тощо)

# 4. Створити БД PostgreSQL + PostGIS (один раз)
psql -U postgres -c "CREATE DATABASE trailfinder_db;"
psql -U postgres -d trailfinder_db -c "CREATE EXTENSION postgis;"

# 5. Застосувати міграції
python manage.py migrate

# 6. Імпортувати дані OSM (перший запуск ~5–10 хв)
python manage.py import_osm_trails --clear

# 7. Створити суперкористувача
python manage.py createsuperuser

# 8. Запустити сервер
python manage.py runserver
```

Відкрити: http://127.0.0.1:8000

---

## Імпорт даних OSM

Команда `import_osm_trails` завантажує дані з Overpass API
(https://overpass-api.de) і зберігає їх у PostGIS.

```bash
# Повний імпорт (стежки + дороги, очистити попередні дані)
python manage.py import_osm_trails --clear

# Тільки стежки (SAC-шкала + marked trails)
python manage.py import_osm_trails --trails-only

# Тільки дороги (path, footway, track, cycleway, residential, …)
python manage.py import_osm_trails --roads-only

# Інший bbox (приклад — тільки Чорногора)
python manage.py import_osm_trails --bbox 48.05,24.4,48.35,24.85
```

**Результат повного імпорту:**
- ~476 помічених стежок (sac_scale / colour / osmc:symbol)
- ~139 000 сегментів доріг і стежок
- ~4 400 POI (джерела, притулки, кемпінги, оглядові майданчики)

---

## Скріншоти

> Скріншоти додаються у папку `docs/screenshots/` при здачі.

| Сторінка | Опис |
|----------|------|
| Головна карта | Усі маршрути на топографічній основі |
| Список маршрутів | Картки з фільтрами SAC/відстань/висота |
| Деталі маршруту | Карта + статистика + відгуки |
| Побудова маршруту | A* по стежках і дорогах, snap-маркери |

---

## Ліцензія даних

Картографічні дані: © [OpenStreetMap](https://www.openstreetmap.org/copyright)
contributors (ODbL).  
Топографічні тайли: © [OpenTopoMap](https://opentopomap.org) (CC-BY-SA).  
Супутникові тайли: © Esri, USGS, NOAA.
