#!/usr/bin/env bash
# Relocatable, user-scoped services. Run after building frontend and migrating.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export JC_INSTALL_REPO="$REPO_DIR"
"$REPO_DIR/.venv/bin/python" - <<'PY'
import os
from pathlib import Path
root=Path(os.environ['JC_INSTALL_REPO'])
units=Path.home()/'.config/systemd/user'
units.mkdir(parents=True,exist_ok=True)
assert (root/'frontend/dist/index.html').is_file(),'Build frontend first: cd frontend && npm run build'
from job_crawler import config,store
store.connect(config.DB_PATH).close()
value=str(root).replace('%','%%').replace('\\','\\\\').replace('"','\\"')
for path in (root/'scripts/local').iterdir():
    if path.suffix in ('.service','.timer'):
        (units/path.name).write_text(path.read_text().replace('@REPO_DIR@',value))
for name in ('run_crawler.sh','run_companies.sh','run_deep.sh'):
    path=root/'scripts/local'/name
    path.chmod(path.stat().st_mode | 0o111)
PY
systemd-analyze --user verify "$HOME/.config/systemd/user/job-crawler-dashboard.service" "$HOME/.config/systemd/user/job-crawler-crawl.service" "$HOME/.config/systemd/user/job-crawler-companies.service" "$HOME/.config/systemd/user/job-crawler-deep.service"
systemctl --user daemon-reload
systemctl --user reset-failed job-crawler-crawl.service job-crawler-deep.service job-crawler-dashboard.service || true
systemctl --user enable --now job-crawler-crawl.timer job-crawler-companies.timer job-crawler-deep.timer
systemctl --user restart job-crawler-dashboard.service
systemctl --user enable job-crawler-dashboard.service
systemctl --user list-timers 'job-crawler-*' --no-pager
