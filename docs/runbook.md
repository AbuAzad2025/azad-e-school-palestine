# Incident Runbook — Azad E-School

## Severity Levels
| Level | Description | Examples | Response Time |
|-------|-------------|----------|---------------|
| SEV-1 | Platform unavailable | 500 errors on all pages, DB down | 15 min |
| SEV-2 | Major feature degraded | Login broken, payments failing | 1 hour |
| SEV-3 | Minor issue | Slow page, non-critical bug | 4 hours |
| SEV-4 | Low priority | Cosmetic issue, warning logs | 1 day |

## Contacts
- On-call engineer: see PagerDuty / Opsgenie
- Sentry: https://sentry.io/organizations/azad-e-school/
- Uptime monitor: https://uptimerobot.com/
- Logs: `journalctl -u azad-e-school -f`

## Common Checks
```bash
# Health endpoints
curl -sf https://azad.school/health
curl -sf https://azad.school/health/deep

# Service status
sudo systemctl status azad-e-school
sudo systemctl status postgresql
sudo systemctl status redis

# Recent logs
sudo journalctl -u azad-e-school -n 200 --no-pager

# Database
sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity;"

# Disk / memory
df -h
free -h
```

## Rollback
```bash
cd /opt/azad-e-school
git log --oneline -5
git checkout <previous-stable-commit>
docker compose -f deploy/docker-compose.production.yml up -d --build
flask db upgrade
```

## Escalation
1. Attempt rollback if SEV-1/SEV-2
2. Page on-call if issue persists >30 min
3. Post incident summary in #incidents Slack channel within 24h

## Post-Mortem Template
- Timeline
- Root cause
- Impact
- Resolution
- Action items (owner + due date)