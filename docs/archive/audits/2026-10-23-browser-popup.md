# Browser popup repair audit

**Status: local release verification and independent review complete.**
Source integration is recorded by the linked repair PR; deployment is separate.
This audit records the observed issue #17 cause and repair evidence. It contains
no candidate data.

## Observed cause and repair

A real popup opens at `/login`. Before publishing that popup as the active page,
the browser session performs a Chromium CDP target lookup that yields. During
that wait, the next task callback can bind to the still-published opener page at
`/`. Later popup adoption cannot change the page already bound to that callback,
so its `/login` navigation wait times out and is reported as
`browser_action_failed`.

The repair publishes the active page, clears unknown target identity to `None`,
updates the URL hash, and installs navigation and restoration handlers before
the yielding lookup. It caches the resolved target only if that page is still
current. While target identity is pending, the session fails closed rather than
using the opener's identity. The regression gates the actual CDP boundary with a
browser condition; it uses no sleep or weakened assertion.

## Evidence

- The original popup regression failed in 33.19 seconds with the navigation
  timeout. A controlled protocol-boundary probe reproduced the callback binding
  to `/` while the popup was at `/login`.
- The new deterministic regression failed before the runtime repair in 1.58
  seconds, observing the opener instead of the popup.
- After the repair, the browser module passed: 48 tests in 49.60 seconds. The
  enhanced popup regression passed in 1.57 seconds, and an independent
  close-during-lookup probe passed in 2.47 seconds. That probe confirmed that
  closing the popup restores the opener and protection, and late popup metadata
  cannot replace the restored identity.
- Independent review found no runtime blocker. It identified a test synchronization
  race: clicking the owner control did not prove the CDP lookup had entered. The
  parent added a bounded `lookup_entered.wait` before asserting the gated
  interleaving. This condition wait establishes the intended test phase without
  adding a sleep or weakening assertions.

Final synchronized popup checks passed: **2 passed in 4.06 seconds**. The complete
stable-source local suite passed: **3655 passed, 11 skipped, 6 warnings in
1149.85 seconds**. `jobwatch check --code` passed against the isolated invented
profile, and `git diff --check` passed. Independent Sol 6.1 review found no
remaining blocker; this is same-family independent review, not cross-family
validation. Hosted CI remains disabled and is not a completion requirement.

## Boundaries and rollback

Browser QA used synthetic loopback pages only. No live settings, providers,
candidate records, employer traffic, deployment or migrations were used. No
service or timer was activated. Rollback reverts the browser source and regression
changes; the repair has no runtime data migration to undo. Reverting restores the
original popup race. Local verification and review do not establish deployment.
