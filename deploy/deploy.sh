#!/usr/bin/env bash
# Разворачивает TengeLens и StockSense на чистой VM Oracle Cloud (Ubuntu 22.04/24.04).
# Запуск на сервере:  bash deploy.sh
set -euo pipefail
GH_USER="${GH_USER:-sobekzat}"
DIR="$HOME/apps"

if ! command -v docker >/dev/null; then
  echo "== Устанавливаю Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

echo "== Открываю порты 80 и 8080 во встроенном файрволе Oracle-образа"
for port in 80 8080; do
  sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 6 -p tcp --dport "$port" -j ACCEPT
done
sudo apt-get install -y iptables-persistent >/dev/null 2>&1 || true
sudo netfilter-persistent save >/dev/null 2>&1 || true

echo "== Скачиваю код"
mkdir -p "$DIR" && cd "$DIR"
for repo in tengelens stocksense; do
  if [ -d "$repo" ]; then git -C "$repo" pull --ff-only; else git clone "https://github.com/$GH_USER/$repo.git"; fi
done
cp stocksense/deploy/docker-compose.yml "$DIR/docker-compose.yml"
sed -i 's#\.\./tengelens#./tengelens#; s#\.\./stocksense#./stocksense#' "$DIR/docker-compose.yml"

echo "== Собираю и запускаю"
sudo docker compose -f "$DIR/docker-compose.yml" up -d --build

IP=$(curl -s ifconfig.me || echo "IP_СЕРВЕРА")
echo
echo "Готово:"
echo "  TengeLens:  http://$IP"
echo "  StockSense: http://$IP:8080"
echo "Если не открывается — добавьте Ingress-правила для портов 80 и 8080 в Security List (см. DEPLOY.md)."
