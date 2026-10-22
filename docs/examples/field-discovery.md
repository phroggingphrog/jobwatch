# Field and job discovery: synthetic workflow

Captured on 2026-10-22 from `tests/occupations/test_discovery_workflow.py` using a real confirmed synthetic profile, tiny invented occupation records and a deterministic fake embedding transport. The API, private caches, discovery ledger and CLI handlers are real. No live candidate records, model provider or employer were used. This proves plumbing, not matching quality.

The example deliberately sets `pipeline.discovery.similar_at` to **0.01** so the fake vectors exercise the embedding branch. The release default remains **0.60**; neither threshold is calibrated. The seven returned toy hypotheses include unrelated records with low similarity; they are search hypotheses, never qualifications or a useful-rank benchmark.

After confirmation, the explicit refresh command is:

```bash
python -m pipeline.agentic.discovery refresh --user fixture-a
```

The captured CLI response (the reference versions are synthetic) was:

```json
{
  "datasets": {
    "anzsco2022": "toy-1",
    "onet": "toy-1"
  },
  "hypotheses": 7,
  "plan_hash": "dcb77ddc58751fa6b6bce6695852de0b240451884d1dfcfab90617bc68b8d3d2",
  "profile_version": 1
}
```

An authenticated `GET /api/agent/discovery/fields` then returned the following excerpt. Six further hypotheses are omitted:

```json
{
  "hypotheses": [
    {
      "code": "13-2011.00",
      "is_qualification_proof": false,
      "rationale": "Closest approved facts: f1. Similarity 0.5345. Strategy balanced. A search hypothesis only; it is not evidence that you qualify.",
      "related": [
        "anzsco2022:221111"
      ],
      "scheme": "onet",
      "similarity": 0.5345,
      "supporting_facts": [
        "f1"
      ],
      "title": "Accountants and Auditors"
    }
  ],
  "note": "Related occupations are search hypotheses, not qualification proof.",
  "profile_version": 1,
  "status": "ready"
}
```

`GET /api/agent/discovery/plan` returned:

```json
{
  "flags": {
    "dedupe": "legacy",
    "ordering": "legacy",
    "relevance": "shadow",
    "search_plan": false
  },
  "plan": {
    "hypotheses": [
      "onet:13-2011.00",
      "anzsco2022:551111",
      "anzsco2022:811111",
      "anzsco2022:254411",
      "anzsco2022:261312",
      "anzsco2022:431111",
      "anzsco2022:551311"
    ],
    "locations": [],
    "plan_hash": "dcb77ddc58751fa6b6bce6695852de0b240451884d1dfcfab90617bc68b8d3d2",
    "policy_hash": "f47155aecec081e3d7e7dc612e5f2c4ece5defdb5edfdd8ad61619af43bf22b4",
    "profile_version": 1,
    "queries": {
      "jobspy": [
        "accountants and auditors",
        "bookkeeper",
        "cleaner",
        "nurse",
        "software developer",
        "barista",
        "payroll officer"
      ],
      "jora": [
        "accountants and auditors",
        "bookkeeper",
        "cleaner",
        "nurse",
        "software developer",
        "barista",
        "payroll officer"
      ],
      "seek": [
        "accountants and auditors",
        "bookkeeper",
        "cleaner",
        "nurse",
        "software developer",
        "barista",
        "payroll officer"
      ]
    }
  },
  "status": "ready"
}
```

Locations are empty because this synthetic profile supplied no confirmed location. Real overlays use the confirmed home and scope; only the first plan location is sent to Seek, Jora and JobSpy. Additional locations remain visible in the plan. A changed profile/policy or reference cache invalidates execution of an old plan; `/plan` labels a retained stale plan `stale`, and the fields view reports `not_computed` until refresh.

After a full invented advert was admitted and screened, `GET /api/agent/discovery/postings/1/relevance` returned:

```json
{
  "created_at": "2026-10-22T08:29:18+00:00",
  "judgment": {
    "ad_hash": "99518e8b9a9b76c20464a4100365499b19b61154b4394fb9243364b6518cbe37",
    "matched_hypotheses": [
      "onet:13-2011.00",
      "anzsco2022:551111",
      "anzsco2022:811111"
    ],
    "method": "embedding",
    "plan_hash": "dcb77ddc58751fa6b6bce6695852de0b240451884d1dfcfab90617bc68b8d3d2",
    "posting_id": 1,
    "quotes": [
      "Accountant reconciles supplier ledgers and prepares journals. Accountant reconciles supplier ledgers and prepares journals. Accountant reconciles supplier ledgers and prepares journals. Accountant reconciles supplier ledgers and prepares journals. Accountant reconciles supplier ledgers and prepares "
    ],
    "reason": "related_fields",
    "relevant": "yes",
    "similarity": 0.500489
  },
  "mode": "shadow"
}
```

