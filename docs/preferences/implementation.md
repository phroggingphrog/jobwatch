# Local owner preference learning

Owner words (verbatim): “how about the statistical model evaluator”; “fix it then”; “continue then”. BUI-288 authorizes the local implementation. This feature is supplementary preference learning inside the agentic career-ops system; it never replaces hard eligibility or predicts employer callbacks.

## Inputs and ownership

The protected owner board is the only source of genuine choices. Three freshly verified eligible agentic evaluations plus the explicit outside option are frozen into each set. The parent adapter must recheck the current ad, profile, evidence, configuration, run key and deterministic gate before calling `create_set`; hashes and boolean assertions are provenance, not independent authority. GET methods do not migrate, create choices or fit models. Protected POST handlers supply owner authority, origin checks and a stable request identifier. The core rejects other actors but does not authenticate an HTTP user itself.

SQLite sets, picks and fit records are append-only with update/delete triggers, transactional set/pick insertion, uniqueness, checked ownership and foreign keys. A conflicting replay never replaces an answer. Choosing none is `selected=None` with an answer timestamp, distinguishable from unanswered. Full set snapshots contain ad/evaluation/profile/run hashes, fixed feature values, feature/model/prior versions, and SHA-256 digests of the Python and R/JAGS sources. Source changes invalidate current data and fits; older snapshots remain inspectable. No automatic relabeling or migration hides that invalidation.

The training/holdout assignment is made before an answer: every fifth new independent set is holdout. A posting seen again inherits its original split; a triple spanning both splits is rejected. The fitting boundary additionally rejects any posting overlap. Minimums are 20 training and 5 heldout choices, explicitly a conservative operational floor rather than a power calculation. Sparse data remains insufficient/untrained. No historical synthetic or agent-generated scores become owner choices. Tests use a separately marked synthetic store; mixed origins are rejected and a synthetic fit cannot produce owner predictions.

## Model and assumptions

DAG: prior means → beta; mu_alpha, tau, alpha_raw → family intercept alpha; beta, alpha, observed job features → three utilities; utilities and a fixed zero outside utility → softmax probabilities → the explicit owner choice. This is the archived conditional-logit mechanism, with non-centred hierarchical family effects. It assumes conditionally independent sets and stable owner preferences within a context. The softmax has the usual independence-of-irrelevant-alternatives limitation. The sampling population is the already eligible job pool; this learner cannot infer preferences for excluded or unassessed jobs.

The original 17 coefficient names and prior directional means are preserved. Coefficients have Normal(prior_mean, SD 0.5) priors. Family effects use mu_alpha ~ Normal(0,1), tau ~ half-Normal(0,0.5), independent standard-normal raw effects and the archived accounting offset +0.5. Customer service has been removed from the model's family levels; customer service, hospitality, retail and shop-floor alternatives are rejected. Unmatched allowed families pool into the explicitly named other level; the source family remains in the snapshot.

Current schemas provide entry/program status, explicit part-time permission, remote-accessible status, and requirement matches. Coverage is the proportion of applicable stated critical/high/meaningful requirements with strong evidence matches; must-have gaps counts the remainder, including partial matches. No unstated requirement, pay, commute distance, candidate experience difference, automation angle, flexible full-time or visa-welcoming field is guessed. These remain null. Every feature has a separate missing indicator with Normal(0,0.5) prior; missing observations are imputed using training medians only. Missing indicators are centred on training missingness rates, avoiding spurious family-intercept confounding for entirely unsupported fields; the input also retains an explicit uncentred missingness mask. Pay is centred on training medians and retains the donor's $5/hour unit. Other features retain the donor's units; no response or holdout values fit the transformation. This deliberate model differs from the donor's silent zero substitution.

Four JAGS chains use fixed independent seeds 1103, 2207, 3301 and 4409, 1,500 adaptation and 2,500 burn-in iterations. Production default is 30,000 retained iterations per chain. The local subprocess uses no shell, no model gateway or inherited credentials, and has a bounded timeout. Each run writes private input, complete diagnostics/parameter summaries, a posterior subset and a trace/density PDF into its own directory. Only PDF plotting is thinned to about 2,000 points per chain; every retained draw contributes to the fit and diagnostics. All parameter summaries have a mode, mean, SD and 95% highest-density interval.

