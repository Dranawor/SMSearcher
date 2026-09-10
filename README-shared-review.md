# SMSearcher shared-review update

Replace the existing `scanner/scan.py`, `app.js`, `index.html`, and `styles.css`.
Add `.github/workflows/review-sync.yml`.
Replace `.github/workflows/pages.yml`.
Add `data/reviews.json` containing `{}`.

The dashboard now shows Steam preview images, titles, creators/descriptions when available, and shared Reviewed/Unreviewed status.

Because GitHub Pages is static, Mark Reviewed opens a prefilled GitHub Issue. A reviewer submits it, then the workflow synchronizes the shared status. Only repository collaborators with triage/push/maintain/admin permission are accepted as reviewers.

Do not replace the existing `data/results.json`.
