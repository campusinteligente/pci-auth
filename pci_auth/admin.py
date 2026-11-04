from django.contrib import admin

from pci_auth.models import PermissoesUsuario


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
