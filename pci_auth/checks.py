"""
Checks do Django para a configuração do pci-auth.

Só avisos (Warning): um erro de check travaria `migrate` e `runserver`, e um serviço não pode parar
por causa da declaração de permissões. O comando `sincronizar_permissoes` recusa rodar com eles.
"""

import re

from django.conf import settings
from django.core.checks import Warning

from pci_auth import conf

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CODIGO_PERMISSAO = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def verificar_configuracao():
    avisos = []
    usa_backend = "pci_auth.backends.AuthServiceBackend" in getattr(settings, "AUTHENTICATION_BACKENDS", [])
    if usa_backend and not conf.authservice_url():
        avisos.append(Warning("AUTHSERVICE_URL não configurado: ninguém consegue entrar.", id="pci_auth.W001"))

    if bool(conf.valor("CLIENT_ID")) != bool(conf.valor("CLIENT_SECRET")):
        avisos.append(Warning("CLIENT_ID e CLIENT_SECRET vão juntos: um deles está vazio.", id="pci_auth.W002"))

    if not (conf.credenciais_cliente() or conf.valor("TOKEN_REGISTRO")):
        return avisos  # não vai registrar nem sincronizar: a declaração não é usada

    slug = conf.valor("SLUG")
    if not slug or len(slug) > 60 or not SLUG.match(slug):
        avisos.append(
            Warning(f"SLUG inválido ({slug!r}): use minúsculas, números e hífens, até 60.", id="pci_auth.W003")
        )
    if not conf.valor("NOME"):
        avisos.append(Warning("NOME vazio: o auto-registro exige um nome.", id="pci_auth.W004"))

    permissoes = conf.valor("PERMISSOES")
    if not isinstance(permissoes, dict):
        avisos.append(Warning("PERMISSOES deve ser um dict {codigo: descricao}.", id="pci_auth.W005"))
        return avisos
    invalidos = sorted(c for c in permissoes if not isinstance(c, str) or not CODIGO_PERMISSAO.match(c) or len(c) > 150)
    if invalidos:
        avisos.append(
            Warning(
                f"Códigos de permissão inválidos: {', '.join(map(str, invalidos))}. "
                "Use minúsculas, números, _ e pontos (ex.: movimentacao.registrar_saida).",
                id="pci_auth.W006",
            )
        )
    longas = sorted(c for c, d in permissoes.items() if d and len(d) > 255)
    if longas:
        avisos.append(Warning(f"Descrição com mais de 255 caracteres: {', '.join(longas)}.", id="pci_auth.W007"))
    return avisos


def checar(app_configs, **kwargs):
    return verificar_configuracao()
