"""
Rastreabilidade (0.5.0): quem criou, alterou ou apagou cada registro, com o antes e o depois de cada
campo, por onde (tela, API, token, admin), de onde (IP, aparelho) e com qual token (jti, o mesmo que o
AuthService guarda no login); e cada acesso negado, com a permissão que faltou.

Ligar no serviço:

    PCI_AUTH = {..., "AUDITAR": True}
    MIDDLEWARE = [..., "django.contrib.auth.middleware.AuthenticationMiddleware",
                  "pci_auth.auditoria.AuditoriaMiddleware", ...]

- Models auditados: os dos apps em AUDITAR_APPS (padrão: APP_LABELS, ["app"]).
- Campos ignorados: AUDITORIA_IGNORAR_CAMPOS (padrão: password). Textos longos são cortados.
- Fica fora: queryset.update(), bulk_create() e SQL direto (não disparam sinais do Django).
- O registro entra na mesma transação da mudança: se ela for desfeita, o registro também.
  Falha ao gravar o registro nunca derruba a requisição (vai para o log).
- Retenção: `manage.py limpar_auditoria` (AUDITORIA_DIAS, padrão 365).
"""

import contextvars
import datetime
import decimal
import ipaddress
import logging
import uuid

from django.db import transaction
from django.db.models.fields.files import FieldFile
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save

from pci_auth import conf

logger = logging.getLogger(__name__)

_contexto = contextvars.ContextVar("pci_auth_auditoria", default=None)
_ANTES = "_pci_auditoria_antes"
_LIMITE_TEXTO = 500


def ligada():
    return bool(conf.valor("AUDITAR"))


# ── Contexto da requisição ──────────────────────────────────────────────────

