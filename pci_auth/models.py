from django.conf import settings
from django.db import models


class PermissoesUsuario(models.Model):
    """
    Permissões do usuário nesta aplicação, como o AuthService mandou no último login.

    Regravado a cada login: mudança feita no AuthService vale a partir do próximo login.
    """

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="permissoes_pci", verbose_name="Usuário"
    )
    aplicacao = models.CharField("Aplicação", max_length=60, help_text="aud do token.")
    permissoes = models.JSONField("Permissões", default=list)
    escopo = models.JSONField(
        "Escopo", default=dict, help_text="{codigo: [nós]} das permissões limitadas a setores."
    )
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Permissões do usuário (AuthService)"
        verbose_name_plural = "Permissões dos usuários (AuthService)"

    def __str__(self):
        return f"{self.usuario} em {self.aplicacao}"
