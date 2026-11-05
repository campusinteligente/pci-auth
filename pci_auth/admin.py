from django.contrib import admin

from pci_auth.models import PermissoesUsuario, RegistroAuditoria


@admin.register(PermissoesUsuario)
class PermissoesUsuarioAdmin(admin.ModelAdmin):
    """Só leitura: quem manda é o AuthService (papéis e atribuições ficam no admin dele)."""

    list_display = ("usuario", "aplicacao", "atualizado_em")
    search_fields = ("usuario__username",)
    readonly_fields = ("usuario", "aplicacao", "permissoes", "escopo", "atualizado_em")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    """Só leitura. Para ver o login no AuthService: busque o jti em Acessos, no admin dele."""

    list_display = ("quando", "acao", "username", "modelo", "objeto_repr", "permissao", "origem", "ip")
    list_filter = ("acao", "origem", "modelo")
    search_fields = ("username", "objeto_id", "objeto_repr", "=jti", "=requisicao", "caminho", "ip")
    date_hierarchy = "quando"
    readonly_fields = [f.name for f in RegistroAuditoria._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # limpeza só pelo comando limpar_auditoria (retenção)
