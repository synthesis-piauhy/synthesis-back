# Implantação Linux na mesma origem

O checklist de preparação, homologação, promoção e pós-implantação está em
[`../../PROXIMAS_ACOES_SYNTHESIS.md`](../../PROXIMAS_ACOES_SYNTHESIS.md).

Topologia assumida: Nginx público com TLS em `synthesis.example.org`; Next em `127.0.0.1:3000`; Gunicorn/Django em `127.0.0.1:8000`; PostgreSQL local e isolado; mídia privada em `/srv/synthesis/media`. O arquivo `nginx.conf` é uma base e deve ter domínio e certificados substituídos.

## Preparação

1. Crie um usuário de serviço sem shell e diretórios separados para código, mídia, estáticos e backups. O usuário da aplicação deve escrever em mídia, mas o processo Next e o Nginx não precisam dessa permissão.
2. Copie `.env.production.example` para um arquivo fora do repositório com modo `0600`. Gere `SECRET_KEY` com `openssl rand -base64 48`. O projeto usa sessão Django e não exige chave JWT.
3. Restrinja PostgreSQL ao loopback, use senha em arquivo protegido e configure um serviço libpq em `pg_service.conf`. Para banco em outro host, remova `DATABASE_LOCAL_PRIVATE` e use `sslmode=verify-full` com CA confiável.
4. Instale exatamente `uv.lock` e `package-lock.json`. Execute migrations e `collectstatic` antes de trocar os processos.

Comandos de validação, carregando as variáveis pelo gerenciador de serviços:

```sh
uv sync --locked --no-dev
uv run python manage.py check --deploy --fail-level WARNING
uv run python manage.py migrate --check
npm ci
npm run build
```

As dependências de desenvolvimento do frontend são necessárias no estágio de build. Depois do build, copie
`.next/static` e `public` para a árvore `.next/standalone` e publique somente esse artefato no host de execução.

Execute Django com Gunicorn ligado somente ao loopback, por exemplo `uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 60`. Execute o artefato standalone do Next no loopback. Use unidades systemd com reinício em falha, `PrivateTmp=true`, `NoNewPrivileges=true`, `ProtectSystem=strict` e `ReadWritePaths=/srv/synthesis/media` somente no backend.

O endpoint `/api/health` verifica o processo; `/api/health/ready` verifica também o banco. Monitore 5xx, 429, duração de `pdf_generation_completed`, `pdf_generation_failed`, uso de disco, conexões e latência do PostgreSQL.

## Deploy e rollback

Antes do deploy, produza e valide um backup. Instale a nova versão em diretório separado, execute checks e migrations, troque o symlink de release e reinicie backend e frontend. Faça smoke test de login, relato com imagem, edição, PDF, download privado e logout. Rollback de código só é seguro quando as migrations da versão nova são compatíveis; migrations destrutivas precisam de procedimento específico e backup restaurável.

## Backup e restauração

Coloque a aplicação em manutenção ou modo somente leitura para obter um par consistente de banco e mídia. Execute `deploy/backup.sh DIRETORIO MEDIA_ROOT PGSERVICE`, copie o resultado para armazenamento separado e protegido e exercite a restauração periodicamente.

Para testar restauração, use um host/banco isolado: valide `sha256sum -c SHA256SUMS`, restaure `database.dump` com `pg_restore` em banco vazio, extraia `media.tar.gz` em diretório vazio, execute `manage.py migrate --check`, `manage.py check --deploy` e o fluxo de smoke test. Nunca teste restauração sobre o banco operacional.

Comece HSTS com uma duração curta. Aumente gradualmente depois de confirmar HTTPS integral. `includeSubDomains` e preload permanecem desligados até todos os subdomínios serem auditados.

## Rotação e incidente

Trocar `SECRET_KEY` encerra todas as sessões e invalida dados assinados. Para uma conta específica, use “encerrar todas as sessões” pela API autenticada ou incremente `session_version` em procedimento administrativo auditado. Em suspeita de vazamento, bloqueie a conta, preserve logs, rotacione a chave afetada e confirme que URLs `/media/` continuam bloqueadas pelo proxy.
