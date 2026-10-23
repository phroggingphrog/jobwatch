# Jobwatch with vanilla LibreChat

LibreChat and the website are separate clients of Jobwatch's authoritative native
backend. The optional OpenAI wire adapter forwards conversation turns to durable
Jobwatch runs; it does not add a second supervisor. Jobwatch owns evidence,
identity, model routes, budgets, approval and confirmed submission.


## Current deployment direction (2026-10-24)

Use vanilla LibreChat and the standard configuration in [librechat.yaml](librechat.yaml).
Preserve existing volumes and configuration for unrelated endpoints, MCP servers,
agents and skills. Remove only Jobwatch-specific enrollment, automatic-card settings
and MCP preset attachments. Keep the independent Jobwatch website and backend.

Enable `JOBWATCH_UI_FORMAT=artifacts` on the backend. The bot endpoint receives original
file bytes in standard OpenAI-compatible content parts and grants read/run scope to a
trusted server credential plus its authenticated subject. The existing identity registry
preserves the owner mapping and isolates other accounts. The client stores no Jobwatch
human credential. Routine profile answers update the unconfirmed draft directly. The backend
shows the exact profile and search scope in chat and accepts an explicit reply from the
authenticated user against that review. Preserve the preceding assistant review in conversation
history when forwarding the reply. Corrections or changed inputs require another review.
Native interaction controls remain an alternative over the same operation. Native Artifacts
provide local interactive previews; they carry no approval authority and cannot fill an employer
form or Submit. Other gated operations remain paused without their required human review.

Configure attachment delivery as `provider` for Jobwatch, with MIME types `.*` and the
10 MiB aggregate/20-file limit in the sample. Receipt and reading are separate: arbitrary
originals are retained, known documents/ZIP members become unconfirmed intake evidence,
and unsupported or corrupt content receives an explanation within the conversation.

Before rollout, run the required local checks, an independent review and a synthetic
vanilla-client upload/Artifact journey. Pin the official image digest, back up active
configuration and record the backend revision. Restart only the authorized chat/API
services, retain all current data and provide a rollback to the saved image/configuration.
Do not run the historical whole-backend rollback to change only the chat frontend.

The following sections describe the previous custom-client installation and its
historical verification. They are retained for rollback context; they do not override
this vanilla-client direction.

## Historical custom-client release and private configuration

1. Use an isolated checkout. Install existing locked dependencies with
   `uv sync --frozen --extra dev --extra browser --extra mcp`. Run the required
   local release checks: `uv run --no-sync python -m pytest -q` and
   `jobwatch check --code` against the intended runtime. Record missing onboarding
   facts separately. Hosted CI stays disabled.
2. Keep runtime data and credentials outside Git with private directory/file
   permissions (0700/0600). Preserve existing data and take consistent SQLite
   backups before rollout. Set `JOBWATCH_DATA_DIR`, `JOBWATCH_DB`,
   `JOBWATCH_PROFILE_DIR`, `JOBWATCH_CAREER_DIR` and `JOBWATCH_CONFIG_DIR`
   explicitly for the intended runtime. Do not reset a profile during an update.
3. Retain the approved paid gateway, credential index, configured model routes,
   reasoning router, budgets and Qwen embedding route. Disable hosted tracing.
   Development `cross-model.json` is not runtime model configuration.
4. Keep separate read/run and human-action credentials. Enable
   `JOBWATCH_LIBRECHAT_ENABLED=true`, `JOBWATCH_MCP_APP_ENABLED=true` and
   `JOBWATCH_NATIVE_BROWSER_ENABLED=true`. Set `JOBWATCH_AGENT_PUBLIC_URL`
   to the existing HTTPS Jobwatch origin and `JOBWATCH_APP_ORIGIN` to LibreChat's
   HTTPS origin. Bind the native API and MCP app to loopback (18914/18918 by
   default); containers can use private authenticated bridge forwards.
5. Generate `JOBWATCH_LIBRECHAT_IDENTITY_KEY` server-side and configure the same
   secret in Jobwatch and LibreChat's private environment. Pin
   `JOBWATCH_LIBRECHAT_OWNER_SUBJECT` to the existing owner's authenticated
   LibreChat subject before enabling enrollment. Other signed-in accounts are
   provisioned atomically as separate people. Users never enter or share
   Jobwatch keys. Credentials remain encrypted/server-side; model and client
   text cannot select a person or grant human authority.
6. Deploy the backend/browser owner before enabling automatic cards. The optional
   `jobwatch-mcp-app` process uses the same checkout, identity mapping and native
   runtime (`JOBWATCH_NATIVE_URL=http://127.0.0.1:18914`). Configure the website's
   `JOBWATCH_NATIVE_BROWSER_URL` to use the shared loopback owner. The website
   remains independently usable; do not require its pages for chat workflows.
7. Merge [librechat.yaml](librechat.yaml) into the existing configuration of a
   LibreChat build supporting Jobwatch account enrollment and automatic MCP Apps.
   Replace example URLs/bridge addresses. `JOBWATCH_AGENT_BASE_URL` includes
   `/v1`; `jobwatch.baseUrl` names the native root without `/v1`.
   `apiKey: user_provided` is the endpoint's storage mode: authenticated server
   enrollment fills it automatically. Keep the declared `customUserVars`: LibreChat
   uses them to load the enrolled encrypted MCP values. Users do not fill them in.
   Keep the explicit enrollment timeout/cache settings: not every LibreChat
   configuration consumer applies schema defaults at runtime.
