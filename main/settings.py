import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv('.env.dev')

BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-r$=kolofo@otwg#dxtuxf9+&78wp%s!ur3p(hh^i11#!0wpx!_')

DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    ".localhost",
    '.levelupapp.ru',

    'm.vk.com',
    'tunnel.levoneapp.ru',

    'levonework.ru'
]

CSRF_TRUSTED_ORIGINS = [
    'http://localhost',
    'http://127.0.0.1',
    'https://levelupapp.ru',
    'https://*.levelupapp.ru',

    'https://m.vk.com',
    'https://tunnel.levoneapp.ru',

    'https://levonework.ru'
]

CORS_ALLOWED_ORIGINS = [
    'http://localhost',
    'http://127.0.0.1',
    'https://levelupapp.ru',
    'https://*.levelupapp.ru',

    'https://m.vk.com',
    'https://tunnel.levoneapp.ru',

    'https://levonework.ru'
]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]


# CORS_ALLOWED_ORIGINS=[
#     'http://localhost',
#     'http://127.0.0.1',
# 	'https://tunnel.levoneapp.ru',
# 	'https://levone.levoneapp.ru',
# ]

SHARED_APPS = [
	'django_tenants',
	'apps.shared.config.apps.ConfigConfig',
	'apps.shared.clients.apps.ClientsConfig',
	'apps.shared.guest.apps.GuestConfig',
    'apps.shared.users.apps.UsersConfig',

    'django.contrib.admin',
	'django.contrib.humanize',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
	
    'rest_framework',
    'corsheaders',
    'django_filters',
	'colorfield'
]


TENANT_APPS = [
	'django.contrib.contenttypes',
    'django.contrib.auth',
	'django.contrib.admin',

    'apps.tenant.staff.apps.StaffConfig',
    'apps.tenant.branch.apps.BranchConfig',
	'apps.tenant.catalog.apps.CatalogConfig',
	'apps.tenant.game.apps.GameConfig',
	'apps.tenant.inventory.apps.InventoryConfig',
	'apps.tenant.quest.apps.QuestConfig',
	'apps.tenant.stats.apps.StatsConfig',
	'apps.tenant.senler.apps.SenlerConfig',
	'apps.tenant.delivery.apps.DeliveryConfig'
]

INSTALLED_APPS = list(SHARED_APPS) + [app for app in TENANT_APPS if app not in SHARED_APPS]

MIDDLEWARE = [
	'corsheaders.middleware.CorsMiddleware',
	'django_tenants.middleware.main.TenantMainMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'main.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'main.wsgi.application'


DATABASES = {
    "default": {
        'ENGINE': 'django_tenants.postgresql_backend',
        "NAME": os.getenv("POSTGRES_DB"),
        "USER": os.getenv("POSTGRES_USER"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "HOST": os.getenv("POSTGRES_HOST"),
        "PORT": os.getenv("POSTGRES_PORT"),
    },
}

DATABASE_ROUTERS = (
    'django_tenants.routers.TenantSyncRouter',
)

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = os.getenv('LANGUAGE_CODE')

TIME_ZONE = os.getenv('TZ')

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
STATIC_ROOT = 'staticfiles/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]

DEFAULT_FILE_STORAGE = "django_tenants.files.storage.TenantFileSystemStorage"
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    )
}

TENANT_MODEL = 'clients.Company'
TENANT_DOMAIN_MODEL = 'clients.Domain'
AUTH_USER_MODEL = 'users.User'

VK_SECRET=os.getenv("VK_SECRET")

# Читаем из окружения, а если переменной нет — берем localhost (для локального запуска без докера)
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

ROOT_URLCONF = 'apps.shared.config.urls_tenants'
PUBLIC_SCHEMA_URLCONF = 'apps.shared.config.urls_public'

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
