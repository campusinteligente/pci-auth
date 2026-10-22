"""Chamadas HTTP ao AuthService."""

import requests

from pci_auth import conf


class AuthServiceIndisponivel(Exception):
    """Sem conexão, timeout ou resposta que não é JSON."""


def post(caminho, corpo, cabecalhos=None):
    """POST em AUTHSERVICE_URL + caminho. Devolve (status, corpo JSON)."""
    url = conf.authservice_url()
    if not url:
        raise AuthServiceIndisponivel("AUTHSERVICE_URL não configurado.")
    cabecalhos = dict(cabecalhos or {})
    if conf.valor("HOST"):
        cabecalhos["Host"] = conf.valor("HOST")
    try:
        resposta = requests.post(f"{url}{caminho}", json=corpo, headers=cabecalhos, timeout=conf.valor("TIMEOUT"))
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
