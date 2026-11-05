"""Chamadas HTTP ao AuthService."""

from urllib.parse import quote

import requests

from pci_auth import conf


class AuthServiceIndisponivel(Exception):
    """Sem conexão, timeout ou resposta que não é JSON."""


def post(caminho, corpo, cabecalhos=None):
    """POST em AUTHSERVICE_URL + caminho. Devolve (status, corpo JSON)."""
    return _chamar("post", caminho, cabecalhos, json=corpo)


def get(caminho, cabecalhos=None):
    """GET em AUTHSERVICE_URL + caminho. Devolve (status, corpo JSON)."""
    return _chamar("get", caminho, cabecalhos)


def _chamar(metodo, caminho, cabecalhos, **kwargs):
    url = conf.authservice_url()
    if not url:
        raise AuthServiceIndisponivel("AUTHSERVICE_URL não configurado.")
    cabecalhos = dict(cabecalhos or {})
    if conf.valor("HOST"):
        cabecalhos["Host"] = conf.valor("HOST")
    try:
        resposta = getattr(requests, metodo)(
            f"{url}{caminho}", headers=cabecalhos, timeout=conf.valor("TIMEOUT"), **kwargs
        )
    except requests.RequestException as e:
        raise AuthServiceIndisponivel(f"Não foi possível falar com o AuthService em {url}: {e}") from e
    try:
        dados = resposta.json()
    except ValueError:
        dados = None
    if dados is None and resposta.status_code < 500:
        raise AuthServiceIndisponivel(f"AuthService respondeu {resposta.status_code} sem JSON em {caminho}.")
    return resposta.status_code, dados or {}


def declaracao():
    """O que a aplicação declara ao AuthService no registro e na sincronização."""
    corpo = {
        "url": conf.valor("URL") or "",
        "repo": conf.valor("REPO") or "",
        "grupo_exigido": conf.valor("REQUIRED_GROUP") or "",
        "permissoes": [
            {"codigo": codigo, "descricao": descricao or ""}
            for codigo, descricao in sorted((conf.valor("PERMISSOES") or {}).items())
        ],
    }
    if conf.valor("NOME"):
        corpo["nome"] = conf.valor("NOME")
    return corpo


def registrar(token):
    """Auto-registro: cria a aplicação pendente ou atualiza a pendente."""
    corpo = {"slug": conf.valor("SLUG"), **declaracao()}
    return post("/api/aplicacoes/registro/", corpo, {"Authorization": f"Registro {token}"})


def sincronizar(client_id, client_secret):
    """Sincroniza dados declarados e permissões de uma aplicação já aprovada."""
    corpo = {"client_id": client_id, "client_secret": client_secret, **declaracao()}
    return post("/api/aplicacoes/sincronizar/", corpo)


def minhas_permissoes(access, aplicacao=None):
    """
    GET /api/permissoes/me/ com o access do usuário. A aplicação vem do aud do token ou,
    num token sem aud (emitido sem client_id), de `aplicacao`.
    """
    caminho = "/api/permissoes/me/"
    if aplicacao:
        caminho += f"?aplicacao={quote(aplicacao)}"
    return get(caminho, {"Authorization": f"Bearer {access}"})
