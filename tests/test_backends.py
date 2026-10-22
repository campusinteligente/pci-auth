from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.sessions.backends.db import SessionStore

from tests.utils import OUTRA_PRIVADA, PUBLICA, ErroConexao, access, resposta, simular_post

User = get_user_model()
URL = "http://authservice.teste"


def entrar(**kwargs):
    return authenticate(None, username="maria", password="senha", **kwargs)


class LoginTests(TestCase):
    def test_cria_usuario_local_com_claims_e_sem_senha(self):
        token = access(email="m@if.edu.br", is_staff=True, groups=["Produtos"])
        with simular_post(resposta(200, {"access": token, "refresh": "r"})) as post:
            user = entrar()

        self.assertEqual(user.username, "maria")
        self.assertEqual(user.email, "m@if.edu.br")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Produtos"])
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{URL}/api/token/")
        self.assertEqual(kwargs["json"], {"username": "maria", "password": "senha"})
        self.assertEqual(kwargs["headers"], {"Host": "localhost"})

    def test_atualiza_usuario_existente_e_tira_grupos_removidos(self):
        user = User.objects.create_user("maria", password="local", is_staff=True)
        user.groups.add(Group.objects.create(name="Antigo"))
        with simular_post(resposta(200, {"access": access(groups=["Novo"])})):
            entrar()

        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Novo"])

    def test_sem_usuario_ou_senha_nem_chama_o_authservice(self):
        with simular_post() as post:
            self.assertIsNone(authenticate(None, username="maria", password=""))
        post.assert_not_called()

    def test_credenciais_erradas(self):
        with simular_post(resposta(401, {"detail": "No active account"})):
            self.assertIsNone(entrar())
        self.assertFalse(User.objects.exists())

    def test_authservice_fora_do_ar(self):
        with simular_post(ErroConexao), self.assertLogs("pci_auth", "ERROR"):
            self.assertIsNone(entrar())

    def test_resposta_sem_json(self):
        with simular_post(resposta(502, sem_json=True)):
            self.assertIsNone(entrar())

    def test_sem_access_na_resposta(self):
        with simular_post(resposta(200, {"refresh": "r"})), self.assertLogs("pci_auth", "ERROR"):
            self.assertIsNone(entrar())

    def test_token_sem_user_id(self):
        with simular_post(resposta(200, {"access": access(user_id=None)})):
            self.assertIsNone(entrar())

    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": ""})
    def test_sem_url_configurada(self):
        with simular_post() as post, self.assertLogs("pci_auth", "ERROR"):
            self.assertIsNone(entrar())
        post.assert_not_called()

    def test_salva_access_na_sessao(self):
        request = RequestFactory().post("/login/")
        request.session = SessionStore()
        token = access()
        with simular_post(resposta(200, {"access": token})):
            authenticate(request, username="maria", password="senha")
        self.assertEqual(request.session["access_token"], token)


class GrupoExigidoTests(TestCase):
    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL, "REQUIRED_GROUP": "Produtos"})
    def test_sem_o_grupo_nao_entra(self):
        with simular_post(resposta(200, {"access": access(groups=["Outro"])})):
            self.assertIsNone(entrar())
        self.assertFalse(User.objects.exists())

    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL, "REQUIRED_GROUP": "Produtos"})
    def test_com_o_grupo_entra(self):
        with simular_post(resposta(200, {"access": access(groups=["Produtos"])})):
            self.assertIsNotNone(entrar())

    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL, "REQUIRED_GROUP": "Produtos"})
    def test_superusuario_entra_sem_o_grupo(self):
        with simular_post(resposta(200, {"access": access(is_superuser=True)})):
            self.assertTrue(entrar().is_superuser)


class AssinaturaTests(TestCase):
    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL, "CHAVE_PUBLICA": PUBLICA})
    def test_assinatura_valida(self):
        with simular_post(resposta(200, {"access": access()})):
            self.assertIsNotNone(entrar())

    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL, "CHAVE_PUBLICA": PUBLICA})
    def test_assinatura_de_outra_chave_e_recusada(self):
        with simular_post(resposta(200, {"access": access(chave=OUTRA_PRIVADA)})), self.assertLogs("pci_auth", "ERROR"):
            self.assertIsNone(entrar())

    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL, "CHAVE_PUBLICA": PUBLICA})
    def test_claim_aud_nao_atrapalha(self):
        # Fase 2: o token de uma aplicação identificada vem com aud = slug.
        with simular_post(resposta(200, {"access": access(aud="produtos")})):
            self.assertIsNotNone(entrar())

    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL}, SIMPLE_JWT={"VERIFYING_KEY": PUBLICA})
    def test_usa_a_chave_do_simple_jwt(self):
        with simular_post(resposta(200, {"access": access(chave=OUTRA_PRIVADA)})), self.assertLogs("pci_auth", "ERROR"):
            self.assertIsNone(entrar())


