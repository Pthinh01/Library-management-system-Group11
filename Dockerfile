FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 library \
    && mkdir -p /app/data /app/test-results \
    && chown -R library:library /app
COPY --chown=library:library app.py Source_code.py database.py run_tests.py ./
COPY --chown=library:library static ./static
COPY --chown=library:library tests ./tests
USER library
EXPOSE 8765
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "8765"]
