"""
Backend de login pelo AuthService. Substitui o `app/backends.py` copiado nos serviços.

Fluxo:
1. POST {AUTHSERVICE_URL}/api/token/ com usuário e senha (e client_id/client_secret, se configurados)
2. Lê os claims do access (confere a assinatura RS256 quando há CHAVE_PUBLICA)
3. Exige REQUIRED_GROUP (superusuário sempre passa)
4. Cria ou atualiza o User local, sem senha usável
5. Sincroniza os grupos; grupo criado agora recebe as permissões de PERMISSOES_POR_GRUPO
"""

import logging

import jwt
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

from pci_auth import conf
from pci_auth.cliente import AuthServiceIndisponivel, post

logger = logging.getLogger(__name__)


def aplicar_permissoes_grupo(grupo):
    """Dá ao grupo recém-criado as permissões configuradas para o nome dele."""
    mapa = conf.valor("PERMISSOES_POR_GRUPO") or {}
    if grupo.name not in mapa:
        logger.debug("Grupo '%s' criado sem mapeamento de permissões: configure pelo admin.", grupo.name)
        return
    permissoes = Permission.objects.filter(content_type__app_label__in=conf.valor("APP_LABELS"))
    if mapa[grupo.name] != "all":
        permissoes = permissoes.filter(codename__in=mapa[grupo.name])
    grupo.permissions.set(permissoes)
    logger.info("Grupo '%s' criado: %d permissões aplicadas.", grupo.name, permissoes.count())


class AuthServiceBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        access = self.pedir_token(username, password)
        if access is None:
            return None
        claims = self.ler_claims(access)
        if claims is None or not claims.get("user_id"):
            return None
        if not self.pode_entrar(username, claims):
            return None
        if request is not None and hasattr(request, "session") and conf.valor("SALVAR_TOKEN_NA_SESSAO"):
            request.session["access_token"] = access
        return self.atualizar_usuario(username, claims)

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    # ------------------------------------------------------------------
    # Etapas (podem ser sobrescritas numa subclasse)
    # ------------------------------------------------------------------

    def pedir_token(self, username, password):
        """Access token do AuthService, ou None."""
        corpo = {"username": username, "password": password}
        credenciais = conf.credenciais_cliente()
        if credenciais:
            corpo["client_id"], corpo["client_secret"] = credenciais
        try:
            status, dados = post("/api/token/", corpo)
            if status == 401 and credenciais:
                # Credencial da aplicação errada não pode trancar o login de todo mundo enquanto o
                # client_id for opcional. Tenta sem ela e avisa alto se era mesmo ela o problema.
                corpo.pop("client_id"), corpo.pop("client_secret")
                status, dados = post("/api/token/", corpo)
                if status == 200:
                    logger.error(
                        "AuthService recusou o client_id '%s'; login feito sem identificar a aplicação. "
                        "Confira PCI_AUTH_CLIENT_ID e PCI_AUTH_CLIENT_SECRET.",
                        credenciais[0],
                    )
        except AuthServiceIndisponivel as e:
            logger.error("%s", e)
            return None
        if status != 200:
            logger.warning("AuthService respondeu %s para o usuário '%s'.", status, username)
            return None
        access = dados.get("access")
        if not access:
            logger.error("AuthService não devolveu o access token.")
        return access or None

    def ler_claims(self, access):
        chave = conf.valor("CHAVE_PUBLICA")
        try:
            if chave:
                return jwt.decode(access, chave, algorithms=["RS256"], options={"verify_aud": False})
            return jwt.decode(access, options={"verify_signature": False})
        except jwt.PyJWTError as e:
            logger.error("Token do AuthService inválido: %s", e)
            return None

    def pode_entrar(self, username, claims):
        grupo = conf.valor("REQUIRED_GROUP")
        if not grupo or claims.get("is_superuser"):
            return True
        if grupo in claims.get("groups", []):
            return True
        logger.warning("Usuário '%s' sem o grupo '%s'. Grupos: %s", username, grupo, claims.get("groups", []))
        return False

    def atualizar_usuario(self, username, claims):
        user, criado = get_user_model().objects.get_or_create(username=username)
        novos = {
            "email": claims.get("email", ""),
            "is_superuser": claims.get("is_superuser", False),
            "is_staff": claims.get("is_staff", False),
        }
        mudou = criado
        for campo, valor in novos.items():
            if getattr(user, campo) != valor:
                setattr(user, campo, valor)
                mudou = True
        if user.has_usable_password():
            user.set_unusable_password()
            mudou = True
        if mudou:
            user.save()

        grupos = []
        for nome in claims.get("groups", []):
            grupo, grupo_criado = Group.objects.get_or_create(name=nome)
            if grupo_criado:
                aplicar_permissoes_grupo(grupo)
            grupos.append(grupo)
        user.groups.set(grupos)
        return user
