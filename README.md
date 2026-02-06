# WordPress Bug Bounty

Automated mirroring of WordPress plugins and themes with continuous security scanning.

## Overview

This project automatically mirrors popular WordPress plugins and themes from the official WordPress.org repository into individual GitHub repositories under the [WordPressBugBounty](https://github.com/WordPressBugBounty) organization. Each mirrored repository includes automated Semgrep security scanning to identify potential vulnerabilities.


## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Mirror all targets with default minimum install count (1,000)
./mirror-targets.py

# Mirror targets with custom minimum install count
./mirror-targets.py --min_install_count 5000
```

## Configuration

- **GITHUB_ORG**: Organization where repositories are created (default: `WordPressBugBounty`)
- **GH_TOKEN**: GitHub personal access token (from environment variable)
- **min_install_count**: Minimum active installations required (default: 1,000)

## Files

- `mirror-targets.py`: Main script for mirroring targets
- `semgrep.yml`: Template GitHub Actions workflow for security scanning
- `targets.json`: State file tracking all mirrored targets and versions
- `requirements.txt`: Python dependencies

## Security Scanning

Each mirrored repository includes a GitHub Actions workflow that:
- Runs Semgrep with pro-level intrafile analysis and dataflow tracing
- Executes on push to main/master branches
- Runs on a randomized daily schedule (jittered to avoid rate limits)
- Uploads findings to GitHub Security Advanced Security (SARIF format)
- Supports manual triggering via workflow_dispatch