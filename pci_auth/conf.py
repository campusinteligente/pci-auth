"""
Configuração do pci-auth.

Tudo fica em `settings.PCI_AUTH` (um dict). Para trocar o `app/backends.py` copiado pelo pacote sem
mexer no resto do settings, os nomes antigos continuam valendo quando a chave não está no dict:

    AUTHSERVICE_URL       ← settings.AUTHSERVICE_URL
    REQUIRED_GROUP        ← settings.REQUIRED_GROUP
    PERMISSOES_POR_GRUPO  ← settings.GROUP_PERMISSIONS
    CHAVE_PUBLICA         ← settings.SIMPLE_JWT["VERIFYING_KEY"]
    CLIENT_ID, CLIENT_SECRET, TOKEN_REGISTRO ← variáveis de ambiente PCI_AUTH_<NOME>
"""

import os

from django.conf import settings

PADROES = {
    # AuthService
    "AUTHSERVICE_URL": "",
    "HOST": "localhost",  # cabeçalho Host nas chamadas (as cópias do backend sempre mandaram "localhost")
    "TIMEOUT": 10,
    "CHAVE_PUBLICA": None,  # PEM; sem ela o token não tem a assinatura conferida (veio direto do AuthService)
    # Credenciais da aplicação (vêm do .env)
    "CLIENT_ID": "",
    "CLIENT_SECRET": "",
    "TOKEN_REGISTRO": "",
    # O que a aplicação declara no auto-registro
    "SLUG": "",
    "NOME": "",
    "URL": "",
    "REPO": "",
    "PERMISSOES": {},  # {"movimentacao.registrar_saida": "Registrar saída de produto"}
    # Login
    "REQUIRED_GROUP": None,
    "PERMISSOES_POR_GRUPO": {},  # {"Servico_Gerente": "all", "Servico_Operador": ["view_x", ...]}
    "APP_LABELS": ["app"],
    "SALVAR_TOKEN_NA_SESSAO": True,
}

_LEGADO = {
    "AUTHSERVICE_URL": lambda: getattr(settings, "AUTHSERVICE_URL", None),
    "REQUIRED_GROUP": lambda: getattr(settings, "REQUIRED_GROUP", None),
    "PERMISSOES_POR_GRUPO": lambda: getattr(settings, "GROUP_PERMISSIONS", None),
    "CHAVE_PUBLICA": lambda: (getattr(settings, "SIMPLE_JWT", None) or {}).get("VERIFYING_KEY"),
    "CLIENT_ID": lambda: os.environ.get("PCI_AUTH_CLIENT_ID"),
    "CLIENT_SECRET": lambda: os.environ.get("PCI_AUTH_CLIENT_SECRET"),
    "TOKEN_REGISTRO": lambda: os.environ.get("PCI_AUTH_TOKEN_REGISTRO"),
}


def valor(nome):
    """Valor de uma chave: PCI_AUTH, depois o nome antigo, depois o padrão."""
    config = getattr(settings, "PCI_AUTH", None) or {}
    if nome in config:
        return config[nome]
    legado = _LEGADO.get(nome)
    if legado is not None:
        antigo = legado()
        if antigo is not None:
            return antigo
    return PADROES[nome]


def authservice_url():
    return (valor("AUTHSERVICE_URL") or "").rstrip("/")


def credenciais_cliente():
    """(client_id, client_secret) quando os dois estão configurados, senão None."""
    client_id, segredo = valor("CLIENT_ID"), valor("CLIENT_SECRET")
    if client_id and segredo:
        return client_id, segredo
    return None
