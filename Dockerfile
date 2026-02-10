FROM python:3.11-slim

# Отключаем буферизацию (чтобы логи Celery сразу шли в консоль)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала копируем только requirements, чтобы кэшировать установку библиотек
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Код мы не копируем (COPY . .), так как будем пробрасывать его через Volume
# Но для финальной сборки эта строчка обычно нужна.
# Для dev-режима она не повредит, но будет "перекрыта" вольюмом.
COPY . .