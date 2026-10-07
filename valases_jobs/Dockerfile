FROM python:3.12-slim
WORKDIR /service
COPY valases_jobs/requirements.txt /service/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY valases_jobs /service/valases_jobs
RUN useradd --create-home jobsuser
USER jobsuser
EXPOSE 8010
CMD ["uvicorn", "valases_jobs.main:app", "--host", "0.0.0.0", "--port", "8010"]

