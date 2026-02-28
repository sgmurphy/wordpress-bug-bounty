#! /usr/bin/env python3

import json
import os
import subprocess
import requests
from dotenv import load_dotenv

load_dotenv()

GH_TOKEN = os.environ.get('GH_TOKEN')
GITHUB_ORG = 'WordPressBugBounty'

with open('targets.json') as f:
    targets = json.load(f)

valid_repos = set()
for slug in targets.get('plugins', {}):
    valid_repos.add(f'plugins-{slug}')
for slug in targets.get('themes', {}):
    valid_repos.add(f'themes-{slug}')

def get_org_repos():
    repos = []
    page = 1
    headers = {'Authorization': f'Bearer {GH_TOKEN}', 'X-GitHub-Api-Version': '2022-11-28'}
    while True:
        print(f'Fetching org repos page {page}...')
        response = requests.get(
            f'https://api.github.com/orgs/{GITHUB_ORG}/repos',
            headers=headers,
            params={'per_page': 100, 'page': page, 'type': 'public'}
        )
        response.raise_for_status()
        page_repos = response.json()
        if not page_repos:
            break
        repos.extend(page_repos)
        page += 1
    return repos

repos = get_org_repos()

archived_count = 0
for repo in repos:
    name = repo['name']
    # Only touch repos that follow the plugins-/themes- naming convention
    if not (name.startswith('plugins-') or name.startswith('themes-')):
        continue
    if repo['archived']:
        continue
    if name not in valid_repos:
        print(f'Archiving {name}...')
        subprocess.run(
            ['gh', 'repo', 'archive', f'{GITHUB_ORG}/{name}', '--yes'],
            check=True
        )
        archived_count += 1

print(f'Done. Archived {archived_count} repo(s).')
