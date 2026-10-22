# Jobwatch glossary

This is the single glossary for Jobwatch's career-operations domain.

| Term | Meaning |
|---|---|
| Person | The server-authenticated owner of a private profile, evidence, conversations and artifacts. |
| Posting | A saved job opening identified by a posting ID. Its full ad is evidence to inspect. |
| Canonical evidence | Approved source material supporting personal claims; model memory is not a substitute. |
| Thread | A person's durable conversation and its LangGraph checkpoints. |
| API run | One admitted conversation invocation, identified independently from a job attempt. |
| Job attempt | Canonical processing of a posting against captured inputs, identified by its run key. |
| Interaction | A pending human question or approval, bound to the relevant checkpoint and inputs. |
| Approval | A trusted human decision permitting the specified work; only a `submit_application` approval of an exact reviewed fill authorizes final Submit. |
| Package | The persisted application documents and associated verified artifacts for a job. |
| READY | A current package has met the authoritative eligibility, factual and document gates. |
| Held / archived | Saved domain outcomes explaining why a job has stopped or been excluded. |
| Deferred | Work was not admitted or could not proceed now; report the reason and next eligible time when known. |
| Skill | Packaged workflow instructions loaded by the agent; it contains no private candidate facts. |
| Memory | Per-person advisory context; it does not edit approved evidence or override domain gates. |
| Submit | The final application action: the owner's own click, or Jobwatch pressing it for an owner-confirmed, unchanged fill. |
| Company research | The saved ad's explicit skills/duties plus cited public employer context; inferences stay labelled and cannot introduce mandatory requirements. |
| Structural proximity | A 60/40 activity-coverage/cosine measure; not a qualification or hiring probability. |
| Preference prediction | A validated owner-choice probability within an already answered set of three eligible jobs plus none. |
| Callback estimate | Historical Beta-Binomial callback rate and uncertainty, distinct from a forecast for a particular job. |
| Proposal | A private, parsed draft of a person's profile facts and open questions, revised by the person; not authoritative until confirmed. |
| Approved profile | The facts and search scope the person confirmed, stored as a profile version and projected into `profile/`. |
| Profile version | An immutable `profile-versions/<n>/` record of one confirmation or adoption, with its evidence snapshots. |
| Fact basis | Whether a proposed fact is `evidence`, `inference` or `unknown`; a CV gap alone never establishes unemployment. |
| Search scope | The confirmed basis, locations, daily assessments and daily token ceiling within which discovery and assessment may run. |
| Frozen baseline | An immutable per-person snapshot of the pipeline's stored inputs and outputs, with gate routes recomputed under a pinned profile, used for like-for-like comparison. |
| Frozen case | One posting's inputs, outputs, group, tags and usage inside a baseline. |
| Gate version | A sha256 over the gate's source files; it changes by itself when the gate changes. |
| Owner label | The owner's own suitability, relevance or exclusion judgment of a frozen case; never produced by a model. |
| Decision policy | The search strategy, exclusion rules, eligibility constraints and open questions derived from the approved profile's `evidence` facts, separate from `TargetPolicy`. |
| Search strategy | How discovery is aimed for a person, derived from the confirmed profile by five rules: employment-first, explicit focus first, exclusions as rules, ask when material, update on change. |
| Exclusion rule | A confirmed `{"kind", "value"}` exclusion that the gate enforces and that carries its `source_fact_id`; a free-text exclusion is not one until the person names its kind. |
| Eligibility constraint | A work-rights or hours limit the person stated and confirmed, kept as a genuine constraint apart from preferences. |
| Open question | A fact the policy needs but does not have as `evidence`, such as `exclusion:<fact_id>`; it is asked, never answered by the agent. |
| Policy flag | `pipeline.agentic.decision_policy`, with values `legacy` (default) and `profile`, choosing the legacy checks or the confirmed-profile policy. |
| Field hypothesis | A related occupation found by semantic retrieval from approved facts, used as a search hypothesis; never proof of qualification. |
| Reference dataset | Public, versioned, hash-verified occupation data under `<data>/reference/`. |
| Search plan | The queries and locations collectors use, derived from field hypotheses and the decision policy. |
| Relevance judgment | A stored yes/no/uncertain verdict on whether a posting's full ad belongs to the person's fields, with verbatim quotes. |
| Recall pre-screen | Title keywords that may only add postings for detail fetching, never exclude one from the semantic step. |
| Semantic duplicate | The same vacancy listed by different sources, found by description similarity plus company, title and city agreement. |
