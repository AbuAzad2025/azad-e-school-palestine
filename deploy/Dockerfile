FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# خط عربي مضمّن لتوليد PDF (Amiri — رخصة OFL؛ انظر deploy/fonts/OFL.txt)
ENV PDF_FONT_DIR=/app/deploy/fonts

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    gettext \
    # AZ-P1-10: cron لتشغيل المهام المجدولة داخل صورة واحدة (خدمة scheduler)
    cron \
    && rm -rf /var/lib/apt/lists/*

# سجلات المهام المجدولة (deploy/crontab يكتب فيها)
RUN mkdir -p /var/log/azad

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN python scripts/build_css.py && \
    pybabel compile -d app/translations

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "run:app"]