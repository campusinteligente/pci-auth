from django.core import checks
from django.test import SimpleTestCase, override_settings

from pci_auth.checks import verificar_configuracao

URL = "http://authservice.teste"
VALIDA = {"AUTHSERVICE_URL": URL, "TOKEN_REGISTRO": "pcireg_x", "SLUG": "produtos", "NOME": "Produtos"}


def ids(**config):
    with override_settings(PCI_AUTH=config):
        return [a.id for a in verificar_configuracao()]


class ChecksTests(SimpleTestCase):
    def test_configuracao_valida_sem_avisos(self):
        self.assertEqual(ids(**VALIDA, PERMISSOES={"movimentacao.ver": "Ver", "admin": ""}), [])

    def test_registrado_no_django(self):
        with override_settings(PCI_AUTH={**VALIDA, "SLUG": "X"}):
            self.assertIn("pci_auth.W003", [a.id for a in checks.run_checks()])

    def test_sem_url_com_o_backend(self):
        self.assertEqual(ids(), ["pci_auth.W001"])

    @override_settings(AUTHENTICATION_BACKENDS=["django.contrib.auth.backends.ModelBackend"])
    def test_sem_url_sem_o_backend_nao_avisa(self):
        self.assertEqual(ids(), [])

    def test_client_id_sem_secret(self):
        self.assertEqual(ids(AUTHSERVICE_URL=URL, CLIENT_ID="pci_abc"), ["pci_auth.W002"])

    def test_declaracao_so_e_conferida_quando_vai_ser_usada(self):
        self.assertEqual(ids(AUTHSERVICE_URL=URL, SLUG="Inválido!", PERMISSOES={"X Y": ""}), [])

    def test_slug_invalido(self):
        for slug in ("", "Produtos", "produtos_novo", "-produtos", "a" * 61):
            with self.subTest(slug=slug):
                self.assertEqual(ids(**{**VALIDA, "SLUG": slug}), ["pci_auth.W003"])

    def test_sem_nome(self):
        self.assertEqual(ids(**{**VALIDA, "NOME": ""}), ["pci_auth.W004"])

    def test_permissoes_nao_e_dict(self):
        self.assertEqual(ids(**VALIDA, PERMISSOES=["movimentacao.ver"]), ["pci_auth.W005"])

    def test_codigos_invalidos(self):
        for codigo in ("Movimentacao.ver", "movimentacao..ver", "movimentacao.*", "ver-tudo", ".ver"):
            with self.subTest(codigo=codigo):
                self.assertEqual(ids(**VALIDA, PERMISSOES={codigo: ""}), ["pci_auth.W006"])

    def test_descricao_longa(self):
        self.assertEqual(ids(**VALIDA, PERMISSOES={"ver": "x" * 256}), ["pci_auth.W007"])
