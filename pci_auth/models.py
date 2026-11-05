from django.conf import settings
from django.db import models


class PermissoesUsuario(models.Model):
    """
    Permissões do usuário nesta aplicação, como o AuthService mandou no último login.

    Regravado a cada login: mudança feita no AuthService vale a partir do próximo login.
    """

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="permissoes_pci", verbose_name="Usuário"
    )
    aplicacao = models.CharField("Aplicação", max_length=60, help_text="aud do token.")
    permissoes = models.JSONField("Permissões", default=list)
    escopo = models.JSONField(
        "Escopo", default=dict, help_text="{codigo: [nós]} das permissões limitadas a setores."
    )
    atualizado_em = models.DateTimeField("Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Permissões do usuário (AuthService)"
        verbose_name_plural = "Permissões dos usuários (AuthService)"

    def __str__(self):
        return f"{self.usuario} em {self.aplicacao}"


class RegistroAuditoria(models.Model):
    """
    Rastreabilidade (pci_auth.auditoria): cada criação, alteração e exclusão nos models auditados, e
    cada acesso negado. `jti` liga ao login no AuthService (Acessos, busca por jti).
    """

    class Acao(models.TextChoices):
        CRIADO = "criado", "Criado"
        ALTERADO = "alterado", "Alterado"
        EXCLUIDO = "excluido", "Excluído"
        NEGADO = "negado", "Acesso negado"

    class Origem(models.TextChoices):
        TELA = "tela", "Tela"
        API = "api", "API (sessão)"
        TOKEN = "token", "API (token)"
        ADMIN = "admin", "Admin"
        SISTEMA = "sistema", "Sistema (comando, tarefa)"

    quando = models.DateTimeField("Quando", auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="Usuário",
    )
    username = models.CharField("Login", max_length=150, blank=True, help_text="Fica mesmo se o usuário for apagado.")
    acao = models.CharField("Ação", max_length=10, choices=Acao.choices)
    modelo = models.CharField("Tipo", max_length=100, blank=True, help_text="app.model")
    objeto_id = models.CharField("ID", max_length=64, blank=True)
    objeto_repr = models.CharField("Objeto", max_length=200, blank=True)
    mudancas = models.JSONField("Mudanças", default=dict, blank=True, help_text="{campo: [antes, depois]}")
    permissao = models.CharField("Permissão que faltou", max_length=300, blank=True)
    origem = models.CharField("Origem", max_length=10, choices=Origem.choices)
    metodo = models.CharField("Método", max_length=10, blank=True)
    caminho = models.CharField("Caminho", max_length=300, blank=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("User-Agent", max_length=300, blank=True)
    jti = models.CharField("jti do token", max_length=64, blank=True, db_index=True)
    requisicao = models.CharField("Requisição", max_length=32, blank=True, db_index=True)

    class Meta:
        verbose_name = "Registro de auditoria"
        verbose_name_plural = "Auditoria"
        ordering = ["-quando", "-pk"]
        indexes = [
            models.Index(fields=["modelo", "objeto_id"]),
            models.Index(fields=["username", "quando"]),
        ]

    def __str__(self):
        alvo = f"{self.modelo} {self.objeto_repr or self.objeto_id}".strip() or self.caminho
        return f"{self.get_acao_display()} — {alvo} ({self.username or 'sistema'})"
