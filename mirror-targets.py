#! /usr/bin/env python3

import argparse
import requests
import os
import shutil
import zipfile
import json
import subprocess
import random
import re
from dotenv import load_dotenv
from backoff import on_exception, expo
from ratelimit import RateLimitException

# Load environment variables from .env file
load_dotenv()

GH_TOKEN = os.environ.get('GH_TOKEN')
GITHUB_ORG = os.environ.get('GITHUB_ORG')
GITHUB_USERNAME = os.environ.get('GITHUB_USERNAME')
GIT_USER_NAME = os.environ.get('GIT_USER_NAME')
GIT_USER_EMAIL = os.environ.get('GIT_USER_EMAIL')

@on_exception(expo, RateLimitException, max_tries=8)
def get_plugins(page=1):
    plugins = []

    print(f'Fetching plugins info page {page}...')
    response = requests.get('https://api.wordpress.org/plugins/info/1.2/', params={'action': 'query_plugins', 'per_page': 250, 'page': page})

    if (response.status_code == 429):
        raise RateLimitException(response.content, 0)
    elif (response.status_code != 200):
        print(response.content)
        return

    data = response.json()

    for plugin in data['plugins']:
        plugins.append({
            'slug': plugin['slug'],
            'version': plugin['version'],
            'active_installs': plugin['active_installs'],
            'download_link': plugin['download_link']
        })

    return plugins + get_plugins(page + 1) if page < data['info']['pages'] else plugins

@on_exception(expo, RateLimitException, max_tries=8)
def get_themes(page=1):
    themes = []

    print(f'Fetching themes info page {page}...')
    response = requests.get('https://api.wordpress.org/themes/info/1.2/', params={'action': 'query_themes', 'request[browse]': 'popular', 'request[fields][active_installs]': 1, 'request[fields][downloadlink]': 1, 'request[per_page]': 1000, 'request[page]': page})

    if (response.status_code == 429):
        raise RateLimitException(response.content, 0)
    elif (response.status_code != 200):
        print(response.content)
        return

    data = response.json()

    for theme in data['themes']:
        themes.append({
            'slug': theme['slug'],
            'version': theme['version'],
            'active_installs': theme['active_installs'],
            'download_link': theme['download_link']
        })

    return themes + get_themes(page + 1) if page < data['info']['pages'] else themes

def download_file(url, filepath):
    print(f'Downloading {url}...')
    response = requests.get(url, allow_redirects=True)
    if response.status_code == 200:
        with open(filepath, 'wb') as f:
            f.write(response.content)

        try:
            with zipfile.ZipFile(filepath, 'r') as zip:
                zip.extractall()
                os.remove(filepath)
        except:
            print(f'Could not extract zip {filepath}')

def create_repo(name):
    try:
        # Check if the repo already exists
        subprocess.check_output(f'gh repo view {name}', shell=True)
        print(f'Repo {name} already exists.')
        return
    except:
        print(f'Creating repo {name}...')
        subprocess.check_output(f'gh repo create {name} --public --add-readme --disable-issues --disable-wiki', shell=True)

def install_actions_workflow():
    os.makedirs('.github/workflows', exist_ok=True)

    # Read the template workflow as text
    with open('../semgrep.yml', 'r') as f:
        workflow_content = f.read()

    # Add jitter to the cron schedule (randomize minute 0-59 and hour 0-23)
    random_minute = random.randint(0, 59)
    random_hour = random.randint(0, 23)
    jittered_cron = f'{random_minute} {random_hour} * * *'

    # Replace the cron schedule using regex to preserve YAML formatting
    workflow_content = re.sub(
        r"cron:\s*['\"]?\d+\s+\d+\s+\*\s+\*\s+\*['\"]?",
        f"cron: '{jittered_cron}'",
        workflow_content
    )

    # Write the modified workflow
    with open('.github/workflows/semgrep.yml', 'w') as f:
        f.write(workflow_content)

def unarchive_repo(repo):
    """Unarchive a GitHub repo so we can push to it."""
    print(f'Unarchiving {GITHUB_ORG}/{repo}...')
    subprocess.run(
        ['gh', 'api', '-X', 'PATCH', f'repos/{GITHUB_ORG}/{repo}',
         '-f', 'archived=false'],
        check=True, capture_output=True, text=True,
    )


