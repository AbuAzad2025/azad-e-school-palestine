# Production Deployment Checklist — Azad E-School

## Pre-requisites
- [ ] Ubuntu 22.04 LTS server (4 vCPU / 8 GB RAM / 100 GB SSD minimum)
- [ ] Domain name pointing to server (`azad.school`)
- [ ] DNS A/AAAA records set
- [ ] SSH key access configured

## Server Hardening
- [ ] `apt update && apt upgrade -y`
- [ ] Create non-root deploy user (`azad`)
- [ ] Configure UFW: allow 22, 80, 443
- [ ] Install fail2ban
- [ ] Disable password login
- [ ] Configure automatic security updates

## Install Dependencies
- [ ] Docker + Docker Compose (v2)
- [ ] nginx
- [ ] certbot + python3-certbot-nginx
- [ ] PostgreSQL 15+ (or use managed DB)
- [ ] Redis 7+ (or use managed cache)

## Application Setup
- [ ] Clone repo to `/opt/azad-e-school`
- [ ] Copy `.env.example` to `.env` and fill secrets
- [ ] Build CSS: `python scripts/build_css.py`
- [ ] Run migrations: `flask db upgrade`
- [ ] Compile i18n: `pybabel compile -d app/translations`
- [ ] Create admin user via CLI or first-run seed

## SSL / CDN
- [ ] Obtain certificate: `certbot --nginx -d azad.school -d www.azad.school`
- [ ] Configure auto-renewal cron
- [ ] Set up Cloudflare (or similar CDN) for static assets
- [ ] Enable HTTPS-only and HSTS

## Docker Compose Production
```bash
docker compose -f docker-compose.production.yml up -d --build
```

## Systemd Service
```bash
sudo cp deploy/azad-e-school.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now azad-e-school
```

## Verification
- [ ] Site loads over HTTPS
- [ ] Admin login works
- [ ] Database backups running
- [ ] Sentry / Uptime monitoring active
- [ ] Load test completed with <5% failure rate at 1000 users

## Rollback Plan
1. `docker compose -f docker-compose.production.yml down`
2. Restore database from latest backup
3. `git checkout <previous-tag>`
4. Redeploy

## Post-Deploy
- [ ] Run smoke tests
- [ ] Verify error logs are empty
- [ ] Confirm CI/CD pipeline status badge is green