#! /usr/bin/env python3

import argparse
import requests
import os
import shutil
import zipfile
import json
import subprocess
import random
import yaml
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

    # Read and parse the template workflow
    with open('../semgrep.yml', 'r') as f:
        workflow = yaml.safe_load(f)

    # Add jitter to the cron schedule (randomize minute 0-59 and hour 0-23)
    random_minute = random.randint(0, 59)
    random_hour = random.randint(0, 23)
    jittered_cron = f'{random_minute} {random_hour} * * *'

    # Update the cron schedule with jitter
    if 'on' in workflow and 'schedule' in workflow['on']:
        for schedule_item in workflow['on']['schedule']:
            if 'cron' in schedule_item:
                schedule_item['cron'] = jittered_cron

    # Write the modified workflow
    with open('.github/workflows/semgrep.yml', 'w') as f:
        yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)

def mirror_target(type, target):
    print(f'Mirroring {target}...')

    # Clone the repo
    repo = f'{type}-{target["slug"]}'
    os.system(f'git clone https://{GITHUB_USERNAME}:{GH_TOKEN}@github.com/{GITHUB_ORG}/{repo}.git')
    os.chdir(repo)

    # Download the latest version of the plugin or theme
    download_file(target['download_link'], f'{target["slug"]}.{target["version"]}.zip')

    # Install the actions workflow
    install_actions_workflow()

    # Commit the updated files to the repo
    os.system('git add .')
    os.system(f'git commit -m "{target["version"]}" || echo "No changes to commit"')
    os.system('git push -u origin main')

    # Change back to the original directory
    os.chdir('..')

    # Remove the cloned repo
    shutil.rmtree(repo)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--min_install_count', type=int,
                        default=int(os.environ.get('MIN_INSTALL_COUNT', 1000)))
    args = parser.parse_args()

    # Set identity for git
    os.system(f'git config --global user.name "{GIT_USER_NAME}"')
    os.system(f'git config --global user.email "{GIT_USER_EMAIL}"')

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

    # Find plugins or themes that are new or have been updated
    for type in ['plugins', 'themes']:
        for slug, target in new_targets[type].items():
            if not slug in old_targets[type]:
                create_repo(f'{GITHUB_ORG}/{type}-{slug}')
                mirror_target(type, target)
            elif target['version'] != old_targets[type][slug]['version']:
                mirror_target(type, target)

    # Save the new metadata to targets.json
    with open('targets.json', 'w') as f:
        json.dump(new_targets, f)

    # Commit and push the updated targets.json
    os.system('git add targets.json')
    os.system('git commit -m "Update targets.json" || echo "No changes to commit"')
    os.system('git push')