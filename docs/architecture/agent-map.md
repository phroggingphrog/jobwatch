# Jobwatch agent map

**Source snapshot:** feature branch from `a16658f24ccc0acffaad0de1cd2006f03d982ce3`, inspected 2026-11-01, then reconciled with `main` at `e2499a7` (PR #60) for the execution modes and candidate-intent routing. Other sections, including the service and release path, still describe the original inspection. This map describes source behavior. It does not claim that the checkout is deployed or that every path has passed live acceptance.

**DeepWiki:** The web tool could not retrieve `phroggingphrog/jobwatch`. `deepwiki_ask` returned “Repository not found”; `deepwiki_structure` returned the same result. The repository is private or not indexed. No Jobwatch DeepWiki source pages or citations are available. The requested DeepWiki URL is [https://deepwiki.com/phroggingphrog/jobwatch](https://deepwiki.com/phroggingphrog/jobwatch), but it does not provide verified coverage. This map uses checked-out source and runtime metadata instead.

## Summary

Jobwatch has 2 orchestration paths: the deterministic collection pipeline and the native Career Ops agent service. A third legacy graph remains selectable. The native service owns durable runs, assessment, evidence-bound package creation, and eligibility gates. LangChain supplies model and tool interfaces. Deep Agents runs scoped tool graphs. LangGraph supplies persistent chat state and human interrupts. These frameworks do not own identity, eligibility, approval, or Submit authority.

The product intent in `INTENT.md` sets a reliable Screening → Evaluation slice as the priority. The current source contains a native evaluation graph and deterministic prescreen. It does not establish successful end-to-end provider acceptance or production use of every feature. Framework plans or listed skills do not prove an implemented, exercised workflow.

## Entrypoints and orchestration

- `jobwatch/cli.py` dispatches collection, reading, web, MCP and management commands. `jobwatch/execution_mode.py` selects `off`, `reader`, `pipeline`, `agentic`, or `screened` behavior.
- `jobwatch/pipeline.py` runs collectors, normalizes and saves postings, then invokes the selected assessment hook unless the run is collect-only. The fast and slow collection timers are separate from the native agent API.
- `pipeline/graph.py` and `pipeline/nodes/` implement a deterministic staged alternative. `pipeline/store.py` and `pipeline/schemas.py` own shared stage, event, and dead-letter state. The agent service and website also use this substrate.
- `pipeline/agentic/service.py` implements automatic assessment and preparation. It captures a saved posting and full ad, makes input-bound run keys, checks prescreen and candidate digest, checks public ad safety and liveness, runs evaluation, applies the canonical gate, and optionally creates reviewed application documents. It records runs, artifacts, budgets, incidents and stage changes.
- `pipeline/agentic/chat.py` exposes an interactive chat agent. Its tools call existing Jobwatch operations; chat is not a second eligibility engine.
- `pipeline/agentic/autonomous.py` contains the newer native Evaluation graph for configured autonomous evaluation. The older role-based evaluator path remains available. Do not equate the presence of this code with live provider acceptance.

## Agent and specialist roles

Role executors in `pipeline/agentic/runtime.py`, `evaluator.py`, `draft.py`, `review.py`, `candidate_digest.py`, `discovery.py`, `company_research.py`, `interview.py`, and `followup.py` are bounded domain operations. Their completion schemas and tools are explicit. The main agent does not gain domain authority from a role prompt.

The native evaluator in `autonomous.py` uses a constrained Deep Agent tool graph and a typed completion boundary. Candidate understanding in `candidate_digest.py` prepares reusable, profile-bound understanding before personal prescreen when enabled. `evaluator.py` provides the existing requirement extraction, evidence matching and evaluation roles for the compatibility path. `draft.py` and `review.py` prepare and check documents using approved evidence and the full ad. `company_research.py`, `research.py`, and `interview.py` read public sources or prepare cited material. `followup.py` prepares drafts from recorded history; it does not send them. `discovery.py` provides occupation hypotheses, search planning and optional full-ad relevance checks. These are implemented operations, but not proof of successful runtime use or completed acceptance.

`deepagents_runtime.py` adapts the existing approved gateway to LangChain and Deep Agents. It disables general-purpose delegation and summarization for this profile, replaces filesystem access, restricts tool calls to each role registry, and routes all model calls through the bounded Jobwatch budget. `langgraph_entry.py` and `chat_storage.py` provide chat graph persistence. `chat.py` includes private middleware and approval-bound tools. Model-generated tool text cannot assert a candidate fact or approve an operation.

## Chat tools and adapters

`chat.py::_build` defines the interactive conversation tool set. It includes read operations such as `inspect_job`, `find_jobs`, `application_status`, `source_health`, `research_company`, `candidate_paths`, `preference_insights`, `callback_insights`, `read_reference`, `read_evidence`, `task_status`, `jobs_overview`, and `submit_status`. It also defines gated actions such as `assess_job`, `prepare_application`, `run_career_ops`, `revise_application`, `prepare_interview`, `draft_followup`, `submit_application`, and profile onboarding operations. `stop_work` removes queued authority. Tools call canonical services and person-scoped databases.

`pipeline/agentic/api.py` exposes the native authenticated HTTP API. It uses durable per-person runs and typed interactions, separate `read`, `run`, `interact`, and `approve` scopes, cancellation, retry, SSE events and artifacts. `profile_api.py`, `discovery_api.py`, `shortlist_api.py`, `feedback_api.py`, and `browser_api.py` mount typed operations. Optional LibreChat and compatibility client routes depend on environment flags.

`pipeline/agentic/mcp_server.py` exposes authenticated MCP. The chat tools are `career_ops_start_chat` and `career_ops_continue_chat`; read tools include `career_reader`, `followup_history`, and `discovery_status`. It also registers onboarding operations and `chatgpt_connector` tools. Identity comes from a verified static token or verified Cloudflare Access assertion. MCP elicitation carries human questions and approvals in encrypted, principal-bound, short-lived request state. Its host adapter does not turn model text into an approval.

`pipeline/agentic/acp_agent.py` adapts chat to ACP. It exposes no filesystem or terminal capability and maps approvals to client permission requests. `pipeline/agentic/tui.py` is a terminal chat client with local feed, approval and review screens. It calls `chat.dispatch` directly and uses existing gates. `pipeline/agentic/chatgpt_connector.py` registers ChatGPT-compatible tools and a widget resource. `pipeline/agentic/mcp_client.py` can wrap configured external MCP tools; it does not give those tools canonical authority.

## Data flow

1. Collectors from `jobwatch/collectors/` fetch listings. `jobwatch/pipeline.py` normalizes, deduplicates and saves them in each person's Jobwatch database.
2. `jobwatch/prescreen/engine.py` parses saved title, location, work type and ad text using database terms. `jobwatch/prescreen/sync.py` projects confirmed profile policy into database rules. `pipeline/nodes/ingest.py` checks listing metadata before full-ad retrieval and rechecks the full ad. Obvious matching exclusions can archive before paid model work. Ambiguous matches flag or admit.
3. Optional discovery relevance, occupation ranking and semantic dedupe use the configured reference data, embeddings and limited model extraction in `pipeline/agentic/discovery.py`. These are separate from the deterministic prescreen and are configuration-gated.
4. The agent service binds evaluation to the posting, full-ad hash, approved evidence, profile/policy, settings, prescreen rules and model configuration. `candidate_digest.py` prepares reusable candidate understanding on the native path. Public ad screening by Jev sees ad text, not candidate evidence.
5. The evaluator extracts requirements and matches them to approved evidence with citations. `gate.py` and canonical eligibility services decide the authoritative outcome. Model scores alone do not decide eligibility.
6. Approved preparation creates a reviewed CV, letter and form map. Package state is stored in the per-person database and immutable artifact directory. Browser auto-fill stops at review.
7. A separately confirmed Submit request binds the reviewed package, form contents, browser session and final control. `jobwatch/apply/submit_confirm.py` queues the request; the browser-owning web path rechecks the exact live form before pressing. A changed or expired form is refused. Draft follow-up and interview tools do not contact third parties.

## Data stores and authorization

- `jobwatch/db.py` stores postings, ad capture, collection state and prescreen tables. `jobwatch/users.py` names the single owner and refuses any other principal. Profile and evidence services read the owner's approved, versioned data.
- `pipeline/agentic/store.py`, `persistence.py`, and `private_sqlite.py` store bounded run claims, budgets, checkpoints, artifacts and package status. `api_store.py` stores API threads, runs, interactions, events and artifact references. Chat state and advisory memories live in the owner's private store.
- `pipeline/agentic/identity.py`, API credentials, MCP token verification and `users.require_owner` bind the server-side identity. Requests cannot select another person through a free-form `person` field; non-owner credentials and adapter persons refuse startup.
- `pipeline/agentic/chat.py` binds approval to operation and exact inputs. Native HTTP scopes separate reading, work, interaction and approval. MCP binds encrypted interaction state to principal and operation. ACP and TUI map person approval to explicit user actions.
- Candidate data uses approved paid routes. Hosted tracing and arbitrary tool filesystem access are restricted. Public research is separate from candidate evidence.
- Model proposals are not human decisions. Application preparation is not Submit. Only `submit_confirm` carries final Submit authority after an exact human approval and live-state recheck.

## Service and release path

Current user services observed on 2026-11-01 include `jobwatch-agent.service`, `jobwatch-mcp-app.service`, `jobwatch-connector-http.service`, `jobwatch-native-web.service`, `jobwatch-native-fast.timer`, and `jobwatch-native-slow.timer`. At inspection, the agent, MCP app, connector and native web units were active; fast timer was active with its service starting; slow timer was waiting. This is runtime metadata, not proof that a given assessment feature ran successfully.

The source templates in `systemd/` still point to `%h/apps/jobwatch`; they do not by themselves describe the active service configuration. The user-unit `ExecStart` values observed for native web, agent and MCP point to `/home/phroggingphrog/apps/jobwatch-release/.venv/bin/...`. That `jobwatch-release` symlink resolves to `/home/phroggingphrog/projects/.worktrees/jobwatch-release-65ad6c10a307`, source revision `65ad6c10a307c9cfd533f10a794f3f8679b31ff5` dated 2026-11-01. The release worktree was clean and detached. It differs from the source checkout revision `a16658f` inspected for this feature.

`deploy/release.sh <sha>` builds an isolated release worktree under `~/projects/.worktrees/jobwatch-release-<sha>`, performs an import check, and atomically repoints `~/apps/jobwatch-release`. `deploy/README.md` says timers use that release copy. This task does not authorize or perform a deployment, service restart or timer change. The active service arguments and deployed source revision were checked before source edits.

## Database-driven prescreen versus owner requirements

The owner asked for obvious keyword filtering backed by a database vocabulary, rather than an expensive model deciding basic location, seniority, employment type or work-rights constraints. Current source implements that shape: `prescreen_terms`, `prescreen_rules`, `prescreen_overrides`, and `prescreen_decisions` are per-person database tables. The generic engine does not contain per-field term lists. Seed words are versioned data; confirmed profile policy is projected to rules. Metadata screening precedes ad fetch, and full-ad screening precedes evaluation. Only an obvious hit under a skip rule stops work; weak or uncertain evidence flags. Overrides and rule hashes support re-admission after changes.

The term bank includes seniority title terms, location and remote handling, work type, hours, citizenship, clearance and sponsorship phrases. Confirmed candidate facts control the rule effect; unknown work rights are not invented. Since PR #60, `jobwatch/candidate/intent.py::normalize_intent` separates confirmed facts into preferences, explicit constraints, work rights and ambiguities before policy and eligibility read them. A goal or preference is advisory and does not exclude a posting; only an explicit constraint, an exclusion or a work-rights fact can. This matches the owner's database-driven deterministic prescreen requirement. It does not establish complete lexical coverage or accuracy for every occupation, market or phrasing. A person can extend the bank with the prescreen CLI and inspect counts.

A concrete reliability defect existed in `jobwatch/prescreen/lifecycle.py::reconsider`: a missing posting row reached `row.keys()` because of conditional-expression precedence, aborting the reconsideration batch. The fix now skips the missing row safely. A new regression test creates an orphaned archived prescreen state and checks that reconsideration completes. The normal database foreign-key cascade may make this state uncommon; its production reachability is not established.

Other scope boundaries remain explicit: the legacy `jobwatch/filters.py` fallback is not wholly database driven when no confirmed profile policy exists; optional semantic discovery uses separate configuration and can use paid embedding or extraction work; terms can miss unseeded synonyms; and no live quality or provider acceptance was verified here. The immediate approved scope is deterministic obvious screening, not adding a new architecture or imposing a new cost policy.

## Proposed, not proven implemented

`INTENT.md` proposes one reliable Screening → Evaluation slice with deterministic screening, reusable candidate understanding, cited evaluation, eligibility, measured cost, and unchanged-input reuse. Some source supports these functions. Runtime evidence does not prove end-to-end native evaluation acceptance. Broader Career Ops stages such as preparation, interviews and follow-up have code, but their presence does not prove complete accepted delivery. Deep Agents planning or specialist concepts do not create separate domain services or authority.

## DeepWiki links

- Requested repository: [https://deepwiki.com/phroggingphrog/jobwatch](https://deepwiki.com/phroggingphrog/jobwatch) — unavailable; query and structure calls reported repository not found.
- Search URL: [https://deepwiki.com/search/](https://deepwiki.com/search/) — no Jobwatch-specific result or source page was returned. No DeepWiki claims are used in this report.
