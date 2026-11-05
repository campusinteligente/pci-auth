from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


class Coisa(models.Model):
    """Model só dos testes da auditoria."""

    nome = models.CharField(max_length=100)
    preco = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    dono = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    segredo = models.CharField(max_length=50, blank=True)
    grupos = models.ManyToManyField(Group, blank=True)

    class Meta:
        app_label = "tests"

    def __str__(self):
        return self.nome
