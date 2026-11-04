"""
Checagem das permissões que o AuthService calculou (fase 2).

    from pci_auth.permissoes import pode, exige_permissao, ExigePermissaoMixin, permissao_drf

    @exige_permissao("movimentacao.registrar")
    def registrar(request): ...

    if pode(request.user, "produto.editar", no="setor_sub:7"): ...

Regras:
- Superusuário sempre pode (como no Django).
- Usuário sem registro (aplicação sem client_id, ou login antigo) não pode nada.
- Permissão com escopo vale só nos nós listados ("setor_super:1", "setor:3", "setor_sub:7").
  Sem `no`, basta valer em algum lugar.
- Sem o app `pci_auth` em INSTALLED_APPS (settings de dev com login local), só o superusuário passa.
- PCI_AUTH["EXIGIR_PERMISSOES"] = False: tudo liberado para qualquer usuário logado e ativo
  (implantação gradual: marque as views, atribua os papéis no AuthService, depois ligue).
"""

from functools import wraps

from django.apps import apps
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from pci_auth import conf

_CACHE = "_pci_auth_permissoes"
_SEM_REGISTRO = object()


def _registro(user):
    """PermissoesUsuario do usuário, guardado no objeto (uma consulta por requisição)."""
    if not hasattr(user, _CACHE):
        registro = None
        if apps.is_installed("pci_auth"):
            from pci_auth.models import PermissoesUsuario

            registro = PermissoesUsuario.objects.filter(usuario_id=user.pk).first()
        setattr(user, _CACHE, registro or _SEM_REGISTRO)
    registro = getattr(user, _CACHE)
    return None if registro is _SEM_REGISTRO else registro


def esquecer(user):
    """Descarta o que foi guardado no objeto (depois de regravar as permissões)."""
    if hasattr(user, _CACHE):
        delattr(user, _CACHE)


def escopo(user, codigo):
    """None = vale em tudo; set de nós = só neles; set vazio = não tem a permissão."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return set()
    if user.is_superuser or not conf.valor("EXIGIR_PERMISSOES"):
        return None
    registro = _registro(user)
    if registro is None or codigo not in registro.permissoes:
        return set()
    nos = (registro.escopo or {}).get(codigo)
    return None if nos is None else set(nos)


def pode(user, codigo, no=None):
    nos = escopo(user, codigo)
    if nos is None:
        return True
    return bool(nos) and (no is None or no in nos)


def pode_todas(user, codigos, no=None):
    return all(pode(user, codigo, no) for codigo in codigos)


def exige_permissao(*codigos):
    """Decorator de view: anônimo vai para o login; sem a permissão, 403. Exige todas."""
    if not codigos:
        raise ValueError("Informe ao menos um código de permissão.")

    def decorator(view):
        @wraps(view)
        def envolvida(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not pode_todas(request.user, codigos):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return envolvida

    return decorator


class ExigePermissaoMixin(AccessMixin):
    """Para class-based views: `permissao_exigida = "codigo"` ou uma tupla (exige todas)."""

    permissao_exigida = None

    def get_permissao_exigida(self):
        if not self.permissao_exigida:
            raise ValueError(f"{type(self).__name__} precisa de permissao_exigida.")
        if isinstance(self.permissao_exigida, str):
            return (self.permissao_exigida,)
        return tuple(self.permissao_exigida)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not pode_todas(request.user, self.get_permissao_exigida()):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


def permissao_drf(*codigos):
    """Classe de permissão do DRF: `permission_classes = [permissao_drf("produto.ver")]`."""
    if not codigos:
        raise ValueError("Informe ao menos um código de permissão.")
    from rest_framework.permissions import BasePermission

    class TemPermissao(BasePermission):
        def has_permission(self, request, view):
            return bool(request.user and request.user.is_authenticated and pode_todas(request.user, codigos))

    TemPermissao.__name__ = f"TemPermissao({', '.join(codigos)})"
    return TemPermissao
