# pci-auth

Login pelo **AuthService** (repo `Pessoa`) e **auto-registro de aplicações** para os serviços Django do
PCI – Campus Inteligente.

Substitui o `app/backends.py` que cada serviço tinha copiado (as cópias já divergiam) e faz o serviço
se apresentar ao AuthService: quem ele é e quais permissões existem nele.

- `pci_auth.backends.AuthServiceBackend`: login com usuário e senha no AuthService, mesmo comportamento
  do backend copiado (grupo exigido, usuário local sem senha, grupos sincronizados).
- `pci_auth.permissoes`: `pode`, `@exige_permissao`, `ExigePermissaoMixin`, `permissao_drf` e o filtro
  `pode` nos templates, com as permissões que o AuthService calculou para o usuário (a partir da 0.2.0).
- `pci_auth.drf`: permissões na API (0.4.0): por modelo + ação na API dinâmica e para quem chama com
  token Bearer.
- `pci_auth.auditoria`: rastreabilidade (0.5.0): quem criou, alterou ou apagou cada registro (antes e
  depois), por onde, de onde e com qual token; e cada acesso negado.
- `manage.py sincronizar_permissoes`: roda no deploy. Registra a aplicação (fica pendente até alguém
  aprovar no admin do AuthService) e, depois de aprovada, mantém as permissões declaradas em dia.

> Repositório público. Não coloque aqui IP, URL interna, nome de grupo de produção nem token de
> verdade, nem em exemplo ou teste: tudo vem do settings e do `.env` de cada serviço.

## Instalação

```
# requirements.txt
pci-auth @ git+https://github.com/campusinteligente/pci-auth@v0.5.0
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
| `EXIGIR_PERMISSOES` | `True` | `False` libera as checagens de permissão para qualquer usuário logado (implantação gradual) |
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

## Exigindo permissões (0.2.0)

Com o `client_id` configurado, o token do login traz as permissões do usuário nesta aplicação
(papéis e atribuições ficam no admin do AuthService). O backend grava em `PermissoesUsuario` a cada
login (`manage.py migrate` cria a tabela); mudança feita no AuthService vale a partir do próximo login.

```python
from pci_auth.permissoes import ExigePermissaoMixin, exige_permissao, permissao_drf, pode, escopo

@exige_permissao("movimentacao.registrar")              # várias = exige todas
def registrar_saida(request): ...

class EditarProduto(ExigePermissaoMixin, UpdateView):
    permissao_exigida = "produto.editar"                # ou uma tupla

class ProdutoViewSet(ModelViewSet):
    permission_classes = [permissao_drf("produto.ver")]

if pode(request.user, "movimentacao.registrar", no="setor_sub:7"): ...
escopo(request.user, "movimentacao.registrar")          # None = tudo; {"setor_sub:7"}; set() = não pode
```

```django
{% load pci_auth %}
{% if request.user|pode:"produto.editar" %}<a href="...">Editar</a>{% endif %}
```

- Anônimo vai para o login; sem a permissão, 403. Superusuário sempre pode.
- Permissão com escopo vale só nos setores listados (`setor_super:<id>`, `setor:<id>`,
  `setor_sub:<id>`, ids do AuthService). Sem `no`, basta valer em algum lugar.
- **Sem registro, ninguém (fora o superusuário) pode nada**: isso vale para a aplicação sem
  `client_id` e para o settings de dev sem o app `pci_auth`. Só exija permissões depois que a aplicação
  estiver aprovada e os papéis atribuídos no AuthService.
- Aplicação com "Permissões no token" desligado no AuthService: o backend busca em
  `GET /api/permissoes/me/`. Se a busca falhar, o usuário entra sem permissões (o erro vai para o log).
- `REQUIRED_GROUP` continua valendo para entrar; as permissões decidem o que cada um faz lá dentro.
- **Implantação gradual** (0.3.0): `PCI_AUTH["EXIGIR_PERMISSOES"] = False` faz todas as checagens
  liberarem qualquer usuário logado e ativo (como antes). Marque as views, faça o deploy, atribua os
  papéis no AuthService (o simulador mostra o resultado) e só então ligue, por exemplo
  `config("PCI_AUTH_EXIGIR_PERMISSOES", default=False, cast=bool)` no settings e `True` no `.env`.

## Permissões na API (0.4.0)

Duas portas da API passavam ao largo das permissões: a **API dinâmica** do template
(`/api/<app>/<model>/`, ler/criar/alterar/apagar qualquer tabela) e as requisições com **Bearer**
(o login pela web, que grava `PermissoesUsuario`, não acontece nelas).

```python
# settings_production.py
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "pci_auth.drf.PermissaoPorModelo",     # só age em views com get_model() (a DynamicModelViewSet)
    ],
    ...
}
PCI_AUTH = {
    ...
    "API_PERMISSOES": {                         # chave = model_name (minúsculas)
        "produto": {"ler": "produto.ver", "escrever": "produto.editar"},
        "solicitacaoproduto": {"ler": "solicitacao.ver", "criar": "solicitacao.criar",
                               "alterar": "solicitacao.atender", "apagar": "solicitacao.atender"},
        "setorsub": {"ler": ""},               # "" = basta estar logado
    },
}
```

- Ações: `ler` (GET/HEAD/OPTIONS), `criar` (POST), `alterar` (PUT/PATCH), `apagar` (DELETE);
  `escrever` vale para as três últimas.
- **Model ou ação fora do mapa fica fechado** (só o superusuário) quando a exigência está ligada.
- O check `pci_auth.W009` avisa ação desconhecida ou código que não está em `PERMISSOES`.

Para o Bearer, chame `carregar_do_token` na classe de autenticação JWT do serviço:

```python
from pci_auth.drf import carregar_do_token

class AuthServiceJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        resultado = super().authenticate(request)
        if resultado is not None:
            user, token = resultado
            carregar_do_token(user, self.get_raw_token(self.get_header(request)), token.payload)
        return resultado
```

As permissões valem só naquela requisição (nada é gravado):

- token desta aplicação (`aud` = `SLUG`): os claims, ou `GET /api/permissoes/me/`;
- token sem `aud` (outro serviço que consome esta API sem `client_id`):
  `GET /api/permissoes/me/?aplicacao=<SLUG>`;
- token de outra aplicação: nenhuma permissão.

A consulta ao AuthService fica no cache do Django enquanto o token vale, até
`CACHE_PERMISSOES_TOKEN` segundos (padrão 300). Com `EXIGIR_PERMISSOES = False` nada é consultado.

## Auditoria (0.5.0)

```python
PCI_AUTH = {..., "AUDITAR": True}
MIDDLEWARE = [
    ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "pci_auth.auditoria.AuditoriaMiddleware",
    ...
]
```

`manage.py migrate` cria a tabela; a consulta fica no admin (**PCI Auth → Auditoria**), só leitura.

Cada registro guarda: quando, quem (usuário e login, que fica mesmo se o usuário for apagado), a ação
(criado, alterado, excluído, acesso negado), o objeto (`app.model`, id, texto), as mudanças
(`{campo: [antes, depois]}`; M2M: `{campo: {adicionados|removidos: [ids]}}`), a permissão que faltou
(no acesso negado), a origem (tela, API com sessão, API com token, admin, sistema), método, caminho, IP,
aparelho, o **jti** do token e um id da requisição (cabeçalho `X-Requisicao-Id` da resposta).

- **Ligar ao login no AuthService**: o `jti` é o mesmo que o AuthService guarda em Acessos (Pessoa
  com o campo `jti`, 2026-11). Na tela, vem do token guardado na sessão no login; com Bearer, do token
  da requisição (`pci_auth.drf.carregar_do_token`).
- Models auditados: os dos apps em `AUDITAR_APPS` (padrão: `APP_LABELS`). Campos fora:
  `AUDITORIA_IGNORAR_CAMPOS` (padrão `["password"]`). Textos longos são cortados em 500 caracteres.
- **Não pega** `queryset.update()`, `bulk_create()` nem SQL direto (o Django não dispara sinais).
- O registro entra na mesma transação da mudança. Falha ao gravar só vai para o log.
- Acesso negado: `@exige_permissao`, `ExigePermissaoMixin`, `permissao_drf` e `PermissaoPorModelo`
  registram o código; qualquer outro 403 a usuário logado é registrado sem código. Anônimo não.
- Retenção: `manage.py limpar_auditoria [--dias N]` (padrão `AUDITORIA_DIAS` = 365), por exemplo num
  cron diário. Os registros têm dado pessoal (login, IP): defina a retenção com quem cuida da LGPD.
- Check `pci_auth.W010`: auditoria ligada sem o middleware.

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
