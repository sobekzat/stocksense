# Деплой на Oracle Cloud (Always Free)

## 1. Сервер (один раз, ~10 минут в консоли Oracle)
1. **Compute → Instances → Create instance**, образ **Ubuntu 22.04 или 24.04**.
   Подойдёт бесплатная VM.Standard.E2.1.Micro (1 ГБ RAM: двум сайтам нужно ~400 МБ).
   Лучше Ampere A1 (ARM), она тоже бесплатная и мощнее.
2. **Networking → VCN → Security List → Add Ingress Rules**:
   Source `0.0.0.0/0`, TCP, порты **80** и **8080**. Без этого сайты не будут видны из интернета.

## 2. Запуск (на сервере по SSH)
```bash
curl -fsSL https://raw.githubusercontent.com/sobekzat/stocksense/main/deploy/deploy.sh -o deploy.sh
bash deploy.sh
```
Скрипт сам ставит Docker, открывает порты в файрволе Ubuntu, скачивает оба репозитория и запускает их.
Сайты автоматически перезапускаются после перезагрузки сервера.

- TengeLens:  `http://IP_СЕРВЕРА`
- StockSense: `http://IP_СЕРВЕРА:8080`

## 3. Обновление после изменений в коде
```bash
bash deploy.sh
```

## 4. Домен и HTTPS (по желанию)
Купите домен (например, на ps.kz), направьте A-записи `tengelens.ваш-домен.kz` и `stocksense.ваш-домен.kz` на IP сервера.
Потом поставьте Caddy, он сам выпустит HTTPS-сертификаты.
