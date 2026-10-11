from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

environ.Env.read_env(BASE_DIR / '.env', overwrite=False)

SECRET_KEY = env('SECRET_KEY')   # No default — server refuses to start without it

DEBUG = env('DEBUG')

_raw_hosts = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '[::1]'])
ALLOWED_HOSTS = _raw_hosts

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'csp',
    'users',
    'public_website',
    'dashboard',
    'api',
    'identities',
    'reports',
    'verification',
    'core',
    'notifications',
    'payments',
    'django_otp',
    'django_otp.plugins.otp_totp',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
     # 'csp.middleware.CSPMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.site_configuration',
                'notifications.context_processors.unread_notification_count',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': env.db('DATABASE_URL')
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

AUTH_USER_MODEL = 'users.User'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'



LOGIN_URL = 'users:login'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = 'users:login'


# Cloudinary / Evidence Storage Configuration
CLOUDINARY_CLOUD_NAME = env('CLOUDINARY_CLOUD_NAME', default='')
CLOUDINARY_API_KEY = env('CLOUDINARY_API_KEY', default='')
CLOUDINARY_API_SECRET = env('CLOUDINARY_API_SECRET', default='')
EVIDENCE_STORAGE_PROVIDER = env('EVIDENCE_STORAGE_PROVIDER', default='reports.storage_services.CloudinaryEvidenceStorage')

IDENTIFIER_HASH_PEPPER = env('IDENTIFIER_HASH_PEPPER', default='')


# Media configuration (Development)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ==============================================================================
# Redis Caching & Rate Limiting Configuration (Phase 6, Batch 6.1)
# ==============================================================================
REDIS_URL = env('REDIS_URL', default='redis://localhost:6379/0')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
        'KEY_PREFIX': 'verifyng',
        'TIMEOUT': 300,
    }
}

PUBLIC_CHECK_RATE_LIMIT = env.int('PUBLIC_CHECK_RATE_LIMIT', default=30)
PUBLIC_CHECK_RATE_LIMIT_WINDOW = env.int('PUBLIC_CHECK_RATE_LIMIT_WINDOW', default=60)
SECURE_PROXY_TRUSTED_IPS = env.list('SECURE_PROXY_TRUSTED_IPS', default=[])

# ==============================================================================
# Celery Configuration (Phase 6, Batch 6.2)
# ==============================================================================
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default=REDIS_URL)
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = env.bool('CELERY_TASK_ALWAYS_EAGER', default=False)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 1800 seconds (30 minutes hard limit)


# ==============================================================================
# Notifications App (Phase 11)
# ==============================================================================

# Add 'notifications' to INSTALLED_APPS list (add alongside 'core'):
# 'notifications',

# Add to TEMPLATES context_processors list:
# 'notifications.context_processors.unread_notification_count',
# ==============================================================================
# Notifications App (Phase 11) — Email Gate Configuration
# ==============================================================================

# --- Gate 1: Mailtrap Transactional Sending API (HTTPS/443) ---
MAILTRAP_API_TOKEN = env('MAILTRAP_API_TOKEN', default='')
MAILTRAP_SENDING_EMAIL = env('MAILTRAP_SENDING_EMAIL', default='noreply@mailserver.sendmoor.com')
MAILTRAP_FROM_NAME = env('MAILTRAP_FROM_NAME', default='VerifyNG')


# --- Gate 2: Namecheap Private Email SMTP (port 465 SSL) ---
NAMECHEAP_SMTP_HOST = env('NAMECHEAP_SMTP_HOST', default='mail.privateemail.com')
NAMECHEAP_SMTP_PORT = env.int('NAMECHEAP_SMTP_PORT', default=465)
NAMECHEAP_SMTP_USER = env('NAMECHEAP_SMTP_USER', default='')
NAMECHEAP_SMTP_PASSWORD = env('NAMECHEAP_SMTP_PASS', default='')
NAMECHEAP_FROM_EMAIL = env('NAMECHEAP_FROM_EMAIL', default='')
NAMECHEAP_FROM_NAME = env('NAMECHEAP_FROM_NAME', default='VerifyNG')

# --- Gate 3: Gmail SMTP (port 587 STARTTLS) ---
GMAIL_SMTP_USER = env('GMAIL_SMTP_USER', default='')
GMAIL_SMTP_APP_PASSWORD = env('GMAIL_SMTP_APP_PASSWORD', default='')
GMAIL_FROM_NAME = env('GMAIL_FROM_NAME', default='VerifyNG')

# Route all Django outbound mail through the three-gate VerifyNG service
EMAIL_BACKEND = 'notifications.django_email_backend.VerifyNGEmailBackend'
DEFAULT_FROM_EMAIL = env('MAILTRAP_FROM_EMAIL', default='noreply@verifyng.com')


# ==============================================================================
# Payments & Subscriptions (Phase 12) — Paystack Configuration
# ==============================================================================
PAYSTACK_SECRET_KEY = env('PAYSTACK_SECRET_KEY', default='')
PAYSTACK_PUBLIC_KEY = env('PAYSTACK_PUBLIC_KEY', default='')

# Full base URL used to build Paystack callback URLs.
# Override in production: SITE_BASE_URL=https://verifyng.com
SITE_BASE_URL = env('SITE_BASE_URL', default='http://localhost:8000')


# ==============================================================================
# Security Headers (Phase 13) — active in production (DEBUG=False)
# ==============================================================================
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=not DEBUG)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if not DEBUG else None
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 60 * 60 * 8
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_BROWSER_XSS_FILTER = True




# ==============================================================================
# Content Security Policy (Phase 13) — django-csp 4.0
# ==============================================================================
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "script-src": [
            "'self'",
            "https://cdn.jsdelivr.net",
            "https://cdnjs.cloudflare.com",
        ],
        "style-src": [
            "'self'",
            "https://cdn.jsdelivr.net",
            "https://cdnjs.cloudflare.com",
            "https://fonts.googleapis.com",
        ],
        "font-src": [
            "'self'",
            "https://fonts.gstatic.com",
        ],
        "img-src": [
            "'self'",
            "data:",
            "https://res.cloudinary.com",
        ],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
        "default-src": ["'self'"],
        "connect-src": [
            "'self'",
            "https://api.paystack.co",
            "https://js.paystack.co",
        ],
    },
    "REPORT_ONLY": env.bool('CSP_REPORT_ONLY', default=True),
}

# ==============================================================================
# Logging Configuration
# ==============================================================================
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'notifications': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}