Every monitored beta, alpha, alpha_raw, mu_alpha and tau must have finite diagnostics: R-hat ≤1.01, ESS ≥10,000 and MCSE/SD ≤0.01. Missing parameters or inconsistent MCSE fail closed. This uses the installed Bayesian skill's stricter accuracy gate, not the retired 1,000-ESS floor. The heldout log score sums log(mean posterior probability of the chosen option). It must beat a 20,000-draw genuine prior-predictive integration on the identical heldout sets and training transformation. No repeated automatic retuning to the same holdout is performed. One holdout win is an activation guard, not evidence of population generalization; prior-sensitivity and calibration studies remain future analyses when genuine choices exist.

Prediction requires a current accepted owner fit and the caller's current eligible alternative snapshots. Outputs include set-dependent choice probabilities with 95% HDIs, none probability, utility intervals and additive family/feature contribution intervals. These are preference probabilities conditional on these four options, never a rubric probability, eligibility override or hiring probability. New choices, profile/config context changes or source changes invalidate previous activation. No pipeline or timer consumes the score automatically.

## Donor provenance and repairs

References were read from the archived job-tracker tree and never imported at runtime:

| Archived file | SHA-256 |
|---|---|
| `agent/fit/fit_choice_model.R` | `c9fc39ba36c1a221a86e2301cd83bdf864ed33f674317db9a10fcc06a7374383` |
| `agent/fit/choice_model.jags` | `9b0c52e4a1ec5f9c3a6340473b6ea58fd69535e838f4cd2ef0b1ff7dced58114` |
| `agent/workspace/skills/fit-evaluation/choice_sets.py` | `23943fb7ddf67289b27aead52bff9e17d289a847b9b2de3c7f369a3d35c1e873` |

Repairs include four reproducibly seeded chains instead of three unseeded chains, stable softmax, training-only preprocessing instead of full-dataset medians, explicit missingness, no excluded target family, finite per-parameter diagnostics instead of unsafe aggregate checks, proper prior-predictive validation instead of plug-in prior means, and immutable owner-only provenance instead of a retired messaging/runtime dependency.

## Local checks

`tests/preferences/test_core.py` covers missing/no-data behavior, GET nonmutation, immutable/idempotent owner picks, exclusion/provenance rejection, split separation, train-only preprocessing, missingness, finite gates, stale fit rejection and synthetic isolation. `JOBWATCH_TEST_R=1 ... pytest tests/preferences/test_local_r.py` additionally runs the actual local four-chain R/JAGS sampler against explicitly synthetic choices. Synthetic results demonstrate the implementation and recovery, not owner fit quality.

Undo before deployment: revert the preference module, tests and integration changes. Deployed owner rows, if ever created after a separately approved deployment, must be archived before any removal; do not undo by dropping owner data.

## Website and current-evaluation integration

The protected `/preferences` page records explicit comparisons, while the pool adapter reconstructs current profile/policy/runtime/ad identities and reruns the deterministic eligibility gate. Legacy agentic tables are not accepted as current evaluations. GET does not create labels or fits. POST rechecks exact snapshots and uses the existing origin guard; the owner can choose none. The CLI runs local fitting on demand. After an accepted owner fit, answered current comparisons show posterior ranking, 95% intervals, feature contributions and missingness. Unanswered comparisons never show predictions; retrospective training examples are explicitly distinguished from held-out validation. The live read-only inventory currently reports zero sets and zero choices.

An actual temporary-loopback HTTP Chromium walkthrough exercised comparison creation, a click on none and the resulting immutable recorded choice. Both temporary server and browser exited. No model or employer calls occurred. A real persisted synthetic pipeline test verifies that eligible evaluations enter the pool, a below-threshold evaluation does not, and an ad change rejects a previously displayed choice.
