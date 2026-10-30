from jobwatch.models import Posting

NAME = "fixture-plugin"
VERSION = "1.0"
FIELDS = ("title", "url", "company")

def collect(context, options):
    context.http.get_text(options["url"])
    return [Posting(source=NAME, source_id="fixture-1", title="Fixture role",
                    url=options["url"], company="Fixture employer")]
