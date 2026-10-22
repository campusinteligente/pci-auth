from django.apps import AppConfig
from django.core import checks


class PciAuthConfig(AppConfig):
    name = "pci_auth"
    verbose_name = "PCI Auth"

    def ready(self):
        from pci_auth.checks import checar

        checks.register(checar)
