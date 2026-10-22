# pci-auth

Login pelo **AuthService** (repo `Pessoa`) e **auto-registro de aplicações** para os serviços Django do
PCI – Campus Inteligente.

Substitui o `app/backends.py` que cada serviço tinha copiado (as cópias já divergiam) e faz o serviço
se apresentar ao AuthService: quem ele é e quais permissões existem nele.

- `pci_auth.backends.AuthServiceBackend`: login com usuário e senha no AuthService, mesmo comportamento
  do backend copiado (grupo exigido, usuário local sem senha, grupos sincronizados).
- `manage.py sincronizar_permissoes`: roda no deploy. Registra a aplicação (fica pendente até alguém
  aprovar no admin do AuthService) e, depois de aprovada, mantém as permissões declaradas em dia.

> Repositório público. Não coloque aqui IP, URL interna, nome de grupo de produção nem token de
> verdade, nem em exemplo ou teste: tudo vem do settings e do `.env` de cada serviço.

## Instalação

```
# requirements.txt
pci-auth @ git+https://github.com/campusinteligente/pci-auth@v0.1.0
```

Fixe sempre uma tag: cada serviço atualiza quando quiser.

## Configuração (`config/settings_production.py`)

```python
INSTALLED_APPS += ["pci_auth"]
AUTHENTICATION_BACKENDS = ["pci_auth.backends.AuthServiceBackend"]

PCI_AUTH = {
    "AUTHSERVICE_URL": config("AUTHSERVICE_URL"),
    "REQUIRED_GROUP": config("REQUIRED_GROUP", default="") or None,

    # Declaração da aplicação (vai para o AuthService no registro e a cada deploy)
    "SLUG": "produtos",                       # minúsculas, números e hífens; não muda depois
    "NOME": "Gestão de Produtos",
    "URL": config("URL_PUBLICA", default=""),
    "REPO": "https://github.com/campusinteligente/GestaoDeProdutos",
    "PERMISSOES": {
        "movimentacao.registrar_saida": "Registrar saída de produto",
        "movimentacao.ver": "Ver movimentações",
    },

    # Grupos do AuthService → permissões Django locais (o antigo DEFAULT_GROUP_PERMISSIONS)
    "PERMISSOES_POR_GRUPO": {
        "MeuServico_Gerente": "all",
        "MeuServico_Visualizador": ["view_produto", "view_movimentacaoproduto"],
    },
    "APP_LABELS": ["app"],
}
```

Todas as chaves:

| Chave | Padrão | Para quê |
|---|---|---|
| `AUTHSERVICE_URL` | `settings.AUTHSERVICE_URL` | Endereço do AuthService (sem `/` no fim) |
| `REQUIRED_GROUP` | `settings.REQUIRED_GROUP` | Grupo exigido para entrar; superusuário sempre entra |
| `CLIENT_ID`, `CLIENT_SECRET` | env `PCI_AUTH_CLIENT_ID`, `PCI_AUTH_CLIENT_SECRET` | Credencial da aplicação, gerada na aprovação |
| `TOKEN_REGISTRO` | env `PCI_AUTH_TOKEN_REGISTRO` | Só para o primeiro registro |
| `SLUG`, `NOME`, `URL`, `REPO` | vazio | Identificação da aplicação no AuthService |
| `PERMISSOES` | `{}` | `{codigo: descricao}`; código em minúsculas, números, `_` e pontos |
| `PERMISSOES_POR_GRUPO` | `settings.GROUP_PERMISSIONS` | `{grupo: "all" \| [codenames]}`, aplicado quando o grupo é criado localmente |
| `APP_LABELS` | `["app"]` | De quais apps vêm as permissões de `"all"` (ex.: `["app", "paginas_pci"]`) |
| `CHAVE_PUBLICA` | `SIMPLE_JWT["VERIFYING_KEY"]` | PEM do AuthService; com ela a assinatura do token é conferida |
| `SALVAR_TOKEN_NA_SESSAO` | `True` | Guarda o access em `request.session["access_token"]` |
| `HOST` | `"localhost"` | Cabeçalho `Host` nas chamadas (o backend copiado sempre mandou esse); `None` não manda |
| `TIMEOUT` | `10` | Segundos por chamada |

