# Future work: cloud deployment (not implemented)

This project runs locally with SQLite. It has not been deployed to any cloud service, and nothing in this repository is built or tested for one.

If it were deployed, a reasonable direction would be:

- Run the FastAPI app as a container on a managed service (for example AWS Lambda behind API Gateway, or a container service).
- Replace the bundled SQLite file with a managed read-only database or a query service over files in object storage, because a Lambda filesystem is read-only and temporary.
- Keep the API key in a secrets manager and add authentication and rate limiting in front of `/api/query`.
- Add centralised logs and metrics for the reasoning trace and request latency.

These are ideas for further work, not features of the current submission.