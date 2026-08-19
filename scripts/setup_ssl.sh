#!/bin/bash
set -euo pipefail
DOMAIN="${1:?Usage: setup_ssl.sh <domain>}"
EMAIL="${2:?Usage: setup_ssl.sh <domain> <email>}"
apt-get update && apt-get install -y certbot
certbot certonly --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive
echo "0 3 * * * certbot renew --quiet --post-hook 'nginx -s reload'" | crontab -
nginx -s reload
echo "SSL certificate installed for $DOMAIN"
