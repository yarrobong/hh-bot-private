FROM python:3.13-slim

ENV UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1

# Системные зависимости
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      gcc \
      libc6-dev \
      procps \
      cron \
      dos2unix \
      tzdata \
      less && \
    rm -rf /var/lib/apt/lists/*

# Настройка пользователя
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID docker && \
    useradd -u $UID -g docker -m -s /bin/bash docker

WORKDIR /app

COPY pyproject.toml README.md requirements.lock ./

# 1. Cтавим playwright, браузер и системные зависимости (этот тяжелый слой теперь закэшируется)
RUN pip install --no-cache-dir uv && \
    uv pip install --system -r requirements.lock && \
    playwright install-deps chromium && \
    su docker -c "playwright install chromium"

# 2. Теперь копируем исходный код
COPY src ./src

# 3. Устанавливаем саму утилиту и остальные зависимости
#    Подготовка cron
RUN uv pip install --system --no-deps -e . && \
    touch /var/log/cron.log && chown docker:docker /var/log/cron.log && \
    mkdir -p ./config && chown -R docker:docker ./config

# Копируем остальное (эти файлы мешают кешированию последующих слоев)
COPY --chmod=755 crontab startup.sh .

# Запускаем cron и читаем лог
# cron не видит переменные окружения, переданные главному процессу, точнее
# он начинает новую сессию, где тот же $CONFIG_DIR пуст
CMD printenv | grep -E 'CONFIG_DIR|HH_PROFILE_ID' >> /etc/environment && \
    chown -R docker:docker ./config && \
    dos2unix -n ./crontab /tmp/crontab && \
    crontab -u docker /tmp/crontab && \
    cron && \
    tail -f /var/log/cron.log
