# Changelog

## Unreleased

- Validate personal ranking models on held-out source projects with standardized features; retain online preferences when validation fails or data is insufficient.
- Validate immutable feedback snapshots, use the latest publication metrics, and distinguish missing retention from an observed zero.
- Batch candidate predictions, cache loaded models, and save model files atomically with validation reports and reproducible training fingerprints.
