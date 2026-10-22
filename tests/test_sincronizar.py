from io import StringIO

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from tests.utils import ErroConexao, resposta, simular_post

URL = "http://authservice.teste"
DECLARACAO = {
    "AUTHSERVICE_URL": URL,
    "SLUG": "produtos",
    "NOME": "Gestão de Produtos",
    "URL": "https://pci.exemplo/produtos/",
    "REPO": "https://github.com/campusinteligente/GestaoDeProdutos",
    "REQUIRED_GROUP": "GestaoDeProdutos",
    "PERMISSOES": {
        "movimentacao.registrar_saida": "Registrar saída",
        "movimentacao.ver": "Ver movimentações",
    },
}
ESPERADO = {
    "nome": "Gestão de Produtos",
    "url": "https://pci.exemplo/produtos/",
    "repo": "https://github.com/campusinteligente/GestaoDeProdutos",
    "grupo_exigido": "GestaoDeProdutos",
    "permissoes": [
        {"codigo": "movimentacao.registrar_saida", "descricao": "Registrar saída"},
        {"codigo": "movimentacao.ver", "descricao": "Ver movimentações"},
    ],
}


def rodar(*args):
    saida = StringIO()
    call_command("sincronizar_permissoes", *args, stdout=saida)
    return saida.getvalue()


@override_settings(PCI_AUTH={**DECLARACAO, "TOKEN_REGISTRO": "pcireg_x"})
class RegistroTests(SimpleTestCase):
    def test_registra_com_o_token(self):
        with simular_post(resposta(201, {"slug": "produtos", "status": "pendente"})) as post:
            saida = rodar()

        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{URL}/api/aplicacoes/registro/")
        self.assertEqual(kwargs["json"], {"slug": "produtos", **ESPERADO})
        self.assertEqual(kwargs["headers"]["Authorization"], "Registro pcireg_x")
        self.assertIn("registrada, aguardando aprovação", saida)

    def test_registro_repetido_atualiza(self):
        with simular_post(resposta(200, {"slug": "produtos", "status": "pendente"})):
            self.assertIn("atualizada", rodar())

    def test_token_recusado(self):
        with simular_post(resposta(401, {"detail": "Token de registro inválido."})):
            with self.assertRaisesMessage(CommandError, "token de registro"):
                rodar()

    def test_ja_aprovada_pede_o_client_id(self):
        with simular_post(resposta(409, {"detail": "..."})):
            with self.assertRaisesMessage(CommandError, "PCI_AUTH_CLIENT_ID"):
                rodar()

    def test_erro_de_validacao_mostra_o_corpo(self):
        with simular_post(resposta(400, {"slug": ["Use minúsculas"]})):
            with self.assertRaisesMessage(CommandError, "Use minúsculas"):
                rodar()

    def test_authservice_fora_do_ar(self):
        with simular_post(ErroConexao):
            with self.assertRaisesMessage(CommandError, "Não foi possível falar"):
                rodar()

    @override_settings(PCI_AUTH={**DECLARACAO, "TOKEN_REGISTRO": "pcireg_x", "SLUG": "Produtos!"})
    def test_configuracao_invalida_nem_chama(self):
        with simular_post() as post:
            with self.assertRaisesMessage(CommandError, "SLUG inválido"):
                rodar()
        post.assert_not_called()


@override_settings(PCI_AUTH={**DECLARACAO, "CLIENT_ID": "pci_abc", "CLIENT_SECRET": "s", "TOKEN_REGISTRO": "pcireg_x"})
class SincronizacaoTests(SimpleTestCase):
    def test_com_cliente_sincroniza_em_vez_de_registrar(self):
        mudancas = {"criadas": ["movimentacao.ver"], "reativadas": [], "desativadas": ["antiga"]}
        with simular_post(resposta(200, mudancas)) as post:
            saida = rodar()

        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{URL}/api/aplicacoes/sincronizar/")
        self.assertEqual(kwargs["json"], {"client_id": "pci_abc", "client_secret": "s", **ESPERADO})
        self.assertNotIn("Authorization", kwargs["headers"])
        self.assertIn("criadas: 1, reativadas: 0, desativadas: 1", saida)
        self.assertIn("desativada: antiga", saida)

    def test_cliente_recusado(self):
        with simular_post(resposta(401, {"detail": "Credenciais da aplicação inválidas."})):
            with self.assertRaisesMessage(CommandError, "recusou o client_id 'pci_abc'"):
                rodar()


class SemCredenciaisTests(SimpleTestCase):
    def test_nao_faz_nada(self):
        with simular_post() as post:
            self.assertIn("nada a fazer", rodar())
        post.assert_not_called()

    @override_settings(PCI_AUTH=DECLARACAO)
    def test_mostrar_nao_chama_e_nao_tem_segredo(self):
        with simular_post() as post:
            saida = rodar("--mostrar")
        post.assert_not_called()
        self.assertIn('"slug": "produtos"', saida)
        self.assertIn("movimentacao.registrar_saida", saida)

    @override_settings(PCI_AUTH={**DECLARACAO, "NOME": "", "URL": "", "REPO": "", "REQUIRED_GROUP": None})
    def test_campos_vazios_vao_como_texto_vazio_e_sem_nome(self):
        from pci_auth.cliente import declaracao

        corpo = declaracao()
        self.assertNotIn("nome", corpo)
        self.assertEqual((corpo["url"], corpo["repo"], corpo["grupo_exigido"]), ("", "", ""))
