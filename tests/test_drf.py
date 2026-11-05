import importlib.util
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.checks import Warning
from django.test import RequestFactory, TestCase, override_settings

from pci_auth.checks import verificar_api_permissoes
from pci_auth.drf import PermissaoPorModelo, carregar_do_token, codigo_da_api, permissoes_do_token
from pci_auth.models import PermissoesUsuario
from pci_auth.permissoes import pode
from tests.utils import ErroConexao, resposta

User = get_user_model()
GET = "pci_auth.cliente.requests.get"
CONF = {"AUTHSERVICE_URL": "http://authservice.teste", "SLUG": "produtos", "EXIGIR_PERMISSOES": True}
MAPA = {
    "produto": {"ler": "produto.ver", "escrever": "produto.editar"},
    "solicitacao": {"ler": "solicitacao.ver", "criar": "solicitacao.criar", "apagar": "solicitacao.atender"},
    "setor": {"ler": ""},
}


def exp(segundos=600):
    import time
    return int(time.time()) + segundos


@override_settings(PCI_AUTH=CONF)
class PermissoesDoTokenTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_aud_desta_aplicacao_com_claims(self):
        claims = {"aud": "produtos", "permissoes": ["produto.ver"], "permissoes_escopo": {"produto.ver": ["setor:3"]}}
        with mock.patch(GET) as get:
            self.assertEqual(permissoes_do_token("tok", claims), (["produto.ver"], {"produto.ver": ["setor:3"]}))
        get.assert_not_called()

    def test_aud_de_outra_aplicacao_nao_da_nada(self):
        with mock.patch(GET) as get:
            self.assertEqual(permissoes_do_token("tok", {"aud": "motoristas", "permissoes": ["produto.ver"]}), ([], {}))
        get.assert_not_called()

    def test_sem_aud_consulta_pelo_slug_e_guarda_em_cache(self):
        dados = {"permissoes": ["produto.ver"], "permissoes_escopo": {}}
        with mock.patch(GET, return_value=resposta(200, dados)) as get:
            self.assertEqual(permissoes_do_token("tok", {"exp": exp()}), (["produto.ver"], {}))
            self.assertEqual(permissoes_do_token("tok", {"exp": exp()}), (["produto.ver"], {}))
        get.assert_called_once()
        self.assertTrue(get.call_args.args[0].endswith("/api/permissoes/me/?aplicacao=produtos"))
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    def test_aud_sem_claims_consulta_sem_parametro(self):
        with mock.patch(GET, return_value=resposta(200, {"permissoes": ["produto.ver"]})) as get:
            self.assertEqual(permissoes_do_token("tok2", {"aud": "produtos", "exp": exp()}), (["produto.ver"], {}))
        self.assertTrue(get.call_args.args[0].endswith("/api/permissoes/me/"))

    def test_falha_no_authservice_nao_da_nada_e_nao_guarda(self):
        with mock.patch(GET, side_effect=[ErroConexao, resposta(403, {"detail": "x"}), resposta(200, {"permissoes": ["a.b"]})]):
            self.assertEqual(permissoes_do_token("tok3", {"exp": exp()}), ([], {}))
            self.assertEqual(permissoes_do_token("tok3", {"exp": exp()}), ([], {}))
            self.assertEqual(permissoes_do_token("tok3", {"exp": exp()}), (["a.b"], {}))

    @override_settings(PCI_AUTH={**CONF, "SLUG": ""})
    def test_sem_aud_e_sem_slug_nao_da_nada(self):
        with mock.patch(GET) as get:
            self.assertEqual(permissoes_do_token("tok", {}), ([], {}))
        get.assert_not_called()


@override_settings(PCI_AUTH=CONF)
class CarregarDoTokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("maria")
        # Permissões antigas do login pela web: o Bearer não usa nem mexe nelas.
        PermissoesUsuario.objects.create(usuario=self.user, aplicacao="produtos", permissoes=["produto.editar"])

    def test_vale_so_o_token_e_nada_e_gravado(self):
        carregar_do_token(self.user, b"tok", {"aud": "produtos", "permissoes": ["produto.ver"]})
        self.assertTrue(pode(self.user, "produto.ver"))
        self.assertFalse(pode(self.user, "produto.editar"))
        self.assertEqual(PermissoesUsuario.objects.get(usuario=self.user).permissoes, ["produto.editar"])

    @override_settings(PCI_AUTH={**CONF, "EXIGIR_PERMISSOES": False})
    def test_exigencia_desligada_nao_consulta(self):
        with mock.patch(GET) as get:
            carregar_do_token(self.user, "tok", {"exp": exp()})
        get.assert_not_called()
        self.assertTrue(pode(self.user, "qualquer.coisa"))


