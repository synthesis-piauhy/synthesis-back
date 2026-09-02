# synthesis-back

Backend da aplicação interna **synthesis**, construído com Django, Django Ninja Extra e PostgreSQL.

O sistema recebe relatos semanais dos gestores, permite que a gerente monte um relatório editorial sem
alterar os relatos originais e mantém cada PDF gerado como uma versão imutável.

## Requisitos

- Python 3.12 ou superior
- [uv](https://docs.astral.sh/uv/)
- Docker, opcional, para executar PostgreSQL localmente

## Executar localmente

```bash
cp .env.example .env
# Preencha SECRET_KEY, JWT_SIGNING_KEY e as variáveis POSTGRES_* no arquivo .env.
# Defina também DATABASE_URL com os mesmos dados do PostgreSQL.
docker compose up -d postgres
uv sync
uv run python manage.py migrate
uv run python manage.py seed_synthesis
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

A documentação OpenAPI fica em `http://localhost:8000/api/docs` e o Django Admin em
`http://localhost:8000/admin`.

Sem um arquivo `.env`, ou com `DATABASE_URL` vazio, o desenvolvimento usa SQLite para permitir uma
inicialização imediata. Para PostgreSQL, preencha as variáveis `POSTGRES_*` e `DATABASE_URL` no `.env` antes
de iniciar o `compose.yaml`. Os testes sempre usam um SQLite isolado.

## Autenticação

A API usa JWT no cabeçalho `Authorization: Bearer <access>`.

- `POST /api/token/pair` — recebe `email` e `password` e devolve access/refresh tokens.
- `POST /api/token/refresh` — renova e rotaciona o refresh token.
- `POST /api/token/verify` — verifica um token.
- `GET /api/me` — devolve o usuário autenticado.

Usuários, áreas, ciclos e grupos podem ser administrados pela interface em `/administracao`. Os papéis são `gestor`, `gerente` e `admin`.

## Contrato principal

- `GET /api/areas`
- `GET /api/users`
- `GET /api/cycles`
- `POST /api/cycles/{id}/reopen`
- `GET|POST /api/activity-reports`
- `GET|PATCH /api/activity-reports/{id}`
- `GET /api/collection/overview`
- `GET /api/collection/pending-managers`
- `GET /api/weekly-reports`
- `POST /api/weekly-reports/draft`
- `GET /api/weekly-reports/{id}`
- `PATCH /api/weekly-reports/{id}/cards/{card_id}`
- `DELETE /api/weekly-reports/{id}/cards/{card_id}`
- `POST /api/weekly-reports/{id}/sections/{section_id}/reorder`
- `GET|POST /api/weekly-reports/{id}/versions`
- `GET /api/weekly-reports/versions/{version_id}/url`

O cadastro de relato usa `multipart/form-data`. Os campos de `ActivityCreateIn` são enviados como campos de
formulário e as imagens no campo repetível `photos`; a primeira imagem é a principal. A API aceita JPEG, PNG
e WebP com até 5 MB por arquivo.

## Regras protegidas pelo backend

- O gestor só cria relatos em sua própria área e só edita os próprios relatos.
- Relatos só podem ser criados ou editados enquanto o ciclo está aberto ou reaberto.
- Existe no máximo um relatório editorial por ciclo semanal.
- Depois da geração do rascunho, a seleção de relatos fica fechada.
- Um `ReportCard` é um snapshot editorial; sua edição nunca altera o `ActivityReport` original.
- Retirar um card é uma remoção lógica e não exclui o relato.
- Cada geração cria uma nova versão de PDF; versões anteriores permanecem armazenadas.
- Operações críticas geram eventos de auditoria.

## Desenvolvimento

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python manage.py check
uv run python manage.py makemigrations --check
```

O PDF é gerado de forma síncrona por `synthesis/pdf.py`. Esse limite está isolado no serviço para permitir a
introdução posterior de Celery/Redis sem alterar o contrato HTTP.

## Armazenamento

Arquivos ficam em `media/` durante o desenvolvimento. Quando `AWS_STORAGE_BUCKET_NAME` estiver definido, o
backend utiliza o storage S3 do `django-storages`; `AWS_S3_ENDPOINT_URL` permite serviços compatíveis com S3.

## Administração pelo frontend

A API `/api/administration` exige um usuário ativo com perfil `admin`. O frontend usa os seguintes endpoints:

- `GET /api/administration/resources`: recursos, campos, opções, contagens e ações permitidas.
- `GET /api/administration/{resource}?q=&page=1`: busca paginada, 25 registros por página.
- `GET /api/administration/{resource}/{id}`: detalhes de um registro.
- `POST /api/administration/{resource}`: criação com `{"values": {...}}`.
- `PUT /api/administration/{resource}/{id}`: atualização completa dos campos do formulário.
- `DELETE /api/administration/{resource}/{id}`: exclusão, bloqueada quando houver vínculos protegidos.

Recursos com cadastro e edição: `users`, `areas`, `cycles`, `groups`.
Recursos de consulta: `permissions`, `activities`, `photos`, `reports`, `sections`, `cards`, `versions`, `audit`.

As senhas são validadas e armazenadas como hash; uma senha vazia na edição preserva a senha atual.
Grupos, permissões individuais, acesso ao Django Admin e privilégios de superusuário só podem ser
alterados por superusuários. Os grupos controlam permissões técnicas do Django; os perfis do synthesis
continuam controlando as operações editoriais e de coleta. Um administrador não pode excluir ou desativar
seu próprio acesso. Registros de negócio e versões são consultados sem alterar os fluxos de autoria.
Criação, atualização, redefinição de senha e exclusão administrativa geram eventos de auditoria sem segredos.