The posting stayed `ingested` because this is shadow mode. The read endpoints made no embedding or chat calls. Status is a read-only local operation:

```bash
python -m pipeline.agentic.discovery status --user fixture-a
```

```json
{
  "counts": {
    "no": 0,
    "uncertain": 0,
    "yes": 1
  },
  "datasets": {
    "esco": {
      "licence": "unverified package licence; European Commission website reuse policy CC BY 4.0",
      "state": "disabled",
      "version": "1.2.1"
    },
    "onet": {
      "licence": "CC BY 4.0",
      "state": "missing",
      "version": "31.0"
    },
    "osca": {
      "licence": "CC BY 4.0",
      "state": "missing",
      "version": "2024-v1.0"
    }
  },
  "flags": {
    "dedupe": "legacy",
    "ordering": "legacy",
    "relevance": "shadow",
    "search_plan": false
  },
  "plan_hash": "dcb77ddc58751fa6b6bce6695852de0b240451884d1dfcfab90617bc68b8d3d2",
  "similarity": {
    "max": 0.500489,
    "median": 0.500489,
    "min": 0.500489
  }
}
```

O*NET and OSCA are `missing` here because no real public reference dataset was installed in the synthetic runtime. ESCO remains disabled until the owner acquires and verifies its current package; `--trust-on-first-use` alone cannot discover its email-delivered download links. To inspect or explicitly acquire the pinned public files on an approved install:

```bash
python -m jobwatch.occupations.datasets status
python -m jobwatch.occupations.datasets fetch onet
python -m jobwatch.occupations.datasets verify onet
python -m jobwatch.occupations.datasets fetch osca
```

These fetch commands were not run against a person's runtime during development. Hashes and schemas were investigated on separate public downloads; synthetic tests validate the fetch machinery.

| Flag under `pipeline.agentic` | Default | Effect |
|---|---|---|
| `search_plan` | `false` | Derived collector queries; may trigger a paid refresh on a live run. Dry collection does not refresh. |
| `relevance` | `shadow` | After refresh, stores judgments. Only `on` archives quoted `no` results; `off` disables screening. |
| `dedupe` | `legacy` | `semantic` uses description vectors plus source/company/title/location guards. |
| `ordering` | `legacy` | `hypotheses` uses field similarity while keeping five oldest jobs in the first twenty. |

Review shadow results alongside actual owner judgments before enabling `on`. Configure the other flags independently. Exclusion prefiltering additionally requires `decision_policy: profile`; FT/PT constraints remain in the complete-ad gate, while casual metadata can be prefiltered. Profile confirmation never authorizes document preparation, messages or submission. All embedding and relevance calls share confirmed daily limits and counted budgets; cache hits do not call a provider.

To undo discovery exclusions before disabling the feature:

```bash
python -m pipeline.agentic.discovery restore --user fixture-a
```

The captured fixture had no archived rows to restore:

```json
{
  "restored": 0
}
```

For a source rollback, revert the phase commit(s). Set `relevance: off` to stop shadow calls, restore archived `not_relevant`/`excluded_by_rule` rows first if desired, and return the other flags to their defaults. Additive tables `text_embeddings`, `posting_relevance`, `discovery_spend` and private `<person>/discovery/` caches can remain unused. If removing tables, back up the private DB first and preserve its other state; do not lower the migration version while keeping this release. Shared `<data>/reference/` contains public data only. Semantic `duplicate_of:<id>` archives are not restored by this command.

Live Qwen retrieval quality, relevance-model judgment quality, calibration and deployment remain unverified. No service or timer was activated.

Screening requires a saved ad classified as complete, but is a bounded pre-step:
embeddings use at most four 1,500-character windows (150-character overlap), and
model extraction receives the first 12,000 characters. Semantic dedupe uses those
same passage vectors. This does not establish that every passage of a long ad was
judged; the canonical assessment remains a separate operation.
