SECRET_KEY = "testes"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "pci_auth",
]
AUTHENTICATION_BACKENDS = ["pci_auth.backends.AuthServiceBackend"]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
PCI_AUTH = {"AUTHSERVICE_URL": "http://authservice.teste"}
