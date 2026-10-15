[中文](output.md) · English · [Back to README](../README.en.md)

# Output

Each run creates a session folder under `workspace/`:

```
workspace/session_20261007_133450/
├── 00_session.json               # Session metadata (status, models, duration and usage)
├── 01_question.txt               # Question and request notes
├── 03_plan.json                  # Search plan
├── 04_clarification/             # Clarification result
├── 04_research/                  # Raw search data and page content per round
├── 05_analysis.md                # Analysis
├── 06_drafts/                    # Every draft (draft_0.md is the first; each ends with "claim sources")
├── 07_reviews/                   # Review per round (7 scores)
├── 08_verification/
│   ├── ledger.json               # Claim ledger (sources S* / claims C* / contradictions X* and rulings)
│   ├── source_verification.json  # Source assessment
│   ├── fact_check.json           # Independent checks and rulings
│   ├── conclusion_validation.json
│   ├── confidence_report.json    # Confidence report
│   └── verified_registry.json    # Cache of queries already run
├── 09_final.md                   # Final report
├── research_log.txt              # Run log
└── .checkpoints/                 # Snapshot after each phase, for resume and replay
```

Task state lives in `research_tasks.db` at the project root and survives a server restart; tasks still running before a restart are marked `interrupted`.
