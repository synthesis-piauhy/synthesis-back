# Implantação Linux na mesma origem

O checklist de preparação, homologação, promoção e pós-implantação está em
[`../../PROXIMAS_ACOES_SYNTHESIS.md`](../../PROXIMAS_ACOES_SYNTHESIS.md).

Topologia assumida: Nginx público com TLS em `synthesis.example.org`; Next em `127.0.0.1:3000`; Gunicorn/Django em `127.0.0.1:8000`; PostgreSQL local e isolado; mídia privada em `/srv/synthesis/media`. O arquivo `nginx.conf` é uma base e deve ter domínio e certificados substituídos.

## Preparação

1. Crie os usuários de serviço sem shell `synthesis-back` e `synthesis-front`. Use `/srv/synthesis/backend` como symlink da release atual do backend e `/srv/synthesis/frontend` como symlink do artefato Next atual. Separe mídia e backups dos diretórios de release. Somente `synthesis-back` deve escrever em `/srv/synthesis/media`; Next e Nginx não precisam ler essa árvore. O Nginx precisa ler `/srv/synthesis/backend/staticfiles`.
2. Copie `.env.production.example` para `/etc/synthesis/backend.env`, fora do repositório, com proprietário `root`, grupo `synthesis-back` e modo `0640`. Gere `SECRET_KEY` com `openssl rand -base64 48`. O projeto usa sessão Django e não exige chave JWT.
3. Restrinja PostgreSQL ao loopback, use senha em arquivo protegido e configure um serviço libpq em `pg_service.conf`. Para banco em outro host, remova `DATABASE_LOCAL_PRIVATE` e use `sslmode=verify-full` com CA confiável.
4. Instale exatamente `uv.lock` e `package-lock.json`. Execute migrations e `collectstatic` antes de trocar os processos.

Comandos de validação, carregando as variáveis pelo gerenciador de serviços:

```sh
uv sync --locked --no-dev
uv run python manage.py check --deploy --fail-level WARNING
uv run python manage.py migrate --plan
# Depois do backup pré-deploy e antes de ativar a release:
uv run python manage.py migrate
uv run python manage.py migrate --check
uv run python manage.py collectstatic --noinput
npm ci
npm run build
```

As dependências de desenvolvimento do frontend são necessárias no estágio de build. Depois do build, copie
`.next/static` e `public` para a árvore `.next/standalone` e publique somente esse artefato no host de execução:

```sh
mkdir -p .next/standalone/.next/static
cp -a .next/static/. .next/standalone/.next/static/
cp -a public .next/standalone/public
```

Execute o build com `NEXT_PUBLIC_API_URL=/api` e sem `NEXT_API_PROXY_TARGET`. O navegador usa `/api` na mesma origem HTTPS. No servidor, a pasta `frontend` deve apontar para o conteúdo de `.next/standalone`, incluindo `server.js`, `.next/static` e `public`.

Instale [`synthesis-back.service`](synthesis-back.service) e [`synthesis-front.service`](synthesis-front.service) em `/etc/systemd/system/`, adaptando os caminhos e usuários se a topologia mudar. O backend lê `/etc/synthesis/backend.env`, fora do repositório, com proprietário `root`, grupo `synthesis-back` e modo `0640`; a `.venv` da release deve conter Gunicorn. Ambos os serviços escutam apenas no loopback. Execute `systemctl daemon-reload`, `systemctl enable --now synthesis-back synthesis-front` e confira `systemctl status` e `journalctl -u synthesis-back -u synthesis-front`.

O arquivo [`nginx.conf`](nginx.conf) deve ser instalado no contexto `http` do Nginx porque contém `limit_req_zone`. Substitua o domínio e os caminhos dos certificados, execute `nginx -t` e só então recarregue. O alias `/static/` pressupõe o symlink `/srv/synthesis/backend` descrito acima.

O endpoint `/api/health` verifica o processo; `/api/health/ready` verifica também o banco. Monitore 5xx, 429, duração de `pdf_generation_completed`, `pdf_generation_failed`, uso de disco, conexões e latência do PostgreSQL.

## Deploy e rollback

Antes do deploy, produza e valide um backup. Instale a nova versão em diretório separado, execute checks e migrations, troque o symlink de release e reinicie backend e frontend. Faça smoke test de login, relato com imagem, edição, PDF, download privado e logout. Rollback de código só é seguro quando as migrations da versão nova são compatíveis; migrations destrutivas precisam de procedimento específico e backup restaurável.

## Backup e restauração

Coloque a aplicação em manutenção ou modo somente leitura para obter um par consistente de banco e mídia. Execute `deploy/backup.sh DIRETORIO MEDIA_ROOT PGSERVICE`, copie o resultado para armazenamento separado e protegido e exercite a restauração periodicamente. O script grava arquivos com acesso restrito, elimina um conjunto incompleto em caso de falha e produz `SHA256SUMS` com caminhos relativos.

Para testar restauração, use um host/banco isolado: valide `sha256sum -c SHA256SUMS`, restaure `database.dump` com `pg_restore` em banco vazio, extraia `media.tar.gz` em diretório vazio, execute `manage.py migrate --check`, `manage.py check --deploy` e o fluxo de smoke test. Nunca teste restauração sobre o banco operacional.

Comece HSTS com uma duração curta. Aumente gradualmente depois de confirmar HTTPS integral. `includeSubDomains` e preload permanecem desligados até todos os subdomínios serem auditados.

## Rotação e incidente

Trocar `SECRET_KEY` encerra todas as sessões e invalida dados assinados. Para uma conta específica, use “encerrar todas as sessões” pela API autenticada ou incremente `session_version` em procedimento administrativo auditado. Em suspeita de vazamento, bloqueie a conta, preserve logs, rotacione a chave afetada e confirme que URLs `/media/` continuam bloqueadas pelo proxy.
