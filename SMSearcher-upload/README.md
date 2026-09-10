# SMSearcher

A GitHub Pages dashboard plus scheduled GitHub Actions scanner for public Steam Workshop listings matching a configurable list of protected-IP keywords.

## Setup

1. Upload the files preserving their directory structure.
2. In **Settings → Actions → General**, enable **Read and write permissions** for workflows.
3. In **Settings → Pages**, select **GitHub Actions** as the source.
4. Optionally create an `workshop-alert` issue label.
5. Run **Actions → Scan Steam Workshop → Run workflow** once to populate the dashboard.

The scanner runs every six hours afterward. New listings are marked **NEW** and a GitHub Issue is created for review.

### Important

This is a review/alert tool, not an automated infringement or DMCA system. A keyword match is not an infringement determination. Review each listing before taking action.

The scanner accesses public Steam Community pages only. It does not log in, bypass CAPTCHAs/access controls, or submit takedown requests.

## Keywords

Edit `keywords.json` to add or remove monitored terms.
