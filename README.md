# FTP Indexer

FTP Indexer is a Dockerized FTP/FTPS metadata crawler and search interface. It
recursively indexes remote filenames and directory metadata without downloading
file contents, then serves fast filename and path searches through SQLite FTS5.

The application runs with standard Docker Compose on Linux, macOS, or Windows
and is designed for large FTP directory trees:

- the web/API service and crawler run independently;
- scan queues are stored in SQLite and survive restarts;
- crawler writes are committed in configurable batches;
- interrupted scans reconnect automatically and can resume safely;
- a completed scan marks previously indexed files as unavailable when they are
  no longer present;
- named Docker volumes preserve the database, crawler log, and configuration
  directory.

## Quick start

1. Install Docker Engine with the Compose plugin, or Docker Desktop.
2. Clone this repository or copy the project directory to the Docker host.
3. Create the local environment file:

   ```bash
   cp .env.example .env
   ```

4. Review `.env`, especially `FTP_HOST`, `FTP_USERNAME`, `FTP_PASSWORD`,
   `FTP_PROTOCOL`, and `FTP_ROOT_PATH`.
   Use `FTP_PROTOCOL=ftps` for explicit FTPS and normally keep port `21`.
5. From the project directory, start the stack:

   ```bash
   docker compose up -d --build
   ```

6. Open `http://localhost:11025`. When Docker runs on another machine, replace
   `localhost` with that machine's hostname or IP address. The port is
   configurable with `HOST_PORT` in `.env`.
7. Sign in with the administrator username and password configured in `.env`.
8. Select **Start incremental scan**. The page will show the current directory,
   live statistics, and recent crawler events.

The first crawl can take a long time on a very large server. It can be stopped
and resumed without discarding completed directories. Later scans update the
same index rather than rebuilding it.

## Services

| Service | Purpose |
| --- | --- |
| `migrate` | Applies the versioned database migration before startup |
| `web` | Serves the dashboard, search UI, REST API, and OpenAPI docs |
| `crawler` | Runs scheduled/manual scans and processes durable scan queues |

Only the web service publishes a host port. The crawler never accepts inbound
network traffic.

## Configuration

Copy `.env.example` to `.env` for a new installation. Important variables:

| Variable | Default | Description |
| --- | --- | --- |
| `FTP_HOST` | required | FTP/FTPS hostname |
| `FTP_PORT` | `21` | Remote port |
| `FTP_PROTOCOL` | `ftp` | `ftp` or explicit `ftps` |
| `FTP_USERNAME` / `FTP_PASSWORD` | required | Remote credentials |
| `FTP_PASSIVE_MODE` | `true` | Use passive data connections |
| `FTP_ROOT_PATH` | `/` | Limit crawling to this remote subtree |
| `FTP_TIMEOUT_SECONDS` | `30` | Per-connection/request timeout |
| `FTP_MAX_RETRIES` | `5` | Reconnect attempts per failed request |
| `FTP_REQUEST_DELAY_MS` | `250` | Courtesy delay after directory requests |
| `FTP_BATCH_SIZE` | `500` | Metadata rows processed per database batch |
| `FTP_TLS_VERIFY` | `true` | Verify the FTPS server certificate chain |
| `SCAN_SCHEDULE` | `0 */6 * * *` | Standard five-field cron schedule; blank disables |
| `DATABASE_URL` | `sqlite:////data/ftp-index.db` | Persistent index database |
| `HOST_PORT` | `11025` | Port published on the Docker host |
| `WEB_PORT` | `8080` | Internal web service port; normally leave unchanged |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | optional | Local web administrator; blank password disables login |
| `SESSION_SECRET` | required | Long random value used to sign sessions |
| `SECURE_COOKIES` | `false` | Set `true` when the browser uses HTTPS |
| `ALLOWED_HOSTS` | `*` | Comma-separated accepted hostnames |
| `ENABLE_DIRECT_FTP_LINKS` | `false` | Show credential-free FTP links |
| `MUSIC_FILENAME_PARSING` | `true` | Infer optional music fields from names/paths |

The settings page stores non-secret crawler overrides in SQLite. The FTP
password can only be supplied through the environment and is never returned by
the API, rendered in the page, or included in crawler logs.

