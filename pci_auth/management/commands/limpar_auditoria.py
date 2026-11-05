from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from pci_auth import conf
from pci_auth.models import RegistroAuditoria


class Command(BaseCommand):
    help = "Apaga registros de auditoria mais antigos que PCI_AUTH['AUDITORIA_DIAS'] (padrão 365) ou --dias."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=None)

    def handle(self, *args, dias=None, **options):
        dias = dias if dias is not None else int(conf.valor("AUDITORIA_DIAS"))
        if dias < 1:
            self.stderr.write("--dias precisa ser 1 ou mais.")
            return
        apagados, _ = RegistroAuditoria.objects.filter(quando__lt=timezone.now() - timedelta(days=dias)).delete()
        self.stdout.write(f"pci-auth: {apagados} registro(s) de auditoria com mais de {dias} dias apagados.")
