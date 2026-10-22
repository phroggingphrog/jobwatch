# Confirmed preferences: synthetic comparison

Captured locally with invented ads and profiles, no gateway or provider calls.
The historical gate uses an explicitly invented Brunswick/VIC profile. The current
gate receives separate confirmed Sydney, Perth and Melbourne policies as arguments.
The qualification inputs remain identical in each comparison; the low-score case
has supported evidence and employment-first strategy.

```json
[
  {
    "case": "Sydney NSW",
    "historical_gate": "archive",
    "confirmed_matching_profile": "draft",
    "confirmed_other_profile": "archive"
  },
  {
    "case": "Perth WA",
    "historical_gate": "archive",
    "confirmed_matching_profile": "draft",
    "confirmed_other_profile": "archive"
  },
  {
    "case": "supported low career score",
    "historical_gate": "archive",
    "confirmed_employment_first": "draft"
  }
]
```

The historical fixture freezes gate logic and imports current scanners/contracts;
this is not an exact reproduction of a deployed release. It includes cases the
former gate archived, and proves the intended routing changes without establishing
live recommendation quality. `tests/test_profile_gate_comparison.py` asserts the
same outcomes, plus verified remote evidence and unknown seniority handling.

Eligibility regressions additionally cover independent citizenship/residence,
clearance/sponsorship, advertised numeric hours, explicit exclusions, unknowns,
foreign residency, mixed requirement alternatives and two contrasting profiles.
Human approval and confirmed Submit are outside this offline comparison.
