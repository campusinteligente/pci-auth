from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.views import View
import importlib.util
from unittest import mock, skipUnless

from pci_auth.models import PermissoesUsuario
from pci_auth.permissoes import ExigePermissaoMixin, escopo, exige_permissao, pode, permissao_drf
from tests.utils import ErroConexao, access, resposta, simular_post

User = get_user_model()
TOKEN_APP = {"aud": "produtos", "permissoes": ["produto.ver", "movimentacao.registrar"],
             "permissoes_escopo": {"movimentacao.registrar": ["setor_sub:7"]}}


def entrar(token):
    with simular_post(resposta(200, {"access": token})):
        return authenticate(None, username="maria", password="senha")


class GuardarNoLoginTests(TestCase):
    def test_permissoes_do_token(self):
        user = entrar(access(**TOKEN_APP))
        registro = PermissoesUsuario.objects.get(usuario=user)
        self.assertEqual(registro.aplicacao, "produtos")
        self.assertEqual(registro.permissoes, ["produto.ver", "movimentacao.registrar"])
        self.assertEqual(registro.escopo, {"movimentacao.registrar": ["setor_sub:7"]})

    def test_novo_login_substitui(self):
        entrar(access(**TOKEN_APP))
        user = entrar(access(aud="produtos", permissoes=[], permissoes_escopo={}))
        self.assertEqual(PermissoesUsuario.objects.get(usuario=user).permissoes, [])
        self.assertFalse(pode(user, "produto.ver"))

    def test_sem_aud_apaga(self):
        entrar(access(**TOKEN_APP))
        entrar(access())
        self.assertFalse(PermissoesUsuario.objects.exists())

    def test_so_aud_busca_na_api(self):
        token = access(aud="produtos")
        dados = {"aplicacao": "produtos", "permissoes": ["produto.ver"], "permissoes_escopo": {}, "papeis": []}
        with simular_post(resposta(200, {"access": token})), \
                self.settings(PCI_AUTH={"AUTHSERVICE_URL": "http://authservice.teste"}), \
                mock.patch("pci_auth.cliente.requests.get", return_value=resposta(200, dados)) as get:
            user = authenticate(None, username="maria", password="senha")
        self.assertEqual(get.call_args.args[0], "http://authservice.teste/api/permissoes/me/")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], f"Bearer {token}")
        self.assertTrue(pode(user, "produto.ver"))

    def test_falha_na_api_deixa_sem_permissoes(self):
        entrar(access(**TOKEN_APP))
        for efeito in (resposta(500, {}), ErroConexao):
            with self.subTest(efeito=efeito), simular_post(resposta(200, {"access": access(aud="produtos")})), \
                    mock.patch("pci_auth.cliente.requests.get", side_effect=[efeito]), \
                    self.assertLogs("pci_auth", "ERROR"):
                user = authenticate(None, username="maria", password="senha")
            self.assertEqual(PermissoesUsuario.objects.get(usuario=user).permissoes, [])


class PodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("maria")
        PermissoesUsuario.objects.create(
            usuario=cls.user, aplicacao="produtos", permissoes=TOKEN_APP["permissoes"], escopo=TOKEN_APP["permissoes_escopo"]
        )
        cls.sem_registro = User.objects.create_user("joao")
        cls.super = User.objects.create_superuser("admin")

    def setUp(self):
        for u in (self.user, self.sem_registro, self.super):
            u.refresh_from_db()
            u.__dict__.pop("_pci_auth_permissoes", None)

    def test_regras(self):
        self.assertTrue(pode(self.user, "produto.ver"))
        self.assertTrue(pode(self.user, "produto.ver", no="setor_sub:1"))
        self.assertFalse(pode(self.user, "produto.editar"))
        self.assertTrue(pode(self.user, "movimentacao.registrar"))
        self.assertTrue(pode(self.user, "movimentacao.registrar", no="setor_sub:7"))
        self.assertFalse(pode(self.user, "movimentacao.registrar", no="setor_sub:8"))
        self.assertEqual(escopo(self.user, "movimentacao.registrar"), {"setor_sub:7"})
        self.assertIsNone(escopo(self.user, "produto.ver"))
        self.assertEqual(escopo(self.user, "produto.editar"), set())

    def test_sem_registro_anonimo_inativo_e_superusuario(self):
        self.assertFalse(pode(self.sem_registro, "produto.ver"))
        self.assertFalse(pode(AnonymousUser(), "produto.ver"))
        self.assertTrue(pode(self.super, "qualquer.coisa"))
        self.user.is_active = False
        self.assertFalse(pode(self.user, "produto.ver"))

    def test_uma_consulta_por_objeto(self):
        with self.assertNumQueries(1):
            pode(self.user, "produto.ver")
            pode(self.user, "produto.editar")

    @override_settings(INSTALLED_APPS=["django.contrib.auth", "django.contrib.contenttypes"])
    def test_sem_o_app_so_superusuario(self):
        self.assertFalse(pode(self.user, "produto.ver"))
        self.assertTrue(pode(self.super, "produto.ver"))

    def requisicao(self, user):
        request = RequestFactory().get("/tela/")
        request.user = user
        return request

    def test_decorator(self):
        @exige_permissao("produto.ver", "movimentacao.registrar")
        def tela(request):
            return HttpResponse("ok")

        self.assertEqual(tela(self.requisicao(self.user)).status_code, 200)
        with self.assertRaises(PermissionDenied):
            tela(self.requisicao(self.sem_registro))
        anonimo = tela(self.requisicao(AnonymousUser()))
        self.assertEqual(anonimo.status_code, 302)
        self.assertIn("next=/tela/", anonimo["Location"])
        with self.assertRaises(ValueError):
            exige_permissao()

    def test_mixin(self):
        class Tela(ExigePermissaoMixin, View):
            permissao_exigida = "produto.ver"

            def get(self, request):
                return HttpResponse("ok")

        self.assertEqual(Tela.as_view()(self.requisicao(self.user)).status_code, 200)
        with self.assertRaises(PermissionDenied):
            Tela.as_view()(self.requisicao(self.sem_registro))
        self.assertEqual(Tela.as_view()(self.requisicao(AnonymousUser())).status_code, 302)

    @skipUnless(importlib.util.find_spec("rest_framework"), "DRF não instalado")
    def test_drf(self):
        classe = permissao_drf("produto.ver")
        self.assertTrue(classe().has_permission(self.requisicao(self.user), None))
        self.assertFalse(classe().has_permission(self.requisicao(self.sem_registro), None))
        self.assertFalse(classe().has_permission(self.requisicao(AnonymousUser()), None))

    def test_filtro_de_template(self):
        template = Template('{% load pci_auth %}{% if u|pode:"produto.ver" %}sim{% endif %}{% if u|pode:"x.y" %}nao{% endif %}')
        self.assertEqual(template.render(Context({"u": self.user})), "sim")
