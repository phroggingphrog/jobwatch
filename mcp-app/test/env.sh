# Fake tokens for local tests against the mock backend. Not real credentials.
export JOBWATCH_CONNECTOR_TOKEN=$(printf 'b%.0s' {1..40}) JOBWATCH_BACKEND_URL=http://127.0.0.1:18941 JOBWATCH_MCP_PUBLIC_URL=http://127.0.0.1:18942
