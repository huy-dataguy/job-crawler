#!/usr/bin/env bash
# Relocatable, user-scoped services. Run after building frontend and migrating.
#
# Windmill is the ONLY scheduler (see docs/operations.md). systemd runs the
# dashboard only. The job-crawler-{crawl,deep,companies,sync}.timer units still
# live in this directory for reference but are never enabled: running them
# alongside Windmill causes duplicate runs, "database is locked" failures, and
# Telegram alerts that Windmill never sees. Set JC_INSTALL_LEGACY_TIMERS=1 only
# if you deliberately run systemd instead of Windmill.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export JC_INSTALL_REPO="$REPO_DIR"
export JC_INSTALL_LEGACY_TIMERS="${JC_INSTALL_LEGACY_TIMERS:-0}"
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
legacy=os.environ.get('JC_INSTALL_LEGACY_TIMERS')=='1'
for path in (root/'scripts/local').iterdir():
    if path.suffix in ('.service','.timer'):
        if not legacy and path.name!='job-crawler-dashboard.service':
            continue
        (units/path.name).write_text(path.read_text().replace('@REPO_DIR@',value))
for name in ('run_crawler.sh','run_companies.sh','run_deep.sh'):
    path=root/'scripts/local'/name
    path.chmod(path.stat().st_mode | 0o111)
PY
systemctl --user daemon-reload
systemctl --user reset-failed job-crawler-dashboard.service || true
if [ "$JC_INSTALL_LEGACY_TIMERS" = "1" ]; then
  systemctl --user enable --now job-crawler-crawl.timer job-crawler-companies.timer job-crawler-deep.timer job-crawler-sync.timer
else
  # Safety: a previous install may have left these enabled.
  systemctl --user disable --now job-crawler-crawl.timer job-crawler-companies.timer job-crawler-deep.timer job-crawler-sync.timer 2>/dev/null || true
fi
systemctl --user restart job-crawler-dashboard.service
systemctl --user enable job-crawler-dashboard.service
systemctl --user list-timers 'job-crawler-*' --all --no-pager
