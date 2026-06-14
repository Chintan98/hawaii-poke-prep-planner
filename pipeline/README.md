# 2025 Lunch Prep Pipeline

This pipeline converts the Caspeco transaction export into the static JSON files
used by the Hawaii Poké prep-planner website.

## Rules

- Use `business_date` in 2025.
- Include sales from `11:00:00` through `13:59:59`.
- Pair bowl headers and protein-selection rows within the same receipt.
- Count one physical bowl after pairing.
- Apply the recipe database to mapped bowls.
- Add explicit extra proteins using the standard protein portion.
- Keep unsupported menu items in the audit report rather than guessing recipes.
- Deploy only generated JSON, never the raw transaction export.

## Build

```bash
python3 pipeline/build_lunch_prep.py \
  --source /path/to/caspeco-sales_transactions_original.csv
```

Generated website data is written to `restaurants/` and audit files are
written to `audit/`.

Run tests before publishing:

```bash
python3 -m unittest pipeline.test_build_lunch_prep -v
```

Create a Netlify draft preview from the repository root:

```bash
netlify deploy --dir .
```
