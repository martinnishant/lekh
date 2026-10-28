FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# build the corpus and the review record at image build time, so the container
# starts with a console that already has something to show
RUN python -m lekh.cli generate \
 && python -m lekh.cli check \
 && python -m lekh.cli run \
 && python -m lekh.cli eval \
 && python -m lekh.cli html
EXPOSE 8000
CMD ["sh", "-c", "uvicorn lekh.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
