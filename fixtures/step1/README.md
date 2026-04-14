# Step 1 fixtures

This directory should hold tiny committed Step 1 reproducibility inputs.

## Intended first fixture
- `sample_factor_report.html`

## Fixture requirements
- must be small enough to commit safely
- must not rely on private runtime outputs
- must exercise the HTML ingestion path for `run_step1_for_html`
- should be sufficient to reproduce Step 1 artifact classes on Bernard/Mac

## Not acceptable as fixture
- huge PDFs
- private raw caches
- runtime-generated outputs copied from `objects/` and called input
- anything that depends on unpublished local machine state
