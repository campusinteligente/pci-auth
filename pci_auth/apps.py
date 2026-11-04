from django.apps import AppConfig
from django.core import checks


class PciAuthConfig(AppConfig):
    name = "pci_auth"
    default_auto_field = "django.db.models.AutoField"  # o da migration 0001; não depende do serviço
    verbose_name = "PCI Auth"

    def ready(self):
        from pci_auth.checks import checar

        checks.register(checar)
