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
# Preencha SECRET_KEY e, se usar PostgreSQL, DATABASE_URL/POSTGRES_* no arquivo .env.
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
de iniciar o `compose.yaml`. Os testes usam um SQLite isolado por padrão; defina `TEST_DATABASE_URL` com um
banco PostgreSQL exclusivamente descartável para validar a suíte no mesmo mecanismo de produção.

O diagrama, as responsabilidades das tabelas, constraints, índices e políticas de exclusão estão descritos
em [`docs/database.md`](docs/database.md).

## Autenticação

A aplicação web usa sessões Django armazenadas no servidor. O navegador recebe somente o cookie
`HttpOnly`; operações mutáveis também exigem o token CSRF. Em produção, ambos os cookies são `Secure`.

- `GET /api/token/csrf` — inicializa o cookie CSRF.
- `POST /api/token/pair` — autentica `email` e `password` e cria a sessão.
- `POST /api/token/refresh` e `POST /api/token/verify` — validam e renovam a sessão compatível com o frontend.
- `POST /api/token/logout` — encerra a sessão atual.
- `POST /api/token/logout-all` — revoga todas as sessões do usuário.
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
formulário e as imagens no campo repetível `photos`; a primeira imagem é a principal. A API aceita até dez
JPEG, PNG ou WebP, com no máximo 5 MB por arquivo e 25 MB no lote. Os bytes são decodificados, validados e
reencodados sem metadados antes do armazenamento.

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

Arquivos ficam em `media/` durante o desenvolvimento, mas não são publicados por `/media/`. Fotos e PDFs
são entregues somente pelos endpoints autenticados da API, depois da verificação de papel e propriedade.
Quando `AWS_STORAGE_BUCKET_NAME` estiver definido, o backend pode usar storage S3 privado via
`django-storages`; `AWS_S3_ENDPOINT_URL` permite serviços compatíveis com S3.

As listas de usuários, ciclos, relatos e relatórios são paginadas e aceitam `page` e `pageSize` (máximo 100).
Consulte [`deploy/README.md`](deploy/README.md) para a topologia Linux/Nginx de produção assumida.

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