8. Record source revisions, image IDs, configuration backups and an executable
   rollback before restarting services. Source changes alone never activate a
   service. Keep isolated legacy services stopped/masked as requested.

## HTTPS and sandbox routing

Route Jobwatch `/agent`, `/agent/*`, `/api/agent/*` and `/v1/*` to the native API
behind the existing access policy. Keep the independent website on its own route.
Do not publish native bearer listeners or browser debugging ports broadly.

On the LibreChat hostname, forward only
`^/api/agent/client/(upload|download|browser/action)$` to the native API; other
paths continue to LibreChat. Upload/download and browser controls use bounded
capabilities. Uploads bind the person, filename, kind, byte count and SHA-256;
browser controls bind one person/application/session for five minutes and cannot
Submit. The applicable capability endpoints accept sandbox `Origin: null`;
ordinary native bearer routes gain no cross-origin access. Uploads use a simple
POST capability envelope and retain the 10 MiB limit. File contents never enter
model tool arguments. Normal LibreChat attachment uploads are enabled for Jobwatch.
The authenticated LibreChat server resolves the attached file IDs against the owner's
stored files, streams their original bytes into native intake, and sends the resulting
person-bound IDs through `X-Jobwatch-Uploads`. Apply the matching LibreChat bridge and
the header in `librechat.yaml` together. The host retains its attachment chips while
the model receives native upload references rather than file contents. Intake remains
authoritative; an upload neither confirms profile facts nor approves an operation.

Serve only `/api/mcp/sandbox` on a dedicated sandbox hostname from LibreChat;
return 404 elsewhere on that hostname. Set LibreChat's
`MCP_SANDBOX_FRAME_ANCESTORS=https://<librechat-host>`. The sandbox must have a
different origin from the chat. Preserve the existing Access policies.

## Conversation controls

Choose the Jobwatch preset and ask to set up your profile. Routine Q&A and onboarding
questions stay in plain chat. Generated interfaces serve explicit interactive requests
or useful evidence displays. Requested canonical views, model settings, application
review and required human decisions retain native cards; these open automatically
when requested and earlier cards collapse. Other MCP servers keep their existing
behavior. Failure summaries stay inside chat;
the website is never the fallback. Historical messages retain their saved
resources; new views identify their current bundle with a versioned resource URI.
Refreshing or reopening a card does not start paid work or reuse an approval.

Use LibreChat’s top model selector under **Jobwatch** to choose a configured
gateway model. The authenticated server saves that explicit global choice for
your account before the next message; the backend accepts only your saved model
or the legacy `jobwatch-agent` adapter label. Keep `models.fetch: true` so the
selector loads the gateway catalog. Keep `interface.modelSelect: true` and
`modelSpecs.enforce: false` so normal provider/model navigation and provider
API-key dialogs remain accessible. This does not expose Jobwatch credentials or
change other providers’ API-key controls.

Use the card’s **Models** controls to select configured names for all tasks or individual roles,
then **Save models** and confirm. New choices affect new work; embeddings and
canonical route restrictions remain unchanged. Unsaved fields/selections survive
reconnects. The `jobwatch-agent` endpoint label names the backend adapter, not
its underlying role models.

Human mutations retain LibreChat's host-owned confirmation with exact arguments
under details. Model tools, assistant text and typing “approve” do not consume a
human approval. Documents expose verified previews/downloads and separately
approved revisions. Browser controls allow scoped corrections/login where
supported. The application card must show actual form values, destination and
attachments before separately confirmed final Submit through
`jobwatch/apply/submit_confirm.py`. Changed forms, expired/single-use approvals
and unsupported review state block submission. An uncertain receipt is never
retried automatically.

## Verification status and remaining acceptance work

Record the actual checks for each release; source tests alone do not prove a
public deployment. The 2026-10-23 backend release passed 3830 tests with 10 skips.
Public authenticated checks observed two isolated accounts, automatic cards,
upload/parse/profile confirmation, model changes and native approval handling.
The original screenshot's loading timeout was not reproduced.

**Full public application acceptance remains incomplete.** The controlled
synthetic listing was correctly archived because it explicitly was not a real
vacancy. Eligible selection, preparation, document delivery, live browser review
and final synthetic Submit were not reached in that public journey. Do not
weaken production eligibility, fabricate READY packages or repeatedly spend on
reassessment to force the test through. Complete these scenarios with a separate
controlled test setup and synthetic data, including changed/expired approvals,
duplicate clicks, uncertain receipts and unavailable browser/model cases. No real
employer applications may be submitted during verification.

## Rollback

Restore the recorded previous backend revision, LibreChat image and private
configuration, then restart only the fresh deployment's services. Keep current
data/volumes; restore a database backup only for a separately justified recovery.
Undo only proxy rules and runtime overrides introduced by that release. Preserve
unrelated routes/policies and never unmask legacy units as a rollback side effect.
Temporary public QA routes, Access tokens/policies and synthetic form servers must
be removed after their bounded checks.