Os nomes antigos (`AUTHSERVICE_URL`, `REQUIRED_GROUP`, `GROUP_PERMISSIONS`) continuam valendo quando a
chave não está em `PCI_AUTH`, então dá para trocar o backend sem reescrever o settings.

## `.env`

```
PCI_AUTH_TOKEN_REGISTRO=pcireg_...      # só até a aprovação
PCI_AUTH_CLIENT_ID=...                  # depois da aprovação
PCI_AUTH_CLIENT_SECRET=...
```

## Entrypoint

Depois do `migrate`:

```bash
echo "Sincronizando permissões com o AuthService..."
python manage.py sincronizar_permissoes || echo "AVISO: sincronização de permissões falhou, continuando..."
```

O comando sai com código 1 quando algo dá errado; o `|| echo` impede que um problema no AuthService
derrube o deploy do serviço.

## Do registro à aprovação

1. Com `PCI_AUTH_TOKEN_REGISTRO` no `.env`, o deploy roda `sincronizar_permissoes`, que chama
   `POST /api/aplicacoes/registro/`. A aplicação aparece **pendente** no admin do AuthService
   (Permissões → Aplicações), com as permissões declaradas. Repetir só atualiza a pendente.
2. A equipe central seleciona a aplicação e usa **Aprovar e gerar cliente**. O `client_id` e o
   segredo aparecem uma única vez.
3. Coloque `PCI_AUTH_CLIENT_ID` e `PCI_AUTH_CLIENT_SECRET` no `.env` e faça o deploy de novo. O token
   de registro pode sair.
4. Daí em diante cada deploy chama `POST /api/aplicacoes/sincronizar/`: permissão nova fica ativa, a
   que sumiu da declaração fica inativa (não é apagada, para não perder papéis e atribuições).

Para ver o que seria enviado, sem chamar nada: `python manage.py sincronizar_permissoes --mostrar`.

## Login

- Com `client_id` configurado, o login identifica a aplicação no AuthService (aparece nos acessos da
  aplicação no admin).
- Se o AuthService recusar a credencial da aplicação, o login é refeito sem ela e o erro vai para o
  log: enquanto o `client_id` for opcional no AuthService, uma credencial errada não tranca o login
  de ninguém.
- Sem `CHAVE_PUBLICA`, os claims são lidos sem conferir a assinatura, como no backend copiado (o
  token acabou de vir do próprio AuthService). Com ela, token de outra chave é recusado.
- Os checks do Django (`manage.py check`) avisam sobre configuração errada; o comando
  `sincronizar_permissoes` não roda com eles.

## Trocando o backend copiado

1. `requirements.txt`: acrescente o `pci-auth`.
2. Mova o `DEFAULT_GROUP_PERMISSIONS` do `app/backends.py` para `PCI_AUTH["PERMISSOES_POR_GRUPO"]`
   (ou `GROUP_PERMISSIONS` no settings). Se o `_APP_LABELS` tinha mais de um app, ponha em `APP_LABELS`.
3. `AUTHENTICATION_BACKENDS = ["pci_auth.backends.AuthServiceBackend"]` e `"pci_auth"` em
   `INSTALLED_APPS` (só no `settings_production.py`; o `settings.py` de dev continua com o login local).
4. Apague `app/backends.py` e procure quem importava dele.
5. Entrypoint e `.env` como acima.

Para mudar uma etapa do login sem copiar o backend, faça uma subclasse e sobrescreva `pedir_token`,
`ler_claims`, `pode_entrar` ou `atualizar_usuario`.

## Desenvolvimento

```bash
uv venv --python 3.11 .venv && uv pip install -p .venv/bin/python -e . "Django==4.2.7"
.venv/bin/python runtests.py
```

Versão em `pci_auth/__init__.py`. Para lançar: PR mergeado, depois tag `vX.Y.Z` na `main`.
