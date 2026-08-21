FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY data ./data
# LoincTableCore only (~25MB): the published LOINC term list used to reject
# UMLS results that are not real LOINC codes. The 80MB full LoincTable and the
# ~900MB AccessoryFiles are not needed at runtime.
COPY loinc/LoincTableCore ./loinc/LoincTableCore
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000
CMD ["uvicorn", "aquafhir.main:app", "--host", "0.0.0.0", "--port", "8000"]

