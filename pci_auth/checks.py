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


def verificar_api_permissoes():
    """API_PERMISSOES só com ações conhecidas e, se o serviço declara PERMISSOES, códigos de lá."""
    mapa = conf.valor("API_PERMISSOES") or {}
    if not isinstance(mapa, dict):
        return [Warning("API_PERMISSOES deve ser um dict {model: {acao: codigo}}.", id="pci_auth.W008")]
    declaradas = conf.valor("PERMISSOES") or {}
    acoes = {"ler", "criar", "alterar", "apagar", "escrever"}
    problemas = []
    for model, regras in sorted(mapa.items()):
        if not isinstance(regras, dict):
            problemas.append(f"{model}: esperado {{acao: codigo}}")
            continue
        for acao, codigo in sorted(regras.items()):
            if acao not in acoes:
                problemas.append(f"{model}.{acao}: ação desconhecida (use {', '.join(sorted(acoes))})")
            elif codigo and declaradas and isinstance(declaradas, dict) and codigo not in declaradas:
                problemas.append(f"{model}.{acao}: '{codigo}' não está em PERMISSOES")
    if not problemas:
        return []
    return [Warning("API_PERMISSOES com problemas: " + "; ".join(problemas) + ".", id="pci_auth.W009")]


def verificar_auditoria():
    if not conf.valor("AUDITAR"):
        return []
    if "pci_auth.auditoria.AuditoriaMiddleware" in getattr(settings, "MIDDLEWARE", []):
        return []
    return [Warning(
        "AUDITAR ligado sem o AuditoriaMiddleware: as mudanças ficam sem usuário, IP e jti (como 'sistema') "
        "e os 403 da própria view não são registrados.",
        hint='Adicione "pci_auth.auditoria.AuditoriaMiddleware" ao MIDDLEWARE, depois do AuthenticationMiddleware.',
        id="pci_auth.W010",
    )]


def verificar_configuracao():
    avisos = verificar_api_permissoes() + verificar_auditoria()
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
