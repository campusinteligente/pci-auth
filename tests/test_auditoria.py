import importlib.util
from io import StringIO
from types import SimpleNamespace
from unittest import mock, skipUnless

import jwt
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import HttpResponse, HttpResponseForbidden
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from pci_auth.auditoria import AuditoriaMiddleware, marcar_token
from pci_auth.models import PermissoesUsuario, RegistroAuditoria as R
from pci_auth.permissoes import exige_permissao
from tests.models import Coisa

User = get_user_model()
LIGADA = {"AUDITAR": True, "AUDITAR_APPS": ["tests"], "AUDITORIA_IGNORAR_CAMPOS": ["segredo"], "EXIGIR_PERMISSOES": True}


def na_requisicao(view, user=None, caminho="/coisas/", metodo="get", sessao_token=None, **meta):
    """Roda `view` atrás do AuditoriaMiddleware, como o Django faria."""
    request = getattr(RequestFactory(), metodo)(caminho, **meta)
    request.user = user or AnonymousUser()
    request.session = SessionStore()
    if sessao_token:
        request.session["access_token"] = sessao_token

    def get_response(req):
        try:
            return view(req)
        except PermissionDenied:
            return HttpResponseForbidden()

    return AuditoriaMiddleware(get_response)(request)


class CheckTests(TestCase):
    @override_settings(PCI_AUTH=LIGADA, MIDDLEWARE=[])
    def test_avisa_sem_o_middleware(self):
        from pci_auth.checks import verificar_auditoria

        self.assertEqual([a.id for a in verificar_auditoria()], ["pci_auth.W010"])
        with self.settings(MIDDLEWARE=["pci_auth.auditoria.AuditoriaMiddleware"]):
            self.assertEqual(verificar_auditoria(), [])


class DesligadaTests(TestCase):
    def test_padrao_nao_grava_nada(self):
        Coisa.objects.create(nome="x")
        self.assertFalse(R.objects.exists())


@override_settings(PCI_AUTH=LIGADA)
class MudancasTests(TestCase):
    def setUp(self):
        self.maria = User.objects.create_user("maria")

    def test_criar_alterar_apagar_fora_de_requisicao(self):
        coisa = Coisa.objects.create(nome="Parafuso", preco="2.50", dono=self.maria, segredo="x")
        criado = R.objects.get()
        self.assertEqual((criado.acao, criado.modelo, criado.objeto_id), ("criado", "tests.coisa", str(coisa.pk)))
        self.assertEqual(criado.origem, "sistema")
        self.assertEqual(criado.mudancas, {"nome": [None, "Parafuso"], "preco": [None, "2.50"], "dono": [None, self.maria.pk]})

        coisa.preco = "3.00"
        coisa.segredo = "outro"  # ignorado
        coisa.save()
        alterado = R.objects.filter(acao="alterado").get()
        self.assertEqual(alterado.mudancas, {"preco": ["2.50", "3.00"]})

        coisa.save()  # nada mudou: não registra
        self.assertEqual(R.objects.filter(acao="alterado").count(), 1)

        pk = coisa.pk
        coisa.delete()
        excluido = R.objects.get(acao="excluido")
        self.assertEqual((excluido.objeto_id, excluido.objeto_repr), (str(pk), "Parafuso"))
        self.assertEqual(excluido.mudancas["nome"], ["Parafuso", None])

    def test_m2m(self):
        coisa = Coisa.objects.create(nome="x")
        g1, g2 = Group.objects.create(name="a"), Group.objects.create(name="b")
        coisa.grupos.add(g1, g2)
        coisa.grupos.remove(g1)
        regs = list(R.objects.filter(acao="alterado").order_by("pk").values_list("mudancas", flat=True))
        self.assertEqual(regs, [{"grupos": {"adicionados": sorted([str(g1.pk), str(g2.pk)])}},
                                {"grupos": {"removidos": [str(g1.pk)]}}])

    @override_settings(PCI_AUTH={**LIGADA, "AUDITAR_APPS": ["outro"]})
    def test_so_os_apps_auditados(self):
        Coisa.objects.create(nome="x")
        User.objects.create_user("joao")
        self.assertFalse(R.objects.exists())

    def test_falha_ao_gravar_nao_derruba_a_mudanca(self):
        with mock.patch.object(R.objects, "create", side_effect=RuntimeError("banco")):
            coisa = Coisa.objects.create(nome="x")
        self.assertTrue(Coisa.objects.filter(pk=coisa.pk).exists())

    def test_na_requisicao_quem_por_onde_e_jti_da_sessao(self):
        token = jwt.encode({"jti": "abc123", "user_id": "1"}, "x", algorithm="HS256")

        def view(request):
            Coisa.objects.create(nome="Pela tela")
            return HttpResponse("ok")

        resposta = na_requisicao(view, self.maria, sessao_token=token, HTTP_USER_AGENT="navegador/1",
                                 HTTP_X_FORWARDED_FOR="9.9.9.9, 10.0.0.5")
        reg = R.objects.get()
        self.assertEqual((reg.usuario, reg.username, reg.origem), (self.maria, "maria", "tela"))
        self.assertEqual((reg.metodo, reg.caminho, reg.ip, reg.user_agent), ("GET", "/coisas/", "10.0.0.5", "navegador/1"))
        self.assertEqual(reg.jti, "abc123")
        self.assertEqual(resposta["X-Requisicao-Id"], reg.requisicao)

    def test_bearer_usa_o_jti_do_token_e_origem_token(self):
        def view(request):
            marcar_token({"jti": "do-bearer"})
            Coisa.objects.create(nome="Pela API")
            return HttpResponse("ok")

        na_requisicao(view, self.maria, caminho="/api/x/", HTTP_AUTHORIZATION="Bearer abc")
        reg = R.objects.get()
        self.assertEqual((reg.origem, reg.jti), ("token", "do-bearer"))

    def test_origem_admin_e_api(self):
        def view(request):
            Coisa.objects.create(nome=request.path)
            return HttpResponse("ok")

        na_requisicao(view, self.maria, caminho="/admin/tests/coisa/add/", metodo="post")
        na_requisicao(view, self.maria, caminho="/api/gestao/coisa/", metodo="post")
        self.assertEqual(list(R.objects.order_by("pk").values_list("origem", flat=True)), ["admin", "api"])


