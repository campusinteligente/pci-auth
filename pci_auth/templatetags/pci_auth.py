from django import template

from pci_auth.permissoes import pode as _pode

register = template.Library()


@register.filter
def pode(user, codigo):
    """{% load pci_auth %}{% if request.user|pode:"produto.editar" %}...{% endif %}"""
    return _pode(user, codigo)
