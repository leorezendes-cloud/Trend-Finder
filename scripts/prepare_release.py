"""Build a separate, reviewable website snapshot; never modifies Scout inputs."""
import ast
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'dist' / 'website'


def release_files():
    selected = set()

    def add(path):
        path = path.resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or path.is_symlink():
            raise ValueError(f'Invalid release source: {path}')
        selected.add(path.relative_to(ROOT))

    # Follow static local imports, including imports inside route functions.
    pending = [ROOT / 'app.py', ROOT / 'wsgi.py']
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        add(path)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
                base = ROOT
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or '']
                base = path.parent if node.level else ROOT
                for _ in range(max(0, node.level - 1)):
                    base = base.parent
            else:
                continue
            for module in modules:
                target = base.joinpath(*module.split('.'))
                if target.with_suffix('.py').is_file():
                    pending.append(target.with_suffix('.py'))
                elif target.is_dir() and (target / '__init__.py').exists():
                    pending.append(target / '__init__.py')

    for folder in ('templates', 'static'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and path.name != '.DS_Store':
                add(path)
    for pattern in ('*.csv', '*.json'):
        for path in ROOT.glob(pattern):
            add(path)
    for name in ('gunicorn.conf.py', 'requirements.txt', '.env.example',
                 'HOSTING.md', 'MEMBERSHIP.md', 'NEWSLETTER.md', 'MEMBER_PICKS.md', 'WEEKLY_POLICY.md', 'SEO.md', '.gitignore', 'render.yaml', 'automatic_model.json'):
        add(ROOT / name)
    cache = ROOT / 'data/scout4'
    # Preserve all available saved statistics seasons and their pointed-to files.
    for folder in cache.iterdir():
        if folder.is_dir() and folder.name.isdigit():
            for path in folder.rglob('*'):
                if path.is_file():
                    add(path)
    pointer = cache / 'ratings_latest.json'
    if pointer.exists():
        add(pointer)
        manifest = json.loads(pointer.read_text())
        for key in ('models_path', 'summary_path'):
            add(ROOT / manifest[key])
    for pattern in ('shadow/predictions/*.json', 'shadow/status.json',
                    'personnel/*/*/pregame_evidence.json', 'starter_reports/*.json',
                    'daily/latest.json', 'blend/predictions/*.json', 'blend/status.json', 'weather/**/*.json'):
        for path in cache.glob(pattern):
            add(path)
    for pattern in ('pace/2026/*/profiles_before_week6.json', 'totals_runs/*/summary.json'):
        paths = sorted(cache.glob(pattern))
        if paths:
            add(paths[-1])
    # Ship meaningful tests, but never account databases, secrets, logs or raw downloads.
    for name in ('test_membership.py', 'test_hosting.py', 'test_page_layouts.py', 'test_trend_filters.py', 'test_site_sections.py', 'test_hosted_updates.py', 'test_membership_backups.py', 'test_newsletter.py', 'test_newsletter_draft.py', 'test_member_picks.py', 'test_week_policy.py', 'test_weekly_pick_lines.py', 'test_pick_workflow.py', 'test_weekly_matchup_layout.py', 'test_plug_always_pick.py', 'test_seo.py', 'test_site_health.py', 'test_mobile_pick_menu.js', 'test_context_model.py', 'test_points_publication.py'):
        add(ROOT / name)
    return sorted(selected)


def main():
    if OUTPUT.exists():
        raise SystemExit('dist/website already exists. Preserve or remove that generated copy before rebuilding.')
    files = release_files()
    OUTPUT.mkdir(parents=True)
    manifest = {}
    for relative in files:
        target = OUTPUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
        manifest[str(relative)] = {'bytes': target.stat().st_size,
                                   'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    (OUTPUT / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    size = sum(record['bytes'] for record in manifest.values())
    print(f'Prepared {len(files)} files ({size / 1024**2:.1f} MiB) in {OUTPUT}')


if __name__ == '__main__':
    main()
