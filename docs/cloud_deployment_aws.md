# Future Work: Cloud Deployment

> **This document describes potential future architecture only — nothing here is implemented.**
> The current application runs locally as a single Python/FastAPI process with SQLite.

## Possible AWS Serverless Architecture

The application could be deployed to AWS as follows:

1. **Compute**: Package with Docker; run as an AWS Lambda Container Image behind Amazon API Gateway (using the `mangum` ASGI adapter).
2. **Database**: Replace SQLite with Amazon Aurora Serverless (PostgreSQL) or query S3 Parquet files via Amazon Athena.
3. **LLM**: Replace the `google-genai` SDK with the Amazon Bedrock Converse API (e.g. Claude 3.x).
4. **Static assets**: Serve `static/` from Amazon S3 + CloudFront.
5. **CI/CD**: GitHub Actions → push Docker image to ECR → update Lambda.

This would require significant rework of `database.py`, `llm_client.py`, and the ETL pipeline.
There is no `deploy.yml` workflow in this repository.
