FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir cryptography \
    && useradd --create-home --uid 10001 library \
    && chown library:library /app
COPY --chown=library:library Source_code.py ./
USER library
EXPOSE 8765
CMD ["python", "Source_code.py", "--host", "0.0.0.0", "--port", "8765"]
