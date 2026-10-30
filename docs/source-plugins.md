# Add a source

User sources live outside the repository in `<Jobwatch data>/config/sources/`. Add definitions to `sources.yaml`. Collection uses shared HTTP controls, validates every result, and continues after a source error. Python plugins are trusted code and run with your permissions.

## Declarative RSS example

```yaml
sources:
  - name: melbourne-example
    kind: declarative
    enabled: true
    feed_type: rss
    url: https://jobs.example.org/feed.xml
    respect_robots: true
    min_interval_seconds: 2
    max_pages_per_run: 2
    cache_enabled: true
    cache_ttl_seconds: 300
    company: Example employer
    mapping:
      title: title
      url: link
      description: summary
      posted_at: published
      id: id
```

For JSON, set `feed_type: json`, `items_path` to a list path, and field mappings to paths. For HTML, set `feed_type: html`, `item_selector`, and mappings with selectors and optional attributes.

## Python example

Save this file as `<Jobwatch data>/config/sources/example.py`:

```python
from jobwatch.models import Posting

NAME = "example-python"
VERSION = "1.0"
FIELDS = ("title", "url", "company")

def collect(context, options):
    text = context.http.get_text(options["url"])
    return [Posting(
        source=NAME,
        source_id="example-1",
        title="Example role",
        url=options["url"],
        company="Example employer",
    )]
```

Enable it with this definition:

```yaml
sources:
  - name: example-python
    kind: python
    enabled: true
    file: example.py
    respect_robots: true
    min_interval_seconds: 2
    max_pages_per_run: 2
    timeout_seconds: 20
    cache_enabled: true
    cache_ttl_seconds: 300
    options:
      url: https://jobs.example.org/job/1
```

A plugin returns `list[Posting]`. Each posting needs a title, HTTP(S) URL, source ID, and company. Jobwatch reports the plugin name and exact validation or runtime error. Python plugins are not sandboxed; install only code you trust.

## Checked feeds

Cardinia Council returned valid RSS XML. La Trobe's configured URL and 4 likely replacements returned 404. RMIT's checked path returned HTML with 404. Monash's checked path returned 403. Jobwatch did not add those failed feeds.
