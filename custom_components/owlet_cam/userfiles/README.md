# Private persistent runtime directory

HACS preserves this directory across integration upgrades. Do not commit its
runtime contents. Later embedded milestones create `uploads`, `extracted`,
`runtime`, `logs`, `state`, and `tmp` here. Account passwords and cloud tokens
must never be stored here.
