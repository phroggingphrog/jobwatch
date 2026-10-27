"""Canonical configuration for paid execution and read-only candidate readiness."""
from jobwatch.settings import DEFAULT_MODEL
from pipeline.agentic.contracts import AgenticError


def agentic_settings(config):
    root = config.settings if hasattr(config, 'settings') else config
    pipeline = root.get('pipeline')
    raw = pipeline.get('agentic', {}) if isinstance(pipeline, dict) and 'agentic' in pipeline else root.get('agentic', {})
    return raw if isinstance(raw, dict) else {}


def runtime_config(config):
    raw = agentic_settings(config)
    autonomous = raw.get('autonomous_evaluation', False)
    if type(autonomous) is not bool:
        raise AgenticError('invalid_configuration')
    credential_index = raw.get('credential_index', 0)
    if type(credential_index) is not int or credential_index < 0:
        raise AgenticError('invalid_configuration')
    if type(raw.get('research_enabled', False)) is not bool:
        raise AgenticError('invalid_configuration')
    from jobwatch.model_choice import chosen   # the person's own pick wins over config/jobwatch.yaml
    pick = chosen()
    values = {'worker_model': pick.get('writer') or raw.get('worker_model', DEFAULT_MODEL),
              'evaluator_model': pick.get('evaluator') or raw.get('evaluator_model', DEFAULT_MODEL),
              'reviewer_model': pick.get('reviewer') or raw.get('reviewer_model', DEFAULT_MODEL),
              'answer_model': pick.get('answers') or raw.get('answer_model', DEFAULT_MODEL),
              'credential_index': credential_index,
              'embedding_model': raw.get('embedding_model'),
              'research_enabled': raw.get('research_enabled', False),
              'job_token_ceiling': int(raw.get('job_token_ceiling', 250_000)),
              'batch_token_ceiling': int(raw.get('batch_token_ceiling', 2_000_000)),
              'job_seconds': min(900, float(raw.get('job_seconds', 900))),
              'batch_seconds': min(1800, float(raw.get('batch_seconds', 1800)))}
    if autonomous:
        values['autonomous_evaluation'] = True
        from pipeline.agentic.autonomous import version
        values['autonomous_version'] = version()
    if values['embedding_model'] is not None:
        from pipeline.agentic.execution import embedding_model_allowed
        if not embedding_model_allowed(values['embedding_model']):
            raise AgenticError('invalid_configuration')
    for name in ('occupation_reference_path', 'occupation_mappings_path'):
        value = raw.get(name)
        if value is not None and (type(value) is not str or not value.strip()):
            raise AgenticError('invalid_configuration')
        values[name] = value
    if any(values[k] <= 0 for k in ('job_token_ceiling', 'batch_token_ceiling', 'job_seconds', 'batch_seconds')):
        raise AgenticError('invalid_configuration')
    return values