@override_settings(PCI_AUTH=LIGADA)
class NegadoTests(TestCase):
    def setUp(self):
        self.maria = User.objects.create_user("maria")
        PermissoesUsuario.objects.create(usuario=self.maria, aplicacao="produtos", permissoes=[])

    def test_exige_permissao_registra_o_codigo_uma_vez(self):
        view = exige_permissao("produto.editar", "produto.ver")(lambda request: HttpResponse("ok"))
        self.assertEqual(na_requisicao(view, self.maria).status_code, 403)
        reg = R.objects.get()
        self.assertEqual((reg.acao, reg.permissao, reg.username), ("negado", "produto.editar, produto.ver", "maria"))

    def test_403_da_propria_view_registra_sem_codigo(self):
        na_requisicao(lambda request: HttpResponseForbidden(), self.maria)
        reg = R.objects.get()
        self.assertEqual((reg.acao, reg.permissao, reg.caminho), ("negado", "", "/coisas/"))

    def test_anonimo_nao_registra(self):
        na_requisicao(lambda request: HttpResponseForbidden())
        self.assertFalse(R.objects.exists())

    @skipUnless(importlib.util.find_spec("rest_framework"), "DRF não instalado")
    @override_settings(PCI_AUTH={**LIGADA, "API_PERMISSOES": {}})
    def test_api_por_modelo_registra_o_codigo(self):
        from pci_auth.drf import PermissaoPorModelo

        view = SimpleNamespace(get_model=lambda: SimpleNamespace(_meta=SimpleNamespace(model_name="produto")))

        def chamar(request):
            request.method = "DELETE"
            permitido = PermissaoPorModelo().has_permission(request, view)
            return HttpResponse() if permitido else HttpResponseForbidden()

        na_requisicao(chamar, self.maria, caminho="/api/x/produto/1/")
        self.assertEqual(R.objects.get().permissao, "api.produto.apagar")


@override_settings(PCI_AUTH=LIGADA)
class LimparTests(TestCase):
    def test_apaga_so_os_antigos(self):
        Coisa.objects.create(nome="novo")
        antigo = R.objects.create(acao="criado", origem="sistema")
        R.objects.filter(pk=antigo.pk).update(quando=timezone.now() - timezone.timedelta(days=400))
        saida = StringIO()
        call_command("limpar_auditoria", stdout=saida)
        self.assertIn("1 registro", saida.getvalue())
        self.assertEqual(R.objects.count(), 1)