class CodigoDaApiTests(TestCase):
    @override_settings(PCI_AUTH={"API_PERMISSOES": MAPA})
    def test_mapa(self):
        self.assertEqual(codigo_da_api("produto", "GET"), "produto.ver")
        self.assertEqual(codigo_da_api("produto", "HEAD"), "produto.ver")
        for metodo in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(codigo_da_api("produto", metodo), "produto.editar")
        self.assertEqual(codigo_da_api("solicitacao", "POST"), "solicitacao.criar")
        self.assertEqual(codigo_da_api("solicitacao", "PATCH"), "api.solicitacao.alterar")  # ação fora do mapa
        self.assertEqual(codigo_da_api("solicitacao", "DELETE"), "solicitacao.atender")
        self.assertEqual(codigo_da_api("setor", "GET"), "")
        self.assertEqual(codigo_da_api("setor", "POST"), "api.setor.criar")
        self.assertEqual(codigo_da_api("perfil", "GET"), "api.perfil.ler")  # model fora do mapa

    @override_settings(PCI_AUTH={"API_PERMISSOES": MAPA, "PERMISSOES": {"produto.ver": "", "produto.editar": ""}})
    def test_check_aponta_codigos_nao_declarados_e_acoes_erradas(self):
        avisos = verificar_api_permissoes()
        self.assertEqual(len(avisos), 1)
        self.assertIsInstance(avisos[0], Warning)
        self.assertIn("solicitacao.criar: 'solicitacao.criar' não está em PERMISSOES", avisos[0].msg)
        self.assertNotIn("setor", avisos[0].msg)  # "" = só login

    @override_settings(PCI_AUTH={"API_PERMISSOES": MAPA})
    def test_check_sem_permissoes_declaradas_nao_compara_codigos(self):
        self.assertEqual(verificar_api_permissoes(), [])  # ex.: settings de dev

    @override_settings(PCI_AUTH={"API_PERMISSOES": {"produto": {"listar": "produto.ver"}}})
    def test_check_acao_desconhecida(self):
        self.assertIn("ação desconhecida", verificar_api_permissoes()[0].msg)


@skipUnless(importlib.util.find_spec("rest_framework"), "DRF não instalado")
@override_settings(PCI_AUTH={**CONF, "API_PERMISSOES": MAPA})
class PermissaoPorModeloTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("maria")
        PermissoesUsuario.objects.create(usuario=self.user, aplicacao="produtos", permissoes=["produto.ver"])
        self.permissao = PermissaoPorModelo()

    def view(self, model_name):
        return SimpleNamespace(get_model=lambda: SimpleNamespace(_meta=SimpleNamespace(model_name=model_name)))

    def pode(self, metodo, model_name, user=None):
        request = getattr(RequestFactory(), metodo.lower())("/")
        request.user = user or self.user
        return self.permissao.has_permission(request, self.view(model_name))

    def test_por_model_e_acao(self):
        self.assertTrue(self.pode("GET", "produto"))
        self.assertFalse(self.pode("POST", "produto"))
        self.assertFalse(self.pode("DELETE", "produto"))
        self.assertTrue(self.pode("GET", "setor"))  # "" = só login
        self.assertFalse(self.pode("GET", "perfil"))  # fora do mapa = fechado

    def test_superusuario_e_anonimo(self):
        admin = User.objects.create_superuser("admin", password="x")
        self.assertTrue(self.pode("DELETE", "perfil", admin))
        self.assertFalse(self.pode("GET", "setor", AnonymousUser()))

    @override_settings(PCI_AUTH={**CONF, "API_PERMISSOES": MAPA, "EXIGIR_PERMISSOES": False})
    def test_exigencia_desligada_libera_quem_esta_logado(self):
        self.assertTrue(self.pode("DELETE", "perfil"))
        self.assertFalse(self.pode("GET", "perfil", AnonymousUser()))

    def test_view_sem_get_model_ou_model_inexistente_libera(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        self.assertTrue(self.permissao.has_permission(request, SimpleNamespace()))

        def quebra():
            raise LookupError("não existe")

        self.assertTrue(self.permissao.has_permission(request, SimpleNamespace(get_model=quebra)))
