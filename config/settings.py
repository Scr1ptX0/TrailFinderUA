import glob
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-replace-me-in-production-use-env-var",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost 127.0.0.1").split()

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",          # GeoDjango
    "rest_framework",               # DRF
    "rest_framework_gis",           # GeoJSON support
    "trails",
    "users",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Database — PostGIS
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("DB_NAME", "trailfinder_db"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "trailpass123"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# ---------------------------------------------------------------------------
# GeoDjango — GDAL / GEOS / PROJ paths (Windows)
#
# We source DLLs from the Python wheels already installed (pyogrio bundles
# GDAL, shapely bundles GEOS, pyproj bundles PROJ).  The wheel DLL names
# contain a content hash so we glob for them.
# ---------------------------------------------------------------------------
if os.name == "nt":
    import site

    # getsitepackages() returns [python_root, python_root/Lib/site-packages] on Windows
    _sp = Path(next(p for p in site.getsitepackages() if "site-packages" in p))

    def _find_dll(lib_dir: str, pattern: str) -> str:
        matches = glob.glob(str(_sp / lib_dir / pattern))
        if not matches:
            raise FileNotFoundError(
                f"Cannot find {pattern} in {_sp / lib_dir}. "
                "Make sure pyogrio and shapely are installed."
            )
        return matches[0]

    # GDAL from pyogrio wheel
    GDAL_LIBRARY_PATH = _find_dll("pyogrio.libs", "gdal*.dll")
    # GEOS from shapely wheel
    GEOS_LIBRARY_PATH = _find_dll("shapely.libs", "geos_c*.dll")

    # Add pyogrio.libs to PATH so GDAL can find its sibling DLLs (proj, sqlite3, …)
    _pyogrio_libs = str(_sp / "pyogrio.libs")
    _shapely_libs = str(_sp / "shapely.libs")
    os.environ["PATH"] = _pyogrio_libs + os.pathsep + _shapely_libs + os.pathsep + os.environ.get("PATH", "")

    # PROJ data directory — prefer pyogrio's bundled proj.db (matches the GDAL
    # version it was compiled with), falling back to pyproj then PostGIS.
    _proj_candidates = [
        _sp / "pyogrio" / "proj_data",                                   # pyogrio wheel (best match)
        Path(r"C:\Program Files\PostgreSQL\17\share\contrib\postgis-3.5\proj"),  # PostGIS
        _sp / "pyproj" / "proj_dir" / "share" / "proj",                  # pyproj (older)
    ]
    for _candidate in _proj_candidates:
        if (_candidate / "proj.db").exists():
            os.environ["PROJ_LIB"] = str(_candidate)
            os.environ["PROJ_DATA"] = str(_candidate)
            break

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "users.UserProfile"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/users/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Kyiv"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# ---------------------------------------------------------------------------
# Leaflet CDN versions (referenced in base.html context)
# ---------------------------------------------------------------------------
LEAFLET_VERSION = "1.9.4"
