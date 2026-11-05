SECRET_KEY = "testes"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.admin",
    "django.contrib.messages",
    "pci_auth",
    "tests",  # Coisa, só para a auditoria
]
AUTHENTICATION_BACKENDS = ["pci_auth.backends.AuthServiceBackend"]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
PCI_AUTH = {"AUTHSERVICE_URL": "http://authservice.teste"}
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]},
}]
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "tests.urls"