class ClienteTests(TestCase):
    CONFIG = {"AUTHSERVICE_URL": URL, "CLIENT_ID": "pci_abc", "CLIENT_SECRET": "segredo"}

    @override_settings(PCI_AUTH=CONFIG)
    def test_manda_client_id_e_secret(self):
        with simular_post(resposta(200, {"access": access()})) as post:
            entrar()
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"username": "maria", "password": "senha", "client_id": "pci_abc", "client_secret": "segredo"},
        )

    @override_settings(PCI_AUTH=CONFIG)
    def test_cliente_recusado_tenta_sem_ele_e_avisa(self):
        respostas = [resposta(401, {"detail": "Credenciais da aplicação inválidas."}), resposta(200, {"access": access()})]
        with simular_post(*respostas) as post, self.assertLogs("pci_auth", "ERROR") as logs:
            self.assertIsNotNone(entrar())
        self.assertEqual(post.call_args.kwargs["json"], {"username": "maria", "password": "senha"})
        self.assertIn("pci_abc", logs.output[0])

    @override_settings(PCI_AUTH=CONFIG)
    def test_senha_errada_com_cliente_continua_recusada(self):
        with simular_post(resposta(401, {}), resposta(401, {})):
            self.assertIsNone(entrar())

    @override_settings(PCI_AUTH={"AUTHSERVICE_URL": URL, "CLIENT_ID": "pci_abc"})
    def test_so_client_id_sem_secret_nao_manda_nada(self):
        with simular_post(resposta(200, {"access": access()})) as post:
            entrar()
        self.assertNotIn("client_id", post.call_args.kwargs["json"])


class PermissoesPorGrupoTests(TestCase):
    def _entrar_com(self, grupos, mapa):
        config = {"AUTHSERVICE_URL": URL, "APP_LABELS": ["auth"], "PERMISSOES_POR_GRUPO": mapa}
        with override_settings(PCI_AUTH=config), simular_post(resposta(200, {"access": access(groups=grupos)})):
            return entrar()

    def test_all_da_todas_as_permissoes_dos_app_labels(self):
        self._entrar_com(["Gerente"], {"Gerente": "all"})
        grupo = Group.objects.get(name="Gerente")
        self.assertEqual(grupo.permissions.count(), Permission.objects.filter(content_type__app_label="auth").count())

    def test_lista_da_so_as_listadas(self):
        self._entrar_com(["Leitor"], {"Leitor": ["view_user", "view_group"]})
        codigos = set(Group.objects.get(name="Leitor").permissions.values_list("codename", flat=True))
        self.assertEqual(codigos, {"view_user", "view_group"})

    def test_grupo_ja_existente_nao_e_mexido(self):
        Group.objects.create(name="Gerente")
        self._entrar_com(["Gerente"], {"Gerente": "all"})
        self.assertEqual(Group.objects.get(name="Gerente").permissions.count(), 0)

    def test_grupo_sem_mapeamento_fica_sem_permissoes(self):
        self._entrar_com(["Outro"], {"Gerente": "all"})
        self.assertEqual(Group.objects.get(name="Outro").permissions.count(), 0)

    @override_settings(GROUP_PERMISSIONS={"Leitor": ["view_user"]}, PCI_AUTH={"AUTHSERVICE_URL": URL, "APP_LABELS": ["auth"]})
    def test_nome_antigo_group_permissions_vale(self):
        with simular_post(resposta(200, {"access": access(groups=["Leitor"])})):
            entrar()
        self.assertEqual(
            list(Group.objects.get(name="Leitor").permissions.values_list("codename", flat=True)), ["view_user"]
        )


@override_settings(PCI_AUTH=None, AUTHSERVICE_URL="http://antigo.teste", REQUIRED_GROUP="Produtos")
class NomesAntigosTests(TestCase):
    """O serviço troca o backend copiado pelo pacote sem mexer no resto do settings."""

    def test_authservice_url_e_required_group_antigos(self):
        with simular_post(resposta(200, {"access": access(groups=["Outro"])})) as post:
            self.assertIsNone(entrar())
        self.assertEqual(post.call_args.args[0], "http://antigo.teste/api/token/")

    def test_credenciais_do_ambiente(self):
        env = {"PCI_AUTH_CLIENT_ID": "pci_env", "PCI_AUTH_CLIENT_SECRET": "s"}
        from unittest import mock

        with mock.patch.dict("os.environ", env), simular_post(resposta(200, {"access": access(groups=["Produtos"])})) as post:
            entrar()
        self.assertEqual(post.call_args.kwargs["json"]["client_id"], "pci_env")
