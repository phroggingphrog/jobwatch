# Source plugin design

## Current registration

`jobwatch.collectors.__init__` names built-in modules in `COLLECTORS`. `get()` imports a named module, and `jobwatch.run` calls its `collect(cfg, since)` function. Each collector receives `CollectorContext`, uses its shared `Fetcher`, returns `list[Posting]`, and reports source-specific errors through `cfg.error(where, reason)`. The first implementation keeps existing collectors unchanged and adds a plugin registry path beside them.

## Plugin contract

Each plugin exposes `NAME: str`, `VERSION: str`, `FIELDS: tuple[str, ...]`, and `collect(context, options) -> list[Posting]`. The context contains the shared HTTP client, source options, page budget, and a per-run response cache. Plugins report failures by raising an exception; the host catches each source failure and records `plugin name: exact reason` through the collector error list. A failed plugin cannot stop another source.

Before accepting results, the host checks that the return value is a list of `Posting` instances and validates required posting fields: non-empty title, URL, source ID, and employer/source identity; the URL must be HTTP(S). Invalid output produces a clear error naming the plugin and the invalid field or result type. The declared `FIELDS` must be a subset of supported `Posting` fields and must include title and URL.

## Discovery and configuration

Built-ins are registered explicitly by the Jobwatch package. User plugins are discovered only from the active user's configuration folder, under `sources/plugins/`; Python files are loaded from that directory by an explicit module path in source configuration. Declarative definitions live in `sources/sources.yaml` in the same folder. The folder is outside the repository, under the user's Jobwatch config directory. A configured source has a stable name, `enabled`, `kind`, and options. Each source can set `respect_robots` (default `true`), `min_interval_seconds` (minimum 2), `max_pages_per_run`, `timeout_seconds`, and cache settings (`cache_enabled`, `cache_ttl_seconds`). The host supplies these controls to the shared HTTP client; plugins cannot make direct network calls through the contract.

A declarative source sets `kind: declarative`, `url`, and `feed_type` (`rss`, `atom`, `json`, or `html`). RSS and Atom mappings name output fields and feed element paths. JSON mappings use JSON paths. HTML mappings use CSS selectors. The parser fetches pages through the shared client, respects the configured page cap, and maps entries to validated postings. A Python source sets `kind: python` and a plugin file path. Python plugins are trusted code. They run with the permissions of the user and are not a sandbox.

## Shared request controls and isolation

The host creates one shared HTTP client for a collection run. It enforces the honest Jobwatch User-Agent, per-host minimum interval, timeout, bounded retry policy, cache, robots policy, and per-source page budget for every plugin request. Requests use no proxies. Each plugin runs with a deadline; a timeout becomes a source error and does not stop other sources. The plugin interface exposes only the shared client for HTTP access. Python is not a security boundary, so trusted plugins can still access user permissions outside that interface.

## First plugins and migration

GradConnection and generic RSS/Atom collection are the first two built-in plugins. Its regional `robots.txt` returned 200 and allows all paths except tracking, calendar, and university paths. The checked listing path `/graduate-jobs/` returned 200. Therefore the built-in source defaults to `respect_robots: true`; no exception is needed for that path. Existing La Trobe and Cardinia collectors remain untouched in this change. The configured La Trobe URL returned 404, and 4 likely replacement paths also returned 404; no replacement is confirmed. Cardinia RSS returned valid XML with 8 parsed items. RMIT's checked path returned HTML with 404, and Monash's checked path returned 403. These were the only 4 public feed URL checks. Later, each existing collector can implement this interface and move behind the plugin registry one source at a time, with its parser and fixtures retained and its current error and health behavior preserved.
