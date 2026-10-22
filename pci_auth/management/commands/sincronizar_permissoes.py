"""
Registra a aplicação no AuthService e mantém as permissões declaradas em dia. Roda no deploy.

- Com CLIENT_ID e CLIENT_SECRET: sincroniza (permissão nova fica ativa, a que sumiu fica inativa).
- Sem eles, com TOKEN_REGISTRO: auto-registro; a aplicação fica pendente até alguém aprovar no admin
  do AuthService, que mostra o client_id e o segredo para ir no .env.
- Sem nenhum dos dois: não faz nada.

Falha sai com código 1; no entrypoint use `python manage.py sincronizar_permissoes || echo AVISO...`
para não derrubar o deploy por causa do AuthService.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from pci_auth import cliente, conf
from pci_auth.checks import verificar_configuracao


class Command(BaseCommand):
    help = "Registra a aplicação no AuthService ou sincroniza as permissões que ela declara."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mostrar", action="store_true", help="Só mostra o que seria enviado (sem credenciais) e sai."
        )

    def handle(self, *args, mostrar=False, **options):
        if mostrar:
            corpo = {"slug": conf.valor("SLUG"), **cliente.declaracao()}
            self.stdout.write(json.dumps(corpo, ensure_ascii=False, indent=2))
            return

        problemas = verificar_configuracao()
        if problemas:
            raise CommandError("Configuração do pci-auth com problema:\n" + "\n".join(f"- {p.msg}" for p in problemas))

        credenciais = conf.credenciais_cliente()
        token = conf.valor("TOKEN_REGISTRO")
        try:
            if credenciais:
                self._sincronizar(*credenciais)
            elif token:
                self._registrar(token)
            else:
                self.stdout.write(
                    "pci-auth: sem PCI_AUTH_CLIENT_ID/SECRET nem PCI_AUTH_TOKEN_REGISTRO; nada a fazer."
                )
        except cliente.AuthServiceIndisponivel as e:
            raise CommandError(str(e))

    def _sincronizar(self, client_id, client_secret):
        status, dados = cliente.sincronizar(client_id, client_secret)
        if status in (401, 403):
            raise CommandError(
                f"AuthService recusou o client_id '{client_id}' ({status}): segredo errado, cliente "
                "desativado ou aplicação desligada no admin."
            )
        self._exigir_ok(status, dados)
        resumo = ", ".join(f"{k}: {len(dados.get(k, []))}" for k in ("criadas", "reativadas", "desativadas"))
        self.stdout.write(self.style.SUCCESS(f"pci-auth: permissões sincronizadas ({resumo})."))
        for chave in ("criadas", "reativadas", "desativadas"):
            for codigo in dados.get(chave, []):
                self.stdout.write(f"  {chave[:-1]}: {codigo}")

    def _registrar(self, token):
        status, dados = cliente.registrar(token)
        if status == 401:
            raise CommandError("AuthService recusou o token de registro (PCI_AUTH_TOKEN_REGISTRO).")
        if status == 409:
            raise CommandError(
                f"A aplicação '{conf.valor('SLUG')}' já foi aprovada ou recusada no AuthService. "
                "Se aprovada, coloque PCI_AUTH_CLIENT_ID e PCI_AUTH_CLIENT_SECRET no .env."
            )
        self._exigir_ok(status, dados)
        acao = "registrada" if status == 201 else "atualizada"
        self.stdout.write(
            self.style.SUCCESS(f"pci-auth: aplicação '{dados.get('slug')}' {acao}, aguardando aprovação no AuthService.")
        )

    def _exigir_ok(self, status, dados):
        if status not in (200, 201):
            raise CommandError(f"AuthService respondeu {status}: {json.dumps(dados, ensure_ascii=False)}")
