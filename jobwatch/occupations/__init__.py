"""Public occupational references and advisory field discovery."""

ALGORITHM_VERSION = 'field-discovery-v1'

ERROR_CODES = frozenset({
    'discovery_failed', 'dataset_missing', 'dataset_manifest_invalid',
    'dataset_hash_mismatch', 'dataset_url_refused', 'dataset_too_large',
    'dataset_unpinned', 'dataset_path_refused', 'dataset_disabled',
    'dataset_download_failed', 'dataset_schema_changed', 'reference_invalid',
    'daily_budget', 'embedding_not_configured', 'invalid_configuration',
    'invalid_vector', 'no_policy', 'no_profile_facts', 'reference_index_incomplete',
    'reference_unavailable', 'invalid_request', 'no_confirmed_profile',
    'confirmed_scope_unavailable', 'discovery_not_prepared',
})


class DiscoveryError(ValueError):
    """Safe fixed-code discovery failure; never includes underlying input text."""

    def __init__(self, code: str):
        if not isinstance(code, str) or code not in ERROR_CODES:
            code = 'discovery_failed'
        self.code = code
        super().__init__(code)