class AuditoriaMiddleware:
    """Guarda a requisição para os registros e anota 403 que ninguém registrou com a permissão."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ctx = {"request": request, "id": uuid.uuid4().hex, "jti": "", "negado": False}
        token = _contexto.set(ctx)
        try:
            response = self.get_response(request)
            if ligada():
                if response.status_code == 403 and not ctx["negado"] and _usuario(request) is not None:
                    registrar_negado()
                response["X-Requisicao-Id"] = ctx["id"]
            return response
        finally:
            _contexto.reset(token)


def marcar_token(claims):
    """Chamado ao autenticar um Bearer: o jti vai nos registros desta requisição."""
    ctx = _contexto.get()
    if ctx is not None and claims:
        ctx["jti"] = str(claims.get("jti") or "")[:64]


def _jti(ctx):
    if ctx["jti"]:
        return ctx["jti"]
    request = ctx["request"]
    sessao = getattr(request, "session", None)
    access = sessao.get("access_token") if sessao is not None else None
    if not access:
        return ""
    try:
        import jwt

        # Só para ligar ao login: o token foi conferido no login e veio do nosso próprio backend.
        return str(jwt.decode(access, options={"verify_signature": False}).get("jti") or "")[:64]
    except Exception:
        return ""


def _usuario(request):
    user = getattr(request, "user", None)
    return user if user is not None and getattr(user, "is_authenticated", False) else None


def _ip(request):
    # Último item: o que o nginx acrescentou; os anteriores vêm do cliente e podem ser forjados.
    encaminhado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = encaminhado.split(",")[-1].strip() or request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def _origem(request):
    from pci_auth.models import RegistroAuditoria as R

    if request.META.get("HTTP_AUTHORIZATION", "").startswith("Bearer "):
        return R.Origem.TOKEN
    caminho = request.path_info or ""
    if caminho.startswith("/admin/"):
        return R.Origem.ADMIN
    if "/api/" in caminho or caminho.startswith("/api"):
        return R.Origem.API
    return R.Origem.TELA


def _gravar(**campos):
    from pci_auth.models import RegistroAuditoria

    ctx = _contexto.get()
    if ctx is None:
        campos.update(origem=RegistroAuditoria.Origem.SISTEMA)
    else:
        request = ctx["request"]
        usuario = _usuario(request)
        campos.update(
            usuario=usuario,
            username=getattr(usuario, "username", "") if usuario else "",
            origem=_origem(request),
            metodo=request.method or "",
            caminho=(request.get_full_path() or "")[:300],
            ip=_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            jti=_jti(ctx),
            requisicao=ctx["id"],
        )
    try:
        with transaction.atomic():  # savepoint: falha aqui não estraga a transação da mudança
            RegistroAuditoria.objects.create(**campos)
    except Exception:
        logger.exception("pci_auth: não foi possível gravar o registro de auditoria %s", campos.get("acao"))


def registrar_negado(codigos=()):
    """Acesso negado (403) para o usuário da requisição atual; `codigos` = permissões exigidas."""
    ctx = _contexto.get()
    if not ligada() or ctx is None or ctx["negado"]:
        return
    ctx["negado"] = True
    from pci_auth.models import RegistroAuditoria

    _gravar(acao=RegistroAuditoria.Acao.NEGADO, permissao=", ".join(codigos)[:300])


# ── Mudanças nos dados ──────────────────────────────────────────────────────

def _auditavel(sender):
    from pci_auth.models import RegistroAuditoria

    if not ligada() or sender is RegistroAuditoria or sender._meta.proxy and sender._meta.concrete_model is RegistroAuditoria:
        return False
    apps_auditados = conf.valor("AUDITAR_APPS") or conf.valor("APP_LABELS") or []
    return sender._meta.app_label in apps_auditados


def _campos(model):
    ignorar = set(conf.valor("AUDITORIA_IGNORAR_CAMPOS") or ())
    return [f for f in model._meta.concrete_fields if f.name not in ignorar and not f.primary_key]


def _valor(v):
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, FieldFile):
        return v.name or None
    if isinstance(v, (decimal.Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, (datetime.date, datetime.time)):  # datetime é date
        return v.isoformat()
    if isinstance(v, (dict, list)):
        texto = str(v)
        return v if len(texto) <= _LIMITE_TEXTO else texto[:_LIMITE_TEXTO] + "…"
    texto = str(v)
    return texto if len(texto) <= _LIMITE_TEXTO else texto[:_LIMITE_TEXTO] + "…"


def _foto(instance):
    """{campo: valor} dos campos concretos (FK pelo id: attname)."""
    return {f.name: _valor(getattr(instance, f.attname)) for f in _campos(type(instance))}


def _repr(instance):
    try:
        return str(instance)[:200]
    except Exception:
        return ""


def _antes_de_salvar(sender, instance, raw=False, **kwargs):
    if raw or not _auditavel(sender) or instance._state.adding or instance.pk is None:
        return
    campos = _campos(sender)
    antigo = sender._base_manager.filter(pk=instance.pk).values(*[f.attname for f in campos]).first()
    if antigo is not None:
        setattr(instance, _ANTES, {f.name: _valor(antigo[f.attname]) for f in campos})


def _depois_de_salvar(sender, instance, created, raw=False, **kwargs):
    if raw or not _auditavel(sender):
        return
    from pci_auth.models import RegistroAuditoria

    depois = _foto(instance)
    antes = instance.__dict__.pop(_ANTES, None)
    if created or antes is None:
        acao = RegistroAuditoria.Acao.CRIADO
        mudancas = {c: [None, v] for c, v in depois.items() if v not in (None, "")}
    else:
        acao = RegistroAuditoria.Acao.ALTERADO
        mudancas = {c: [antes.get(c), v] for c, v in depois.items() if antes.get(c) != v}
        if not mudancas:
            return
    _gravar(acao=acao, modelo=sender._meta.label_lower, objeto_id=str(instance.pk), objeto_repr=_repr(instance),
            mudancas=mudancas)


def _depois_de_apagar(sender, instance, **kwargs):
    if not _auditavel(sender):
        return
    from pci_auth.models import RegistroAuditoria

    mudancas = {c: [v, None] for c, v in _foto(instance).items() if v not in (None, "")}
    _gravar(acao=RegistroAuditoria.Acao.EXCLUIDO, modelo=sender._meta.label_lower, objeto_id=str(instance.pk),
            objeto_repr=_repr(instance), mudancas=mudancas)


def _m2m(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear") or reverse:
        return
    dono = type(instance)
    if not _auditavel(dono):
        return
    campo = next((f.name for f in dono._meta.many_to_many if f.remote_field.through is sender), None)
    if campo is None:
        return
    from pci_auth.models import RegistroAuditoria

    chave = {"post_add": "adicionados", "post_remove": "removidos", "post_clear": "removidos"}[action]
    ids = sorted(str(pk) for pk in (pk_set or ())) if action != "post_clear" else ["todos"]
    _gravar(acao=RegistroAuditoria.Acao.ALTERADO, modelo=dono._meta.label_lower, objeto_id=str(instance.pk),
            objeto_repr=_repr(instance), mudancas={campo: {chave: ids}})


def conectar():
    """Chamado no AppConfig.ready(). Os sinais só agem com AUDITAR ligado."""
    pre_save.connect(_antes_de_salvar, dispatch_uid="pci_auth_auditoria_pre_save")
    post_save.connect(_depois_de_salvar, dispatch_uid="pci_auth_auditoria_post_save")
    post_delete.connect(_depois_de_apagar, dispatch_uid="pci_auth_auditoria_post_delete")
    m2m_changed.connect(_m2m, dispatch_uid="pci_auth_auditoria_m2m")
