"""
Permissões na API (Django REST Framework).

1. Bearer: `carregar_do_token(user, access, claims)` põe no `user` as permissões que o
   token dá NESTA aplicação, sem gravar nada (a requisição com Bearer não passa pelo login
   da web, que é quem grava PermissoesUsuario). Chame na classe de autenticação JWT do
   serviço, depois de achar o usuário:

       class AuthServiceJWTAuthentication(JWTAuthentication):
           def authenticate(self, request):
               resultado = super().authenticate(request)
               if resultado:
                   carregar_do_token(resultado[0], self.get_raw_token(self.get_header(request)), resultado[1].payload)
               return resultado

   - token com aud = SLUG e claims de permissão: usa os claims;
   - token com aud = SLUG sem os claims: GET /api/permissoes/me/;
   - token sem aud (emitido sem client_id, ex.: outro app que consome esta API):
     GET /api/permissoes/me/?aplicacao=SLUG;
   - token de outra aplicação: nenhuma permissão.
   A consulta ao AuthService fica em cache (django.core.cache) enquanto o token vale, até
   CACHE_PERMISSOES_TOKEN segundos. Com EXIGIR_PERMISSOES = False, não faz nada.

2. API dinâmica (modelo + ação → código): `PermissaoPorModelo`, para
   DEFAULT_PERMISSION_CLASSES (depois de IsAuthenticated). Só age em views com
   `get_model()` (a DynamicModelViewSet do template); nas outras, libera.

       PCI_AUTH["API_PERMISSOES"] = {
           "produto": {"ler": "produto.ver", "escrever": "produto.editar"},
           "solicitacaoproduto": {"ler": "solicitacao.ver", "criar": "solicitacao.criar",
                                  "alterar": "solicitacao.atender", "apagar": "solicitacao.atender"},
           "setorsub": {"ler": ""},          # "" = basta estar logado
       }

   Chave = model_name (minúsculas). Ações: ler (GET/HEAD/OPTIONS), criar (POST),
   alterar (PUT/PATCH), apagar (DELETE); "escrever" vale para as três últimas.
   Model ou ação fora do mapa = fechado: vira o código "api.<model>.<acao>", que nenhum
   papel tem (só o superusuário passa). Com EXIGIR_PERMISSOES = False, tudo liberado
   para quem está logado, como antes.
"""

import hashlib
import logging
import time

from django.core.cache import cache

from pci_auth import conf
from pci_auth.cliente import AuthServiceIndisponivel, minhas_permissoes
from pci_auth.permissoes import pode, usar_nesta_requisicao

logger = logging.getLogger(__name__)

ACOES = {"GET": "ler", "HEAD": "ler", "OPTIONS": "ler", "POST": "criar", "PUT": "alterar", "PATCH": "alterar",
         "DELETE": "apagar"}
_ESCREVER = ("criar", "alterar", "apagar")
_TEMPO_PADRAO = 300


# ── Bearer ──────────────────────────────────────────────────────────────────

def permissoes_do_token(access, claims):
    """(permissoes, escopo) que o token dá nesta aplicação."""
    slug = conf.valor("SLUG")
    aud = claims.get("aud")
    if aud:
        if slug and aud != slug:
            return [], {}
        if "permissoes" in claims:
            return claims.get("permissoes") or [], claims.get("permissoes_escopo") or {}
        return _consultar(access, claims, None)
    if not slug:
        logger.warning("Token sem aud e PCI_AUTH['SLUG'] vazio: sem como consultar as permissões.")
        return [], {}
    return _consultar(access, claims, slug)


def _consultar(access, claims, aplicacao):
    chave = "pci_auth:token:" + hashlib.sha256(access.encode()).hexdigest()
    guardado = cache.get(chave)
    if guardado is not None:
        return guardado
    try:
        status, dados = minhas_permissoes(access, aplicacao)
    except AuthServiceIndisponivel as e:
        logger.error("Permissões do token não carregadas: %s", e)
        return [], {}
    if status != 200:
        logger.error("AuthService respondeu %s em /api/permissoes/me/; token fica sem permissões.", status)
        return [], {}
    resultado = (dados.get("permissoes") or [], dados.get("permissoes_escopo") or {})
    restante = int(claims.get("exp", 0) - time.time())
    tempo = min(restante, int(conf.valor("CACHE_PERMISSOES_TOKEN") or _TEMPO_PADRAO))
    if tempo > 0:
        cache.set(chave, resultado, tempo)
    return resultado


def carregar_do_token(user, access, claims):
    """Põe em `user` (só nesta requisição) as permissões do token. Ver o topo do módulo."""
    if user is None or not getattr(user, "is_authenticated", False) or user.is_superuser:
        return
    if not conf.valor("EXIGIR_PERMISSOES"):
        return
    if isinstance(access, bytes):
        access = access.decode()
    permissoes, escopo = permissoes_do_token(access or "", claims or {})
    usar_nesta_requisicao(user, permissoes, escopo)


# ── API dinâmica ────────────────────────────────────────────────────────────

def codigo_da_api(model_name, metodo):
    """Código exigido para `metodo` no model; "" = basta login. Fora do mapa = "api.<model>.<acao>"."""
    acao = ACOES.get(metodo.upper())
    if acao is None:
        return f"api.{model_name}.desconhecida"
    regras = (conf.valor("API_PERMISSOES") or {}).get(model_name) or {}
    if acao in regras:
        return regras[acao]
    if acao in _ESCREVER and "escrever" in regras:
        return regras["escrever"]
    return f"api.{model_name}.{acao}"


def _model_name(view):
    obter = getattr(view, "get_model", None)
    if obter is None:
        return None
    try:
        return obter()._meta.model_name
    except Exception:
        return None  # model inexistente: a própria view responde 404


try:
    from rest_framework.permissions import BasePermission
except ImportError:  # DRF é opcional no pacote
    BasePermission = object


class PermissaoPorModelo(BasePermission):
    message = "Sem permissão para esta operação."

    def has_permission(self, request, view):
        model_name = _model_name(view)
        if model_name is None:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        codigo = codigo_da_api(model_name, request.method)
        return codigo == "" or pode(user, codigo)