Keep `FTP_TLS_VERIFY=true` whenever the server presents a certificate chain
trusted by the container. Set it to `false` only for a server with a known,
privately trusted or incomplete certificate chain; the session remains
encrypted but the server identity is not verified.

When exposing the app through an HTTPS reverse proxy, set
`SECURE_COOKIES=true` and set `ALLOWED_HOSTS` to the app hostname or IP.

## Search

Search uses SQLite FTS5 with Unicode tokenization and prefix matching. For
example, `deep ant` finds `Deep Anthem.mp3`. Searches cover the filename,
parent directory, and complete remote path.

Available filters:

- extension;
- minimum/maximum byte size;
- modification date range;
- directory subtree;
- available, unavailable, or all files.

Sorting supports filename, remote path, file size, modification date, and
first-indexed date. Results are paginated and no endpoint loads the complete
index into memory.

## Crawler behavior

The crawler uses the FTP `MLSD` command so it can collect file metadata without
requesting contents. Each directory is a durable queue record. A successful
directory listing is processed in batches and committed before moving on.

Both “full” and “incremental” modes retain existing rows and upsert current
metadata. A full scan provides an explicit new whole-tree run; an incremental
scan performs the same authoritative traversal without clearing the index.
This is necessary because standard FTP provides no reliable server-wide change
feed.

Directories that cannot be accessed are logged and skipped so one permission
problem does not abort the entire tree. A fatal failure leaves remaining queue
records intact and exposes **Resume scan**.

The crawler requires `MLSD`, which is supported by modern FTP servers. A server
that only supports legacy `LIST` will log an error for each inaccessible
listing rather than attempting unreliable locale-dependent parsing.

## REST API

Interactive OpenAPI documentation is available at `/docs`; the machine-readable
schema is at `/openapi.json`.

Main endpoints:

- `GET /api/search`
- `GET /api/files/{id}`
- `GET /api/dashboard`
- `GET /api/scans/status`
- `POST /api/scans`
- `POST /api/scans/stop`
- `POST /api/scans/resume`
- `GET /api/logs`
- `GET /api/settings`
- `PUT /api/settings`

When administrator authentication is enabled, first sign in through `/login`.
State-changing endpoints also require the current session CSRF value in the
`X-CSRF-Token` header. The browser interface handles this automatically.

## Database and backups

SQLite runs in WAL mode with foreign keys and a busy timeout. FTS triggers keep
the search index synchronized with metadata rows.

To back up while the stack is running, use SQLite's online backup command from
inside a temporary container or stop both `web` and `crawler` before copying the
database and its `-wal` file. The simplest consistent backup is:

```bash
docker compose stop web crawler
docker run --rm \
  -v ftp-indexer-data:/source:ro \
  -v "$PWD/backups:/backup" \
  alpine cp -a /source/. /backup/
docker compose start web crawler
```

## Operations

View health and service state:

```bash
docker compose ps
docker compose logs --tail=100 web crawler
```

Apply a future migration after updating the source:

```bash
docker compose run --rm migrate
```

Rebuild and restart:

```bash
docker compose up -d --build
```

## Local development and tests

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
mkdir -p var/data var/logs var/config
DATABASE_URL=sqlite:///./var/data/ftp-index.db \
LOG_DIRECTORY=./var/logs \
CONFIG_DIRECTORY=./var/config \
alembic upgrade head
DATABASE_URL=sqlite:///./var/data/ftp-index.db \
LOG_DIRECTORY=./var/logs \
CONFIG_DIRECTORY=./var/config \
python -m app.run_web
```

Run checks:

```bash
pytest
ruff check app tests
```

Use a separate development `.env` or explicit environment overrides. Never
commit real FTP credentials.

## Security notes

- The checked-in example has no real credentials; `.env` is Git-ignored and
  excluded from Docker build context.
- The local administrator password is stored as an Argon2 hash in SQLite.
- Session cookies are signed, `SameSite=Strict`, and can be marked secure.
- State-changing browser/API requests require a per-session CSRF token.
- Paths are normalized, null bytes and injected separators are rejected, and
  traversal outside `FTP_ROOT_PATH` is refused.
- FTP, administrator, and session secrets are redacted from stored errors.
- The image runs as an unprivileged user.
- No API accepts shell commands or downloads remote file contents.