def clone_repo(repo):
    """Clone a repo, unarchiving first if necessary. Returns the clone dir."""
    url = f'https://{GITHUB_USERNAME}:{GH_TOKEN}@github.com/{GITHUB_ORG}/{repo}.git'
    try:
        subprocess.run(['git', 'clone', url], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        if '403' in (e.stderr or '') or 'archived' in (e.stderr or '').lower():
            unarchive_repo(repo)
            subprocess.run(['git', 'clone', url], check=True, capture_output=True, text=True)
        else:
            raise


def mirror_target(type, target):
    """Mirror a plugin/theme. Returns True on success, False on failure."""
    print(f'Mirroring {target}...')
    repo = f'{type}-{target["slug"]}'
    orig_dir = os.getcwd()

    try:
        clone_repo(repo)
        os.chdir(repo)

        download_file(target['download_link'], f'{target["slug"]}.{target["version"]}.zip')
        install_actions_workflow()

        subprocess.run(['git', 'add', '.'], check=True)
        # commit returns 1 when there's nothing to commit — that's fine
        subprocess.run(['git', 'commit', '-m', target['version']], capture_output=True)
        subprocess.run(['git', 'push', '-u', 'origin', 'main'], check=True,
                       capture_output=True, text=True)
        return True
    except Exception as e:
        print(f'ERROR mirroring {repo}: {e}')
        return False
    finally:
        os.chdir(orig_dir)
        if os.path.isdir(repo):
            shutil.rmtree(repo)

def update_workflow(type, target):
    """Update the semgrep workflow in a repo. Returns True on success, False on failure."""
    print(f'Updating workflow for {target["slug"]}...')
    repo = f'{type}-{target["slug"]}'
    orig_dir = os.getcwd()

    try:
        clone_repo(repo)
        os.chdir(repo)
        install_actions_workflow()
        subprocess.run(['git', 'add', '.github/workflows/semgrep.yml'], check=True)
        subprocess.run(['git', 'commit', '-m', 'Update semgrep workflow'], capture_output=True)
        subprocess.run(['git', 'push', '-u', 'origin', 'main'], check=True,
                       capture_output=True, text=True)
        return True
    except Exception as e:
        print(f'ERROR updating workflow for {repo}: {e}')
        return False
    finally:
        os.chdir(orig_dir)
        if os.path.isdir(repo):
            shutil.rmtree(repo)

def get_repo_version(repo):
    """Get the mirrored version from the latest version-commit in a GitHub repo.
    Skips non-version commits like 'Update semgrep workflow' or 'Initial commit'.
    Returns None if the repo doesn't exist or has no version commits."""
    skip = {'Update semgrep workflow', 'Initial commit', 'initial commit'}
    try:
        result = subprocess.run(
            ['gh', 'api', f'repos/{GITHUB_ORG}/{repo}/commits?per_page=10',
             '--jq', '.[].commit.message'],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.strip().split('\n'):
            msg = line.strip()
            if msg and msg not in skip:
                return msg
        return None
    except subprocess.CalledProcessError:
        return None


def reconcile_targets(targets):
    """Find targets where targets.json version doesn't match the repo's latest commit.
    Returns a list of (type, slug) tuples that need re-mirroring."""
    stale = []
    for type in ['plugins', 'themes']:
        for slug, target in targets[type].items():
            repo = f'{type}-{slug}'
            repo_version = get_repo_version(repo)
            if repo_version is None:
                print(f'  {repo}: repo not found or empty — skipping')
                continue
            if repo_version != target['version']:
                print(f'  {repo}: targets.json={target["version"]}  repo={repo_version}  → STALE')
                stale.append((type, slug))
            else:
                print(f'  {repo}: OK ({target["version"]})')
    return stale


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--min_install_count', type=int,
                        default=int(os.environ.get('MIN_INSTALL_COUNT', 1000)))
    parser.add_argument('--update-workflows', action='store_true',
                        help='Force-install the latest semgrep.yml in all tracked repos')
    parser.add_argument('--reconcile', action='store_true',
                        help='Check all targets for version drift and re-mirror stale repos')
    args = parser.parse_args()

    # Set identity for git
    subprocess.run(['git', 'config', '--global', 'user.name', GIT_USER_NAME], check=True)
    subprocess.run(['git', 'config', '--global', 'user.email', GIT_USER_EMAIL], check=True)

    # Read metadata from last run from targets.json
    old_targets = {
        'plugins': {},
        'themes': {}
    }
    if os.path.exists('targets.json'):
        with open('targets.json', 'r') as f:
            old_targets = json.load(f)

    # Get a list of in-scope plugins and themes
    new_targets = {
        'plugins': {},
        'themes': {}
    }
    for plugin in get_plugins():
        if plugin['active_installs'] >= args.min_install_count:
            new_targets['plugins'][plugin['slug']] = plugin

    for theme in get_themes():
        if theme['active_installs'] >= args.min_install_count:
            new_targets['themes'][theme['slug']] = theme

    # Reconcile: find repos where targets.json is ahead of the actual repo
    if args.reconcile:
        print('\nReconciling targets.json against actual repo versions...')
        stale = reconcile_targets(old_targets)
        if stale:
            print(f'\nFound {len(stale)} stale target(s). Re-mirroring...')
            for type, slug in stale:
                target = old_targets[type][slug]
                if mirror_target(type, target):
                    print(f'  ✓ {type}/{slug} re-mirrored to {target["version"]}')
                else:
                    print(f'  ✗ {type}/{slug} failed to re-mirror')
        else:
            print('\nAll targets are in sync.')

    # Find plugins or themes that are new or have been updated
    mirrored = set()
    failed = set()

    for type in ['plugins', 'themes']:
        for slug, target in new_targets[type].items():
            if slug not in old_targets[type]:
                create_repo(f'{GITHUB_ORG}/{type}-{slug}')
                if mirror_target(type, target):
                    mirrored.add((type, slug))
                else:
                    failed.add((type, slug))
            elif target['version'] != old_targets[type][slug]['version']:
                if mirror_target(type, target):
                    mirrored.add((type, slug))
                else:
                    failed.add((type, slug))

    if args.update_workflows:
        for type in ['plugins', 'themes']:
            for slug, target in old_targets[type].items():
                if (type, slug) not in mirrored:
                    update_workflow(type, target)

    # For failed mirrors, preserve the old version in targets.json so they
    # get retried on the next run instead of being silently skipped.
    for type, slug in failed:
        if slug in old_targets[type]:
            new_targets[type][slug] = old_targets[type][slug]
        else:
            # New target that failed — remove so it gets retried as "new"
            new_targets[type].pop(slug, None)

    if failed:
        print(f'\nWARNING: {len(failed)} target(s) failed to mirror and will be retried next run:')
        for type, slug in sorted(failed):
            print(f'  - {type}/{slug}')

    # Save the new metadata to targets.json
    with open('targets.json', 'w') as f:
        json.dump(new_targets, f)

    # Commit and push the updated targets.json
    subprocess.run(['git', 'add', 'targets.json'], check=True)
    subprocess.run(['git', 'commit', '-m', 'Update targets.json'], capture_output=True)
    subprocess.run(['git', 'push'], check=True)