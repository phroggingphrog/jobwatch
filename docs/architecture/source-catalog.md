# Jobwatch source catalog

Static enumeration on 2026-10-27. Live baseline: `9111a0d`; pending checkout: `7a37865` plus uncommitted corrections. Source inventory is not runtime reachability or test evidence. No runtime data was read.

[Architecture and assessment cost trace](codebase-map.md)

Python entries list top-level classes/functions and statically named local imports. Dynamic routing, dependency injection and string tool dispatch require the architecture narrative; imports alone are not a call graph. Non-Python files are indexed without inferred call relationships. Test files are verification inventory, not proof of passing checks.

## config (6 files)

### [config/employers.example.yaml](../../config/employers.example.yaml)

Static asset/configuration/tooling entry; inspect the linked source.

### [config/employers.yaml](../../config/employers.yaml)

Static asset/configuration/tooling entry; inspect the linked source.

### [config/feeds.yaml](../../config/feeds.yaml)

Static asset/configuration/tooling entry; inspect the linked source.

### [config/jobwatch.yaml](../../config/jobwatch.yaml)

Static asset/configuration/tooling entry; inspect the linked source.

### [config/rules.yaml](../../config/rules.yaml)

Static asset/configuration/tooling entry; inspect the linked source.

### [config/searches.yaml](../../config/searches.yaml)

Static asset/configuration/tooling entry; inspect the linked source.

## deploy (1 files)

### [deploy/librechat.yaml](../../deploy/librechat.yaml)

Static asset/configuration/tooling entry; inspect the linked source.

## jobwatch (226 files)

### [jobwatch/__init__.py](../../jobwatch/__init__.py)

Symbols: none at module scope.

### [jobwatch/adtext.py](../../jobwatch/adtext.py)

Symbols: `Blocked` (L75), `FetchError` (L79), `_note` (L86), `last_status` (L90), `_WouldRequest` (L95), `_skip` (L99), `looks_like_wall` (L114), `get_text` (L120), `write_retry` (L125), `save_text` (L139), `_save_text` (L143), `parse_seek_page` (L151), `fetch_seek` (L166), `Ref` (L185), `_Resp` (L194), `_decode` (L208), `_read_capped` (L220), `_within` (L241), `_requests_get` (L263), `_do_get` (L283), `_public_name` (L312), `_host_ok` (L325), `_http_get` (L340), `_inner_html` (L372), `_title_words` (L391), `_is_this_ad` (L395), `_accept` (L406), `_json` (L419), `_page_title` (L426), `parse_smartrecruiters` (L437), `fetch_smartrecruiters` (L451), `parse_linkedin_page` (L469), `linkedin_id` (L474), `fetch_linkedin` (L489), `parse_jora_page` (L505), `fetch_jora` (L509), `parse_careers_vic_page` (L528), `fetch_careers_vic` (L532), `parse_oracle` (L554), `fetch_oracle` (L571), `_ld_nodes` (L588), `parse_jsonld_job` (L597), `set_legacy_hosts` (L617), `fetch_jsonld` (L624), `parse_successfactors_page` (L661), `fetch_successfactors` (L665), `parse_pageup_page` (L685), `fetch_pageup` (L689), `parse_pulse` (L708), `fetch_pulse` (L718), `_Fetcher` (L735), `_seek` (L744), `would_request` (L764), `_lever_text` (L784), `_raw_text` (L803), `classify` (L817), `_field` (L834), `_row_extras` (L842), `_ref` (L854), `local_text` (L862), `fetch_state` (L878), `fetch_due` (L883), `_record_fetch` (L897), `wants_fetch` (L909), `is_host_failure` (L925), `ensure_text` (L929), `fetch_host` (L974), `pace` (L980), `lock_path` (L985), `review_lock` (L991).

### [jobwatch/apply/__init__.py](../../jobwatch/apply/__init__.py)

Symbols: none at module scope.

### [jobwatch/apply/answers_agent.py](../../jobwatch/apply/answers_agent.py)

Symbols: `_answer_value` (L32), `_verified_legacy_answers` (L38), `AnswerRefused` (L62), `_hash` (L66), `_json` (L70), `AnswerSources` (L75), `load_answer_sources` (L81), `save_owner_answer` (L129), `_Strict` (L165), `AnswerDraft` (L169), `_Answers` (L186), `_Review` (L190), `_ReadSource` (L196), `_validate_control_value` (L200), `_terminal` (L234), `AnswerPlan` (L239), `answer_application` (L256), `with_career_record` (L371).

Local imports: `jobwatch.apply.paths`, `jobwatch.candidate._private_io`, `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.runtime`.

### [jobwatch/apply/ats.py](../../jobwatch/apply/ats.py)

Symbols: `is_pageup_advert` (L12), `pageup_entry_link` (L19), `challenge_provider` (L43), `challenge_complete` (L57).

### [jobwatch/apply/browser.py](../../jobwatch/apply/browser.py)

Symbols: `package_is_current` (L37), `read_live_fields` (L50), `BrowserService` (L75).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.paths`, `jobwatch.apply.prepare`, `jobwatch.apply.submit_confirm`, `jobwatch.commands.state`, `jobwatch.web`, `jobwatch.web.browser_session`, `pipeline.agentic.liveness`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [jobwatch/apply/browser_remote.py](../../jobwatch/apply/browser_remote.py)

Symbols: `call` (L11), `application_review` (L32), `RemoteBrowserService` (L54), `RemoteBrowserSessions` (L75), `remote_status` (L94).

Local imports: `jobwatch`, `jobwatch.web.browser_session`, `pipeline.agentic.api`, `pipeline.agentic.identity`.

### [jobwatch/apply/career_retrieval.py](../../jobwatch/apply/career_retrieval.py)

Symbols: `career_dir` (L32), `_keep` (L41), `career_facts` (L45), `relevant_facts` (L78).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.openrouter_extras`, `jobwatch.settings`.

### [jobwatch/apply/careerops_cv.py](../../jobwatch/apply/careerops_cv.py)

Symbols: `_esc` (L29), `parse_partial` (L33), `fill_entry` (L51), `_partial` (L67), `_text` (L71), `_lis` (L75), `_role` (L79), `_experience` (L95), `_education` (L115), `_contact` (L129), `_strip_section` (L140), `_ordered_sections` (L150), `cv_html` (L168), `html_to_pdf` (L218), `ats_check` (L232), `render_cv_pdf` (L256).

### [jobwatch/apply/careerops_templates/cv-template.ats.html](../../jobwatch/apply/careerops_templates/cv-template.ats.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/careerops_templates/sections/awards.html](../../jobwatch/apply/careerops_templates/sections/awards.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/careerops_templates/sections/certifications.html](../../jobwatch/apply/careerops_templates/sections/certifications.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/careerops_templates/sections/competencies.html](../../jobwatch/apply/careerops_templates/sections/competencies.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/careerops_templates/sections/education.html](../../jobwatch/apply/careerops_templates/sections/education.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/careerops_templates/sections/experience.html](../../jobwatch/apply/careerops_templates/sections/experience.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/careerops_templates/sections/projects.html](../../jobwatch/apply/careerops_templates/sections/projects.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/careerops_templates/sections/skills.html](../../jobwatch/apply/careerops_templates/sections/skills.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/apply/chain.py](../../jobwatch/apply/chain.py)

Symbols: `DraftRefused` (L36), `_now` (L40), `_event` (L44), `_set_status` (L52), `gate` (L62), `start_draft` (L87), `run_chain` (L143), `ad_reading` (L240), `angle_notes` (L259), `_merge_counts` (L273), `_cited` (L280), `_summary_md` (L291), `draft_status` (L311).

### [jobwatch/apply/cli_ext.py](../../jobwatch/apply/cli_ext.py)

Symbols: `register` (L13), `handle` (L22), `_profile_check` (L56).

### [jobwatch/apply/evidence.py](../../jobwatch/apply/evidence.py)

Symbols: `norm` (L28), `_section_kind` (L38), `_strip_md` (L53), `_sentences` (L60), `extract_cv` (L65), `_yaml_scalars` (L126), `_verbatim_ok` (L144), `extract_profile_yaml` (L164), `extract_taxonomy` (L180), `build_evidence` (L198), `check_evidence` (L215), `Profile` (L229), `load_profile` (L241).

### [jobwatch/apply/jev_forms.py](../../jobwatch/apply/jev_forms.py)

Symbols: `past_employers` (L25), `job_answers` (L35), `answer_catalog` (L62), `_field_text` (L93), `jev_match` (L99), `_norm` (L123), `records_for` (L127), `jev_prefill` (L152), `jev_next_button` (L162).

Local imports: `jobwatch.openrouter_extras`, `jobwatch.web.answers_routes`.

### [jobwatch/apply/paths.py](../../jobwatch/apply/paths.py)

Symbols: `ProfileWriteError` (L22), `pin_profile_dir` (L30), `data_dir` (L45), `profile_dir` (L50), `ledger_dir` (L63), `drafts_dir` (L67), `_inside` (L71), `guard_write` (L79), `ensure_dir` (L87), `safe_write_bytes` (L100), `safe_write_text` (L119).

### [jobwatch/apply/prefill.py](../../jobwatch/apply/prefill.py)

Symbols: `PrefillRefused` (L21), `FillResult` (L26), `private_bytes` (L31), `parse_answers` (L37), `load_answers` (L45), `file_snapshot` (L56), `authorize_manifest` (L76), `parse_documents` (L107), `require_host` (L135), `select_owner_page` (L145), `discover_controls` (L159), `generate_template` (L178), `require_unexpired` (L194), `fill_page` (L199), `main` (L306).

### [jobwatch/apply/prefill_workflow.py](../../jobwatch/apply/prefill_workflow.py)

Symbols: `ApplicationFillResult` (L25), `_url` (L34), `_origin` (L44), `session_id` (L49), `private_write` (L58), `prepare_session` (L68), `validate_plan` (L75), `authorize_workflow` (L146), `_single` (L202), `_scope` (L209), `_identity` (L225), `_intact` (L229), `_allowed_click` (L234), `_fill` (L253), `fill_application` (L359), `discover_application` (L672), `plan_from_discovery` (L729), `_form_digest` (L753), `multipart_digest` (L757), `prepare_next_navigation` (L785).

### [jobwatch/apply/prepare.py](../../jobwatch/apply/prepare.py)

Symbols: `PreparationRefused` (L34), `PreparedApplication` (L39), `saved_answers_path` (L55), `_private_dir` (L59), `_write_json` (L69), `_upload_name` (L75), `_document_role` (L81), `_finish` (L90), `latest_preparation` (L130), `record_owner_review` (L160), `record_owner_answer` (L173), `_follow_application_links` (L190), `prepare_application` (L243).

Local imports: `jobwatch.settings`, `jobwatch.web.ask_cards`, `jobwatch.web.browser_session`.

### [jobwatch/apply/render.py](../../jobwatch/apply/render.py)

Symbols: `_candidate` (L27), `headline` (L38), `work_rights` (L44), `pick_templates` (L57), `_md_escape` (L94), `_header_md` (L98), `_claim_text` (L104), `_role_lines` (L114), `cv_markdown` (L129), `letter_markdown` (L179), `to_html` (L199), `render_pdf` (L207).

Local imports: `pipeline.agentic.writing_guide`.

### [jobwatch/apply/requirements.py](../../jobwatch/apply/requirements.py)

Symbols: `structured_block` (L37), `posting_text` (L52), `full_posting_text` (L57), `verify_requirements` (L67), `get_or_extract` (L101).

### [jobwatch/apply/review.py](../../jobwatch/apply/review.py)

Symbols: `drafter_messages` (L102), `reviewer_messages` (L124), `clean_edits` (L134), `reviser_messages` (L148), `_writing_guide` (L156), `_style_options` (L161), `stock_edits` (L165), `repeated_claims` (L196), `drop_repeats` (L212), `drop_stock_framing` (L226), `run_reviewer` (L243).

Local imports: `pipeline.agentic.writing_guide`.

### [jobwatch/apply/submit_confirm.py](../../jobwatch/apply/submit_confirm.py)

Symbols: `SubmitRefused` (L45), `form_state` (L49), `control_label` (L62), `digest` (L66), `record_control` (L76), `final_control` (L89), `live_digest` (L106), `ensure` (L114), `queue` (L122), `pending` (L138), `settle` (L153), `verdict` (L159), `outcome` (L169).

### [jobwatch/apply/verify.py](../../jobwatch/apply/verify.py)

Symbols: `_numbers` (L58), `_months` (L65), `_caps` (L69), `_word_in` (L90), `_years_between` (L94), `ClaimVerifier` (L105), `iter_claims` (L208), `assign_ids` (L226), `verify_draft` (L242).

### [jobwatch/apply/verify_pdf.py](../../jobwatch/apply/verify_pdf.py)

Symbols: `pdf_pages` (L32), `pdf_text` (L38), `compact` (L43), `garbage_reasons` (L47), `keywords` (L68), `coverage` (L78), `required_spans` (L92), `verify_pdf` (L106).

### [jobwatch/baseline_cli.py](../../jobwatch/baseline_cli.py)

Symbols: `register` (L15), `handle` (L40), `_freeze` (L54), `_gate_state` (L72), `_list` (L77), `_show` (L89), `_is_terminal` (L114), `_label` (L121).

Local imports: `pipeline.agentic`, `pipeline.agentic.contracts`.

### [jobwatch/candidate/__init__.py](../../jobwatch/candidate/__init__.py)

Symbols: none at module scope.

### [jobwatch/candidate/_private_io.py](../../jobwatch/candidate/_private_io.py)

Symbols: `PathEscapeError` (L9), `read_profile_source` (L15), `read_regular_file` (L36).

### [jobwatch/candidate/analysis.py](../../jobwatch/candidate/analysis.py)

Symbols: `_error` (L25), `_cosine` (L29), `_clusters` (L36), `analyse_candidate` (L81), `analysis_metadata` (L205), `structural_summary` (L229).

### [jobwatch/candidate/assessment.py](../../jobwatch/candidate/assessment.py)

Symbols: `NoArguments` (L26), `OccupationSelection` (L30), `occupation_details` (L34), `EvidenceSelection` (L41), `CandidateStrength` (L45), `CandidateGap` (L50), `CandidateTargetPath` (L57), `CandidateFindings` (L69), `CandidateAssessment` (L84), `assessment_run_key` (L107), `evidence_records` (L114), `verify_candidate_citations` (L121), `validate_assessment` (L133), `evaluate_candidate` (L155), `assessment_metadata` (L209).

Local imports: `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.runtime`.

### [jobwatch/candidate/contracts.py](../../jobwatch/candidate/contracts.py)

Symbols: `_validate_mapping_primitives` (L14), `StrictFrozen` (L25), `CandidateError` (L34), `digest` (L39), `content_hash` (L51), `validate_hash_64` (L56), `canonicalize_family` (L65), `excluded_families` (L105), `default_allowed_families` (L111), `__getattr__` (L117), `EducationStatusEvidence` (L129), `EvidenceItem` (L156), `compute_bundle_hash` (L228), `EvidenceBundle` (L241), `Dwa` (L313), `Occupation` (L326), `Crosswalk` (L380), `ReferenceBundle` (L409), `Mapping` (L542), `TargetPolicy` (L575), `OccupationFit` (L645), `ArchetypeProposal` (L698), `AnalysisResult` (L720).

### [jobwatch/candidate/data/occupation-reference.json](../../jobwatch/candidate/data/occupation-reference.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/candidate/data/source-manifest.json](../../jobwatch/candidate/data/source-manifest.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/candidate/eligibility.py](../../jobwatch/candidate/eligibility.py)

Symbols: `EligibilityDecision` (L19), `_result` (L24), `_rights_text` (L28), `_scan_requirements` (L37), `_rights_kinds` (L91), `_partition_requirements` (L95), `_requirements` (L124), `_rights` (L152), `_onsite_locations` (L214), `_offers_australian_alternative` (L240), `_advertised_hours` (L248), `evaluate_eligibility` (L274).

Local imports: `jobwatch`, `jobwatch.models`, `jobwatch.reader`, `pipeline.agentic.location`.

### [jobwatch/candidate/evidence.py](../../jobwatch/candidate/evidence.py)

Symbols: `_error` (L24), `_open_source` (L28), `_parse_yaml` (L49), `_end_line` (L87), `_line_contains` (L95), `_contact` (L100), `_extract_primary` (L105), `snapshot_evidence` (L127), `bundle_from_contents` (L140), `_build_snapshot` (L160), `validate_annotation` (L322), `verify_evidence_snapshot` (L341), `bind_career_profile` (L360), `career_profile_text` (L390).

Local imports: `jobwatch.apply.evidence`, `jobwatch.textdates`.

### [jobwatch/candidate/inputs.py](../../jobwatch/candidate/inputs.py)

Symbols: `load_inputs` (L14).

### [jobwatch/candidate/intake.py](../../jobwatch/candidate/intake.py)

Symbols: `_kinds` (L100), `_states_status` (L106), `IntakeError` (L114), `Basis` (L122), `_Model` (L128), `SourceRef` (L132), `ProfileFact` (L138), `Question` (L148), `Proposal` (L155), `_extract` (L168), `extract_text` (L223), `_root` (L233), `_write_private` (L237), `_locked` (L254), `_read_json` (L265), `save_upload` (L272), `_numbered` (L319), `_verified` (L323), `_check` (L337), `_load_docs` (L365), `upload_ids_for` (L385), `require_route` (L399), `estimate_parse_tokens` (L410), `_model_parse` (L416), `_add_unknowns` (L437), `_claim` (L454), `_release` (L461), `propose` (L466), `_merge` (L490), `_finish_parse` (L516), `_parse_worker` (L529), `_spawn` (L557), `start_proposal` (L563), `add_uploads` (L590), `open_proposal` (L619), `upload_profile_files` (L636), `_fact_key` (L662), `_mark_replacements` (L671), `save_proposal` (L690), `load_proposal` (L697), `_new_id` (L719), `_person_fact` (L723), `_value` (L729), `_mutate` (L736), `edit` (L752), `answer` (L781), `digest` (L794), `SearchScope` (L809), `_reconciled` (L816), `_values` (L824), `scope_for` (L829), `_scope_of` (L837), `_scope_digest` (L846), `confirmation` (L850), `_versions_root` (L862), `_numbers` (L866), `_approved` (L873), `current_version` (L877), `versions` (L883), `_write_profile` (L889), `_finish` (L923), `_refuse_hand_edits` (L935), `confirm` (L948), `adopt_existing` (L1051), `_confirmed_scope` (L1096), `discovery_scope` (L1112).

Local imports: `pipeline.agentic`, `pipeline.agentic.discovery_settings`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [jobwatch/candidate/mapping.py](../../jobwatch/candidate/mapping.py)

Symbols: `_error` (L8), `validate_mappings` (L12).

### [jobwatch/candidate/person.py](../../jobwatch/candidate/person.py)

Symbols: `_yaml` (L14), `work_rights` (L28), `hours_limit_per_fortnight` (L36), `full_time_programs_ok` (L47), `target_roles` (L52), `excluded_families` (L57), `field_phrase` (L73).

Local imports: `jobwatch.apply.paths`.

### [jobwatch/candidate/policy.py](../../jobwatch/candidate/policy.py)

Symbols: `default_policy` (L16), `profile_target_policy` (L25), `ExclusionRule` (L42), `DecisionPolicy` (L50), `_text` (L71), `_evidence` (L79), `_status_kinds` (L84), `strategy_for` (L89), `_short_hash` (L100), `_work_type` (L104), `rules_from_fact` (L108), `_affirmed` (L167), `_clauses` (L172), `_negated` (L177), `_spoken` (L183), `person_asserted` (L187), `_places_in` (L210), `_levels_in` (L232), `_number` (L245), `_home` (L256), `_fact_code` (L273), `build_policy` (L278), `_current` (L434), `_policy_from` (L443), `policy_for` (L453), `_questions` (L458), `describe` (L475), `_word_in` (L487), `_location_hit` (L495), `_str` (L506), `exclusion_hit` (L510).

Local imports: `jobwatch`, `jobwatch.place`, `pipeline.agentic.location`.

### [jobwatch/candidate/presentation.py](../../jobwatch/candidate/presentation.py)

Symbols: `statistical_view` (L7).

### [jobwatch/candidate/projection.py](../../jobwatch/candidate/projection.py)

Symbols: `_facts` (L19), `_text` (L24), `_exclusion` (L30), `_uniq` (L37), `_number` (L41), `_work_rights` (L50), `_line` (L87), `_quotes` (L93), `_resume` (L99), `_dump` (L119), `project` (L123).

### [jobwatch/candidate/reference.py](../../jobwatch/candidate/reference.py)

Symbols: `_error` (L14), `_open_reference` (L18), `_unique_object` (L35), `_parse_reference` (L44), `load_reference` (L51), `verify_reference_snapshot` (L66), `crosswalk_codes` (L81).

### [jobwatch/candidate/rules.py](../../jobwatch/candidate/rules.py)

Symbols: `RuleError` (L27), `_root` (L33), `_load` (L37), `listing` (L46), `propose` (L58), `carry_facts` (L95), `_finish` (L109), `confirm` (L126).

Local imports: `jobwatch`, `jobwatch.apply.paths`.

### [jobwatch/candidate/suggestions.py](../../jobwatch/candidate/suggestions.py)

Symbols: `terms` (L16), `suggest_mappings` (L21).

### [jobwatch/cli.py](../../jobwatch/cli.py)

Symbols: `_print_run` (L24), `all_failed` (L35), `_extensions` (L42), `main` (L59), `_main` (L100).

Local imports: `pipeline`, `pipeline.agentic`.

### [jobwatch/collectors/__init__.py](../../jobwatch/collectors/__init__.py)

Symbols: `get` (L18).

### [jobwatch/collectors/ats_ashby.py](../../jobwatch/collectors/ats_ashby.py)

Symbols: `parse` (L11), `fetch_one` (L41), `collect` (L48).

### [jobwatch/collectors/ats_atlassian.py](../../jobwatch/collectors/ats_atlassian.py)

Symbols: `_place` (L20), `row_to_posting` (L26), `fetch_one` (L41), `collect` (L48).

### [jobwatch/collectors/ats_elmo.py](../../jobwatch/collectors/ats_elmo.py)

Symbols: `robots_allows` (L30), `check_robots` (L72), `parse_list` (L84), `fetch_one` (L112), `collect` (L119).

### [jobwatch/collectors/ats_employmenthero.py](../../jobwatch/collectors/ats_employmenthero.py)

Symbols: `parse` (L17), `fetch_one` (L52), `collect` (L66).

### [jobwatch/collectors/ats_greenhouse.py](../../jobwatch/collectors/ats_greenhouse.py)

Symbols: `parse` (L11), `fetch_one` (L34), `collect` (L40).

### [jobwatch/collectors/ats_jobs_search.py](../../jobwatch/collectors/ats_jobs_search.py)

Symbols: `_all` (L28), `parse_list` (L32), `fetch_one` (L64), `collect` (L73).

### [jobwatch/collectors/ats_lever.py](../../jobwatch/collectors/ats_lever.py)

Symbols: `parse` (L10), `fetch_one` (L37), `collect` (L46).

### [jobwatch/collectors/ats_oracle.py](../../jobwatch/collectors/ats_oracle.py)

Symbols: `api_url` (L22), `_locations` (L37), `req_to_posting` (L46), `fetch_one` (L74), `collect` (L97).

Local imports: `pipeline.agentic.location`.

### [jobwatch/collectors/ats_pageup.py](../../jobwatch/collectors/ats_pageup.py)

Symbols: `parse_feed` (L17), `fetch_one` (L45), `collect` (L54).

### [jobwatch/collectors/ats_phenom.py](../../jobwatch/collectors/ats_phenom.py)

Symbols: `page_state` (L26), `_slug` (L46), `job_to_posting` (L50), `fetch_one` (L75), `collect` (L117).

### [jobwatch/collectors/ats_pulse.py](../../jobwatch/collectors/ats_pulse.py)

Symbols: `host_of` (L23), `api_url` (L27), `parse_jobs` (L31), `fetch_one` (L58), `collect` (L68).

### [jobwatch/collectors/ats_recruitmenthub.py](../../jobwatch/collectors/ats_recruitmenthub.py)

Symbols: `list_url` (L29), `parse_list` (L33), `fetch_one` (L59), `collect` (L66).

### [jobwatch/collectors/ats_scouttalent.py](../../jobwatch/collectors/ats_scouttalent.py)

Symbols: `parse_index` (L26), `fetch_one` (L75), `collect` (L81).

### [jobwatch/collectors/ats_smartrecruiters.py](../../jobwatch/collectors/ats_smartrecruiters.py)

Symbols: `to_posting` (L18), `detail_text` (L37), `fetch_one` (L44), `collect` (L71).

### [jobwatch/collectors/ats_successfactors.py](../../jobwatch/collectors/ats_successfactors.py)

Symbols: `fetch_one` (L19), `collect` (L32).

### [jobwatch/collectors/ats_techone.py](../../jobwatch/collectors/ats_techone.py)

Symbols: `parse_dataset` (L20), `fetch_one` (L42), `collect` (L48).

### [jobwatch/collectors/ats_workable.py](../../jobwatch/collectors/ats_workable.py)

Symbols: `parse` (L11), `fetch_one` (L36), `collect` (L42).

### [jobwatch/collectors/ats_workday.py](../../jobwatch/collectors/ats_workday.py)

Symbols: `_path_words` (L18), `row_to_posting` (L24), `fetch_one` (L58), `collect` (L110).

### [jobwatch/collectors/base.py](../../jobwatch/collectors/base.py)

Symbols: `CollectorContext` (L20), `run_per_employer` (L59), `rotate` (L80), `first` (L90).

### [jobwatch/collectors/careers_vic.py](../../jobwatch/collectors/careers_vic.py)

Symbols: `normalise_grade` (L35), `parse_page` (L44), `collect` (L78).

### [jobwatch/collectors/jobspy_src.py](../../jobwatch/collectors/jobspy_src.py)

Symbols: `_clean` (L21), `_Capture` (L33), `capture_jobspy_logs` (L43), `row_to_posting` (L60), `collect` (L87).

### [jobwatch/collectors/jora.py](../../jobwatch/collectors/jora.py)

Symbols: `_text` (L37), `posted_from` (L41), `parse` (L52), `collect` (L80).

Local imports: `jobwatch.place`.

### [jobwatch/collectors/jsonld_pages.py](../../jobwatch/collectors/jsonld_pages.py)

Symbols: `_Page` (L30), `job_postings` (L63), `_addresses` (L88), `_title` (L102), `_slug` (L106), `page_job_urls` (L110), `_plain_host` (L126), `same_site` (L143), `site_hosts` (L148), `to_posting` (L157), `detail_links` (L215), `fetch_one` (L246), `collect` (L292).

### [jobwatch/collectors/reddit.py](../../jobwatch/collectors/reddit.py)

Symbols: `feed_url` (L28), `_compile` (L36), `classify` (L40), `parse` (L60), `collect` (L103).

Local imports: `jobwatch.place`, `pipeline.agentic.location`.

### [jobwatch/collectors/rss.py](../../jobwatch/collectors/rss.py)

Symbols: `parse_generic` (L23), `split_title_location` (L49), `parse_successfactors` (L66), `fetch_conditional` (L103), `collect` (L122).

### [jobwatch/collectors/seek.py](../../jobwatch/collectors/seek.py)

Symbols: `to_posting` (L20), `collect` (L45).

Local imports: `jobwatch.place`.

### [jobwatch/commands/__init__.py](../../jobwatch/commands/__init__.py)

Symbols: none at module scope.

### [jobwatch/commands/apply_api.py](../../jobwatch/commands/apply_api.py)

Symbols: `DraftUnavailable` (L15), `_chain` (L19), `start_draft` (L28), `draft_status` (L32), `ledger` (L36), `upsert` (L42), `append` (L52).

### [jobwatch/commands/state.py](../../jobwatch/commands/state.py)

Symbols: `StatusError` (L25), `check_status` (L29), `match_info` (L38), `application_for_match` (L44), `label` (L50), `set_status` (L57), `open_applications` (L91).

### [jobwatch/config.py](../../jobwatch/config.py)

Symbols: `_merge` (L39), `_load` (L49), `Config` (L57), `load_config` (L79).

### [jobwatch/db.py](../../jobwatch/db.py)

Symbols: `connect` (L512), `_statements` (L530), `migrate` (L542), `ts` (L569), `get_state` (L574), `set_state` (L579), `start_run` (L588), `finish_run` (L595), `record_health` (L602), `last_ok` (L630), `prune` (L636).

### [jobwatch/dedupe.py](../../jobwatch/dedupe.py)

Symbols: `_norm` (L23), `city_of` (L30), `dedupe_key` (L36), `ingest` (L42).

### [jobwatch/digest.py](../../jobwatch/digest.py)

Symbols: `gather` (L14), `render` (L50), `run_digest` (L77).

### [jobwatch/discovery_gate.py](../../jobwatch/discovery_gate.py)

Symbols: `profile_location_rule` (L8), `allowed` (L31).

Local imports: `pipeline.agentic.location`.

### [jobwatch/evaluation_cli.py](../../jobwatch/evaluation_cli.py)

Symbols: `register` (L10), `handle` (L42), `_handle` (L56).

Local imports: `jobwatch.baseline_cli`, `jobwatch.config`, `jobwatch.reports.evaluation`, `pipeline.agentic`, `pipeline.agentic.contracts`.

### [jobwatch/execution_mode.py](../../jobwatch/execution_mode.py)

Symbols: `effective_mode` (L5).

### [jobwatch/expiry.py](../../jobwatch/expiry.py)

Symbols: `_iso` (L20), `fill_missing` (L24), `record` (L32), `sweep` (L53).

Local imports: `pipeline.agentic.liveness`.

### [jobwatch/fieldgen.py](../../jobwatch/fieldgen.py)

Symbols: `_slug` (L22), `_loc` (L26), `generate_config` (L31).

### [jobwatch/filters.py](../../jobwatch/filters.py)

Symbols: `_phrase` (L13), `_regexes` (L17), `Arm` (L22), `Decision` (L31), `Rules` (L41).

### [jobwatch/followup_drafts.py](../../jobwatch/followup_drafts.py)

Symbols: `capture` (L21), `_payload` (L45), `_rows` (L57), `load_draft` (L61), `generate` (L81).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.followup_events`, `pipeline.agentic.contracts`, `pipeline.agentic.followup`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [jobwatch/followup_events.py](../../jobwatch/followup_events.py)

Symbols: `FollowupEventError` (L17), `_time` (L21), `_events` (L31), `_latest` (L60), `history` (L69), `application_cadence` (L100), `record_event` (L105), `recent_events` (L173).

Local imports: `jobwatch`, `jobwatch.followups`, `jobwatch.place`.

### [jobwatch/followups.py](../../jobwatch/followups.py)

Symbols: `FollowupPin` (L15), `FollowupHistory` (L21), `FollowupCadence` (L33), `cadence` (L46).

### [jobwatch/google_gmail.py](../../jobwatch/google_gmail.py)

Symbols: `_call` (L16), `search_messages` (L24), `get_message` (L29), `create_draft` (L33), `archive` (L43), `trash` (L47), `to_gmail_query` (L52), `_header` (L59), `_text` (L66), `GmailMcp` (L72).

### [jobwatch/google_oauth.py](../../jobwatch/google_oauth.py)

Symbols: `GoogleNotConfigured` (L30), `_env` (L34), `configured` (L44), `_key` (L53), `make_state` (L57), `check_state` (L63), `build_consent_url` (L87), `token_path` (L96), `load` (L100), `_save` (L107), `_email_from_id_token` (L118), `_token_request` (L126), `exchange_code` (L133), `refresh` (L144), `access_token` (L157), `disconnect` (L166).

### [jobwatch/http.py](../../jobwatch/http.py)

Symbols: `HttpError` (L25), `Blocked` (L32), `Fetcher` (L36).

### [jobwatch/interview_ad.py](../../jobwatch/interview_ad.py)

Symbols: `InterviewAdUnavailable` (L21), `InterviewAd` (L26), `_segment` (L41), `ats_target` (L48), `_plain` (L84), `structured_ad` (L94).

Local imports: `jobwatch.candidate.contracts`, `pipeline.agentic.research`.

### [jobwatch/interview_browser.py](../../jobwatch/interview_browser.py)

Symbols: `public_posting_urls` (L24), `PublicBrowserTransport` (L41), `_liveness` (L105), `_UncertainDeadline` (L119), `_closing_date` (L123), `_same_posting` (L195), `_same_host_path_stem` (L208), `_snapshot_ad` (L214), `browser_ad` (L240), `acquire_ad` (L306), `indeed_ad` (L321), `seek_ad` (L349), `jora_ad` (L380), `http_ad` (L399).

Local imports: `jobwatch.adtext`, `jobwatch.collectors.jsonld_pages`, `jobwatch.interview_ad`, `jobwatch.models`, `jobwatch.place`, `pipeline.agentic.research`.

### [jobwatch/interview_inputs.py](../../jobwatch/interview_inputs.py)

Symbols: `InterviewInputs` (L13), `_posting` (L28), `load_inputs` (L34), `save_inputs` (L46).

Local imports: `jobwatch`, `pipeline.agentic.contracts`.

### [jobwatch/interview_prep.py](../../jobwatch/interview_prep.py)

Symbols: `_run_table` (L22), `_run_row` (L28), `_save_run` (L33), `_subject_capture` (L38), `capture` (L51), `_payload` (L81), `load_report` (L93), `generate` (L110), `should_prepare_after_interview` (L181), `enqueue` (L196), `queued_posting_ids` (L220), `is_queued` (L261), `queued_subject_ids` (L271), `matching_posting` (L297).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.interview_inputs`, `jobwatch.interview_subjects`, `jobwatch.models`, `pipeline.agentic.contracts`, `pipeline.agentic.interview`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [jobwatch/interview_subjects.py](../../jobwatch/interview_subjects.py)

Symbols: `_Subject` (L25), `_id` (L30), `_inputs` (L35), `_ad` (L44), `_detail` (L65), `load_subject` (L70), `create_subject` (L89), `save_subject_inputs` (L119).

Local imports: `jobwatch`, `jobwatch.interview_ad`, `jobwatch.interview_inputs`, `jobwatch.models`, `pipeline.agentic.contracts`.

### [jobwatch/ledger.py](../../jobwatch/ledger.py)

Symbols: `ReindexRefused` (L38), `_kind` (L42), `path_for` (L49), `_now` (L53), `append` (L57), `read` (L83), `_columns` (L99), `_pk` (L106), `_write_row` (L113), `upsert` (L133), `snapshot` (L150), `_row_records` (L160), `reindex` (L175).

### [jobwatch/llm.py](../../jobwatch/llm.py)

Symbols: `LLMError` (L39), `DeadlineExceeded` (L43), `SafeLLMError` (L47), `_price` (L54), `_read_env_file` (L66), `load_keys` (L80), `_invoke_call` (L102), `parse_json` (L117), `LLMResult` (L142), `_requests_transport` (L155), `_rejected_options` (L171), `_overloaded` (L179), `LLM` (L187).

### [jobwatch/model_choice.py](../../jobwatch/model_choice.py)

Symbols: `ModelRefused` (L40), `_cfg_dir` (L44), `_read` (L48), `_write_private` (L56), `refusal` (L66), `check` (L74), `_from_config` (L82), `chosen` (L93), `get_model` (L97), `set_models` (L103), `gateway_profile` (L128), `set_gateway_profile` (L152), `apply_profile` (L165), `valid_url` (L173), `own_gateway` (L177), `gateway_url` (L184), `own_key` (L189), `set_gateway` (L194), `gateway_view` (L209).

### [jobwatch/models.py](../../jobwatch/models.py)

Symbols: `Posting` (L26), `now_utc` (L68), `canonical_url` (L75), `url_hash` (L92), `html_to_text` (L104), `clean_text` (L119), `fold` (L126), `parse_date` (L135), `iso` (L167), `relative_posted` (L172), `state_of` (L233), `is_australian` (L244), `work_type_of` (L259), `salary_from_text` (L278).

### [jobwatch/notifier/__init__.py](../../jobwatch/notifier/__init__.py)

Symbols: none at module scope.

### [jobwatch/notifier/channels.py](../../jobwatch/notifier/channels.py)

Symbols: `Receipt` (L30), `_receipt` (L40), `Channel` (L44), `resolve_ref` (L52), `value` (L68), `NoneChannel` (L74), `SshAppendChannel` (L87), `CommandChannel` (L116), `WebhookChannel` (L140), `register_kind` (L174), `build` (L180), `validate_config` (L186).

Local imports: `jobwatch`.

### [jobwatch/notifier/cli.py](../../jobwatch/notifier/cli.py)

Symbols: `register` (L18), `_conn` (L38), `_show` (L44), `handle` (L51).

Local imports: `jobwatch`, `jobwatch.config`, `jobwatch.db`.

### [jobwatch/notifier/events.py](../../jobwatch/notifier/events.py)

Symbols: `FailurePayload` (L14), `CompletionPayload` (L23), `ActionRequiredPayload` (L31), `Event` (L41).

### [jobwatch/notifier/legacy.py](../../jobwatch/notifier/legacy.py)

Symbols: `present_state` (L19).

### [jobwatch/notifier/schema.py](../../jobwatch/notifier/schema.py)

Symbols: none at module scope.

### [jobwatch/notifier/service.py](../../jobwatch/notifier/service.py)

Symbols: `ChannelConfig` (L29), `DeliveryResult` (L43), `ensure` (L56), `_person` (L63), `_now_text` (L68), `_row_to_config` (L73), `stored_channels` (L80), `_alias` (L86), `channels_for` (L98), `add_channel` (L111), `disable_channel` (L135), `_matching` (L150), `digest_window` (L154), `_attempt` (L161), `_duplicate` (L174), `enqueue` (L181), `dispatch` (L198), `deliver` (L232), `test_channel` (L256).

Local imports: `jobwatch`.

### [jobwatch/notify.py](../../jobwatch/notify.py)

Symbols: `ensure` (L35), `_now` (L39), `add` (L43), `is_live` (L51), `notify` (L64), `alert` (L80), `flush` (L95), `_alert_key` (L107), `unread` (L115), `mark_read` (L120).

Local imports: `jobwatch.config`, `jobwatch.db`, `jobwatch.notifier`.

### [jobwatch/occupations/__init__.py](../../jobwatch/occupations/__init__.py)

Symbols: `DiscoveryError` (L16).

### [jobwatch/occupations/datasets.py](../../jobwatch/occupations/datasets.py)

Symbols: `FileSpec` (L26), `DatasetSpec` (L33), `DatasetManifest` (L45), `reference_root` (L118), `_component` (L122), `_no_symlinks` (L127), `dataset_dir` (L135), `_file` (L140), `read_manifest` (L145), `_digest` (L165), `verify_dataset` (L177), `status` (L196), `_allowed_url` (L210), `_download` (L219), `fetch_dataset` (L241), `main` (L299).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.contracts`.

### [jobwatch/occupations/embeddings.py](../../jobwatch/occupations/embeddings.py)

Symbols: `text_key` (L25), `normalise` (L29), `_vector` (L43), `VectorCache` (L49), `_consistent` (L81), `_read_vector` (L86), `VectorStore` (L108), `embed_cached` (L136), `reference_store` (L152), `make_embedder` (L163), `discovery_tokens_since` (L171), `_daily_spent` (L178), `discovery_budget` (L187).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate`, `jobwatch.config`, `pipeline.agentic`, `pipeline.agentic.gateway`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [jobwatch/occupations/hypotheses.py](../../jobwatch/occupations/hypotheses.py)

Symbols: `FieldHypothesis` (L29), `_id` (L44), `select` (L48), `_usable` (L72), `_cache_key` (L85), `_folder` (L93), `_load` (L97), `cached_hypotheses` (L144), `cached_doc_keys` (L149), `_excluded` (L154), `_rank` (L167), `field_hypotheses` (L178).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate`, `jobwatch.candidate._private_io`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `jobwatch.candidate.projection`, `jobwatch.config`, `pipeline.agentic.contracts`, `pipeline.agentic.discovery`, `pipeline.agentic.service`.

### [jobwatch/occupations/loaders.py](../../jobwatch/occupations/loaders.py)

Symbols: `OccupationRecord` (L25), `Correspondence` (L38), `LoadedReference` (L44), `record_text` (L52), `read_sheet` (L68), `_bundled_path` (L100), `load_bundled` (L105), `_rows` (L125), `load_onet` (L139), `load_esco` (L171), `_workbook` (L187), `load_osca` (L197), `_load_cached` (L231), `load_reference_records` (L265).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`.

### [jobwatch/occupations/plan.py](../../jobwatch/occupations/plan.py)

Symbols: `SearchPlan` (L15), `query_for` (L30), `_unique` (L36), `search_plan` (L45), `searches_overlay` (L59), `feeds_overlay` (L87), `title_matches_plan` (L120), `save_plan` (L130), `load_plan` (L135).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.contracts`, `jobwatch.place`, `pipeline.agentic.location`.

### [jobwatch/onboarding.py](../../jobwatch/onboarding.py)

Symbols: `write_profile_file` (L38), `write_user_file` (L55), `style_examples` (L71), `wrangle` (L86), `build_profile` (L127).

### [jobwatch/openrouter_extras.py](../../jobwatch/openrouter_extras.py)

Symbols: `deadline_scope` (L30), `_timeout` (L39), `extras_settings` (L58), `_key` (L64), `_post` (L72), `jev_screen` (L132), `jev_injection` (L144), `same_vacancy` (L157), `embed` (L169), `target_roles_text` (L201), `_cosine` (L212), `_pack` (L218), `_unpack` (L222), `_ensure` (L226), `vectors` (L231), `rank_by_target` (L258).

Local imports: `jobwatch`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.runtime`.

### [jobwatch/origin_guard.py](../../jobwatch/origin_guard.py)

Symbols: `OriginRejected` (L17), `is_loopback_host` (L21), `check_bind` (L31), `_split_host_port` (L38), `check_request` (L50), `_host_only` (L89), `check_web_host` (L93), `check_web_post` (L101).

### [jobwatch/outcomes/__init__.py](../../jobwatch/outcomes/__init__.py)

Symbols: none at module scope.

### [jobwatch/outcomes/callback.py](../../jobwatch/outcomes/callback.py)

Symbols: `hdi_beta` (L17), `_hdi_sampled` (L33), `posterior` (L42), `observed_outcome` (L48), `callback_stats` (L58), `render_lines` (L86).

### [jobwatch/outcomes/classify.py](../../jobwatch/outcomes/classify.py)

Symbols: `Verdict` (L46), `_snippet` (L56), `never_hired` (L62), `classify_rules` (L69), `classify_llm` (L102).

Local imports: `jobwatch.settings`.

### [jobwatch/outcomes/cli_ext.py](../../jobwatch/outcomes/cli_ext.py)

Symbols: `register` (L7), `handle` (L15).

### [jobwatch/outcomes/decide.py](../../jobwatch/outcomes/decide.py)

Symbols: `_batch` (L18), `decide` (L28).

### [jobwatch/outcomes/mcp.py](../../jobwatch/outcomes/mcp.py)

Symbols: `_is_loopback_url` (L23), `ToolNotAllowed` (L33), `McpError` (L37), `_parse_body` (L41), `McpClient` (L51).

### [jobwatch/outcomes/readiness.py](../../jobwatch/outcomes/readiness.py)

Symbols: `outcome_readiness` (L5), `response_time_readiness` (L28).

### [jobwatch/outcomes/sync.py](../../jobwatch/outcomes/sync.py)

Symbols: `_place_words` (L52), `settings_for` (L65), `_norm_mid` (L72), `_domain` (L76), `_parse_dt` (L81), `company_terms` (L91), `_q` (L106), `app_query` (L110), `generic_query` (L121), `_mentions` (L125), `_from_email` (L143), `active_applications` (L152), `changes_status` (L168), `_proposed_at` (L175), `expire` (L182), `render_proposals` (L198), `open_proposals` (L209), `scan` (L220), `new_stats` (L320), `run_outcomes` (L326).

Local imports: `jobwatch.place`, `jobwatch.settings`.

### [jobwatch/pipeline.py](../../jobwatch/pipeline.py)

Symbols: `tier_collectors` (L23), `_alert_status` (L32), `run_collector` (L44), `publish` (L127), `ai_budget` (L151), `run` (L159).

Local imports: `jobwatch.notify`, `pipeline.agentic`, `pipeline.graph`.

### [jobwatch/place.py](../../jobwatch/place.py)

Symbols: `_candidate` (L21), `location_text` (L26), `person_state` (L30), `person_city` (L42), `area_pattern` (L46), `person_timezone` (L55).

### [jobwatch/preference_cli.py](../../jobwatch/preference_cli.py)

Symbols: `register` (L10), `handle` (L17).

Local imports: `jobwatch`, `jobwatch.config`, `jobwatch.preferences`, `jobwatch.preferences.migration`.

### [jobwatch/preference_service.py](../../jobwatch/preference_service.py)

Symbols: `preference_context` (L12), `CurrentRun` (L30), `current_runs` (L41), `pool` (L91), `create_next` (L113), `record_pick` (L129).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `jobwatch.preferences`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`.

### [jobwatch/preferences/__init__.py](../../jobwatch/preferences/__init__.py)

Symbols: none at module scope.

### [jobwatch/preferences/choice_model.jags](../../jobwatch/preferences/choice_model.jags)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/preferences/experience.py](../../jobwatch/preferences/experience.py)

Symbols: `_exact_date` (L8), `candidate_years` (L17).

Local imports: `jobwatch.candidate.contracts`.

### [jobwatch/preferences/features.py](../../jobwatch/preferences/features.py)

Symbols: `PreferenceError` (L24), `canonical` (L27), `digest` (L30), `versions` (L33), `context_hash` (L40), `validate_alternatives` (L43), `family_index` (L82), `alternative_from_evaluation` (L86), `_source_hours` (L180), `hourly_pay` (L205), `posting_age_days` (L230), `_flexible_hours` (L243), `flexible_hours` (L271), `_visa_welcome` (L276), `_overall_experience` (L286).

Local imports: `jobwatch.candidate.contracts`, `pipeline.agentic.contracts`.

### [jobwatch/preferences/fit_choice_model.R](../../jobwatch/preferences/fit_choice_model.R)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/preferences/migration.py](../../jobwatch/preferences/migration.py)

Symbols: `_same_source` (L15), `refeaturise` (L26).

Local imports: `jobwatch`.

### [jobwatch/preferences/model.py](../../jobwatch/preferences/model.py)

Symbols: `parameter_names` (L18), `evaluate_fit` (L22), `prepare_data` (L53), `transform_features` (L83), `fit_store` (L89), `interval` (L125), `predict_set` (L130), `_current_posterior` (L156), `predict_utilities` (L187).

### [jobwatch/preferences/store.py](../../jobwatch/preferences/store.py)

Symbols: `now` (L12), `PreferenceStore` (L15).

### [jobwatch/prescreen/__init__.py](../../jobwatch/prescreen/__init__.py)

Symbols: none at module scope.

### [jobwatch/prescreen/cli.py](../../jobwatch/prescreen/cli.py)

Symbols: `register` (L20), `handle` (L60), `_run` (L72).

Local imports: `jobwatch`, `jobwatch.candidate.policy`, `jobwatch.config`.

### [jobwatch/prescreen/engine.py](../../jobwatch/prescreen/engine.py)

Symbols: `PostingFields` (L25), `Hit` (L36), `Outcome` (L58), `fields_of_row` (L84), `fields_of_posting` (L91), `Engine` (L97).

### [jobwatch/prescreen/lifecycle.py](../../jobwatch/prescreen/lifecycle.py)

Symbols: `_row` (L12), `_ad_text` (L16), `screen_ingested` (L25), `reconsider` (L44), `override_skip` (L66).

Local imports: `jobwatch`, `pipeline`, `pipeline.schemas`.

### [jobwatch/prescreen/seed/rules.json](../../jobwatch/prescreen/seed/rules.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/prescreen/seed/terms.json](../../jobwatch/prescreen/seed/terms.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/prescreen/store.py](../../jobwatch/prescreen/store.py)

Symbols: `_now` (L16), `compile_term` (L21), `_seed` (L39), `ensure_seeds` (L43), `add_term` (L71), `set_term_enabled` (L88), `add_rule` (L94), `set_rule_enabled` (L103), `add_override` (L110), `record_decision` (L117), `latest_decision` (L126), `is_current` (L130), `stats` (L135), `readmit` (L146).

Local imports: `pipeline`, `pipeline.schemas`.

### [jobwatch/prescreen/sync.py](../../jobwatch/prescreen/sync.py)

Symbols: `_rules_for` (L21), `sync_profile` (L78).

### [jobwatch/profile_check.py](../../jobwatch/profile_check.py)

Symbols: `_suggest` (L57), `_kind` (L62), `_section` (L69), `_load` (L82), `check` (L96), `_facts` (L132), `check_code` (L151).

Local imports: `jobwatch.apply.paths`, `jobwatch.notifier`.

### [jobwatch/profile_cli.py](../../jobwatch/profile_cli.py)

Symbols: `register` (L5), `handle` (L12).

### [jobwatch/reader.py](../../jobwatch/reader.py)

Symbols: `_read` (L166), `_phone_spans` (L219), `_spelled_phone` (L234), `_contact_line` (L244), `_redact` (L254), `_preamble_end` (L265), `strip_contact` (L274), `_fence_regex` (L312), `_unescape_once` (L321), `_defang` (L326), `_interests` (L345), `person_prefs` (L354), `settings_block` (L364), `system_prompt` (L379), `interest_path` (L385), `load_interest` (L390), `load_profile` (L401), `settings` (L413), `norm` (L425), `_tokens` (L429), `quote_in_text` (L446), `_overlaps` (L481), `_segments` (L620), `_clause_starts` (L630), `_clause_at` (L635), `_admits` (L642), `_clause_facts` (L656), `_classify` (L664), `_scan_full` (L676), `_scan` (L710), `_ongoing_hides` (L714), `_resolve_ongoing` (L728), `rights_backstop` (L735), `unrestricted_backstop` (L748), `blocking_quote` (L766), `clamp_int` (L773), `parse_years` (L801), `_clean` (L822), `_list` (L826), `_yes` (L839), `_truthy` (L844), `is_sponsored` (L850), `_enum` (L878), `_score` (L888), `_dim` (L900), `_real_job` (L904), `usable_reading` (L915), `normalize_report` (L926), `_blank` (L981), `decide` (L987), `_decide` (L1001), `_col` (L1153), `_days_ago` (L1161), `_age_lines` (L1169), `build_messages` (L1190), `content_hash` (L1206), `privacy_leak` (L1220), `ask` (L1231), `store` (L1266), `_store` (L1271), `_jsonld_hosts` (L1318), `review_pending` (L1329), `rederive` (L1489), `sort_not_target` (L1529), `_takes` (L1589), `after_collect` (L1599).

Local imports: `jobwatch.settings`, `pipeline.agentic.location`.

### [jobwatch/recall.py](../../jobwatch/recall.py)

Symbols: `candidates` (L45), `_line` (L71), `system_prompt` (L76), `triage_batch` (L81), `triage_new` (L108).

### [jobwatch/reports/evaluation.py](../../jobwatch/reports/evaluation.py)

Symbols: `_project` (L77), `_identifier` (L99), `_hash` (L105), `report_payload` (L113), `_json_bytes` (L158), `_markdown` (L162), `_private_folder` (L180), `_matches` (L206), `_publish` (L223), `write_report` (L242).

Local imports: `pipeline.agentic.contracts`.

### [jobwatch/review_cli.py](../../jobwatch/review_cli.py)

Symbols: `register` (L15), `handle` (L27), `_locked` (L55), `_rederive` (L83).

### [jobwatch/settings.py](../../jobwatch/settings.py)

Symbols: `_read` (L12), `load` (L24), `get` (L36).

### [jobwatch/textdates.py](../../jobwatch/textdates.py)

Symbols: `blank_dates` (L16), `only_dates` (L23).

### [jobwatch/user_cli.py](../../jobwatch/user_cli.py)

Symbols: `register` (L20), `handle` (L30), `_names` (L36), `_list` (L42), `_set_password` (L48), `_backup` (L68), `_invite` (L81).

### [jobwatch/users.py](../../jobwatch/users.py)

Symbols: `valid_name` (L23), `current` (L27), `scoped` (L31), `use` (L38), `base_dir` (L49), `user_dir` (L55), `db_path` (L64), `config_dir` (L68), `list_users` (L74), `create_user_dirs` (L82).

Local imports: `pipeline`.

### [jobwatch/web/accounts_routes.py](../../jobwatch/web/accounts_routes.py)

Symbols: `profile_path` (L27), `connected_sites` (L31), `register` (L54).

### [jobwatch/web/actions.py](../../jobwatch/web/actions.py)

Symbols: `ActionError` (L28), `_app_for_posting` (L32), `set_status` (L36), `hide` (L71), `save` (L79), `set_notes` (L89), `_chain` (L106), `draft_job` (L110), `start_draft` (L116), `_file_urls` (L166), `draft_state` (L184), `decide_proposal` (L207), `save_search` (L236), `touch_search` (L245), `delete_search` (L250).

Local imports: `jobwatch.config`, `pipeline.agentic`, `pipeline.schemas`.

### [jobwatch/web/answers_routes.py](../../jobwatch/web/answers_routes.py)

Symbols: `_path` (L20), `parse` (L24), `save` (L49), `register` (L62).

Local imports: `jobwatch.apply`.

### [jobwatch/web/app.py](../../jobwatch/web/app.py)

Symbols: `_page_no` (L53), `create_app` (L61).

Local imports: `jobwatch`, `jobwatch.apply.browser_remote`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.followup_drafts`, `jobwatch.followup_events`, `jobwatch.interview_ad`, `jobwatch.interview_browser`, `jobwatch.interview_inputs`, `jobwatch.interview_prep`, `jobwatch.interview_subjects`, `jobwatch.place`, `jobwatch.preferences`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.service`.

### [jobwatch/web/ask_cards.py](../../jobwatch/web/ask_cards.py)

Symbols: `_region` (L57), `_personal` (L66), `_applies` (L92), `load` (L104), `todo` (L109), `card` (L114), `_backup` (L138), `save_answer` (L153), `notify_missing` (L167).

Local imports: `jobwatch.apply`, `jobwatch.apply.render`, `jobwatch.settings`.

### [jobwatch/web/auth_routes.py](../../jobwatch/web/auth_routes.py)

Symbols: `_secret` (L29), `_users_file` (L35), `_load` (L39), `_hash` (L46), `set_password` (L50), `check_password` (L64), `make_cookie` (L80), `read_cookie` (L86), `install_auth` (L102).

### [jobwatch/web/browser_session.py](../../jobwatch/web/browser_session.py)

Symbols: `BrowserSessionError` (L38), `_public_target` (L42), `_public_url` (L62), `_private_dir` (L66), `BrowserSnapshot` (L77), `_Session` (L86), `BrowserSessionManager` (L553).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.ats`, `jobwatch.apply.prefill`, `jobwatch.apply.submit_confirm`.

### [jobwatch/web/chat_routes.py](../../jobwatch/web/chat_routes.py)

Symbols: `system_prompt` (L32), `_plain` (L42), `_job_lines` (L46), `find_jobs` (L72), `snapshot` (L84), `answer` (L123), `chat_history` (L145), `ask_card` (L176), `ask_answer` (L185), `register` (L202).

Local imports: `jobwatch`, `jobwatch.llm`, `jobwatch.model_choice`, `jobwatch.reader`.

### [jobwatch/web/cli_ext.py](../../jobwatch/web/cli_ext.py)

Symbols: `register` (L13), `handle` (L36), `_design` (L56).

### [jobwatch/web/google_routes.py](../../jobwatch/web/google_routes.py)

Symbols: `register` (L12).

### [jobwatch/web/models_routes.py](../../jobwatch/web/models_routes.py)

Symbols: `list_models` (L15), `register` (L38).

Local imports: `jobwatch`, `jobwatch.llm`.

### [jobwatch/web/onboarding_routes.py](../../jobwatch/web/onboarding_routes.py)

Symbols: `register` (L13).

Local imports: `jobwatch`, `jobwatch.candidate.intake`.

### [jobwatch/web/preference_routes.py](../../jobwatch/web/preference_routes.py)

Symbols: `register` (L12).

Local imports: `jobwatch`, `jobwatch.preferences`, `pipeline.agentic`.

### [jobwatch/web/prepare_routes.py](../../jobwatch/web/prepare_routes.py)

Symbols: `register` (L43).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.browser`, `jobwatch.apply.browser_remote`, `jobwatch.apply.paths`, `jobwatch.apply.prepare`, `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.policy`, `jobwatch.candidate.presentation`, `jobwatch.commands.state`, `jobwatch.outcomes.readiness`, `jobwatch.profile_check`, `jobwatch.web`, `jobwatch.web.browser_session`, `pipeline.agentic.liveness`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [jobwatch/web/queries.py](../../jobwatch/web/queries.py)

Symbols: `_tz` (L23), `_tz_for` (L36), `src_label` (L136), `arm_label` (L140), `flag_label` (L146), `hide_label` (L152), `hide_sentence` (L158), `score_display` (L167), `score_label` (L176), `score_class` (L184), `ai_view_text` (L189), `row_ai_text` (L195), `parse_ts` (L204), `ago` (L214), `absolute` (L230), `days_since` (L237), `plain_text` (L252), `teaser` (L265), `desc_blocks` (L270), `commute_km` (L298), `short_location` (L305), `annual_salary` (L311), `salary_display` (L323), `Registry` (L340), `Filters` (L377), `_terms` (L513), `_like` (L522), `load_rows` (L541), `ui_status` (L579), `enrich` (L591), `_text_list` (L638), `ai_from_row` (L653), `ai_from_pipeline` (L708), `_agentic_hold_reason` (L759), `hold_words` (L772), `_ai_from_agentic` (L778), `_line` (L837), `_num` (L841), `_enum_or` (L845), `_report` (L849), `ai_state` (L895), `rec_key` (L904), `ai_progress` (L911), `fit_score` (L920), `_preds` (L952), `_tab_ok` (L993), `apply_filters` (L1000), `sort_rows` (L1081), `add_teasers` (L1093), `board_visit` (L1112), `mark_viewed` (L1126), `saved_searches` (L1133), `job_detail` (L1154), `_snippet` (L1178), `flag_reasons` (L1191), `_table_exists` (L1223), `_json_object` (L1227), `agentic_models` (L1235), `applications` (L1313), `_event_text` (L1355), `draft_files` (L1375), `proposals` (L1395), `health_rows` (L1416), `employer_rows` (L1436), `nav_counts` (L1459), `insights` (L1475).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.followup_events`, `jobwatch.notify`, `jobwatch.place`, `pipeline.agentic.contracts`, `pipeline.agentic.location`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`.

### [jobwatch/web/static/app/app.css](../../jobwatch/web/static/app/app.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/app/app.js](../../jobwatch/web/static/app/app.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/app/index.html](../../jobwatch/web/static/app/index.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/app/pages.css](../../jobwatch/web/static/app/pages.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/app/sheet.css](../../jobwatch/web/static/app/sheet.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/app/shell.js](../../jobwatch/web/static/app/shell.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/auth.css](../../jobwatch/web/static/auth.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/browser.css](../../jobwatch/web/static/browser.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/browser.js](../../jobwatch/web/static/browser.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/htmx.min.js](../../jobwatch/web/static/htmx.min.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/models.js](../../jobwatch/web/static/models.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/apple.css](../../jobwatch/web/static/pebble/assets/apple.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/chat-restyle.css](../../jobwatch/web/static/pebble/assets/chat-restyle.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/full.css](../../jobwatch/web/static/pebble/assets/full.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/gap-components.css](../../jobwatch/web/static/pebble/assets/gap-components.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/lib/phrog-ui.css](../../jobwatch/web/static/pebble/assets/lib/phrog-ui.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/lib/phrog-ui.js](../../jobwatch/web/static/pebble/assets/lib/phrog-ui.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/pebble.css](../../jobwatch/web/static/pebble/assets/pebble.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/pebble/assets/tokens.css](../../jobwatch/web/static/pebble/assets/tokens.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/pages/chat.js](../../jobwatch/web/static/v3/pages/chat.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/pages/inbox.js](../../jobwatch/web/static/v3/pages/inbox.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/pages/insights.js](../../jobwatch/web/static/v3/pages/insights.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/pages/interview.js](../../jobwatch/web/static/v3/pages/interview.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/pages/sources.js](../../jobwatch/web/static/v3/pages/sources.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/pages/table.js](../../jobwatch/web/static/v3/pages/table.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/shell.js](../../jobwatch/web/static/v3/shell.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/v3.js](../../jobwatch/web/static/v3/v3.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/static/v3/web.css](../../jobwatch/web/static/v3/web.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/_followup_draft_status.html](../../jobwatch/web/templates/_followup_draft_status.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/_interview_prep_status.html](../../jobwatch/web/templates/_interview_prep_status.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/_preparation.html](../../jobwatch/web/templates/_preparation.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/_sprite.html](../../jobwatch/web/templates/_sprite.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/accounts.html](../../jobwatch/web/templates/accounts.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/answers.html](../../jobwatch/web/templates/answers.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/app.html](../../jobwatch/web/templates/app.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/base.html](../../jobwatch/web/templates/base.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/candidate.html](../../jobwatch/web/templates/candidate.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/discovery_status.html](../../jobwatch/web/templates/discovery_status.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/error.html](../../jobwatch/web/templates/error.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/evaluation.html](../../jobwatch/web/templates/evaluation.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/followup_draft.html](../../jobwatch/web/templates/followup_draft.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/interview_prep.html](../../jobwatch/web/templates/interview_prep.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/interview_url.html](../../jobwatch/web/templates/interview_url.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/login.html](../../jobwatch/web/templates/login.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/models.html](../../jobwatch/web/templates/models.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/preferences.html](../../jobwatch/web/templates/preferences.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/prepare.html](../../jobwatch/web/templates/prepare.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/signup.html](../../jobwatch/web/templates/signup.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [jobwatch/web/templates/welcome.html](../../jobwatch/web/templates/welcome.html)

Static asset/configuration/tooling entry; inspect the linked source.

## mcp-app (25 files)

### [mcp-app/guidance/skills.json](../../mcp-app/guidance/skills.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/index.ts](../../mcp-app/index.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/mcp-env.d.ts](../../mcp-app/mcp-env.d.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/package-lock.json](../../mcp-app/package-lock.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/package.json](../../mcp-app/package.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/src/backend.ts](../../mcp-app/src/backend.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/src/docs.ts](../../mcp-app/src/docs.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/src/generated/guidance-bundle.ts](../../mcp-app/src/generated/guidance-bundle.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/src/guidance.ts](../../mcp-app/src/guidance.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/src/registry.ts](../../mcp-app/src/registry.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/src/schemas.ts](../../mcp-app/src/schemas.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/src/tools.ts](../../mcp-app/src/tools.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/test/conformance.test.ts](../../mcp-app/test/conformance.test.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/test/env.sh](../../mcp-app/test/env.sh)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/test/realapp.test.ts](../../mcp-app/test/realapp.test.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/test/server.test.ts](../../mcp-app/test/server.test.ts)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/tsconfig.json](../../mcp-app/tsconfig.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/dashboard/view.tsx](../../mcp-app/views/dashboard/view.tsx)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/review/view.tsx](../../mcp-app/views/review/view.tsx)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/settings/SettingsPanel.tsx](../../mcp-app/views/settings/SettingsPanel.tsx)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/settings/settings.css](../../mcp-app/views/settings/settings.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/shared/dashboard.tsx](../../mcp-app/views/shared/dashboard.tsx)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/shared/panes.tsx](../../mcp-app/views/shared/panes.tsx)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/shared/theme.css](../../mcp-app/views/shared/theme.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [mcp-app/views/shared/ui.tsx](../../mcp-app/views/shared/ui.tsx)

Static asset/configuration/tooling entry; inspect the linked source.

## pipeline (100 files)

### [pipeline/__init__.py](../../pipeline/__init__.py)

Symbols: none at module scope.

### [pipeline/agentic/__init__.py](../../pipeline/agentic/__init__.py)

Symbols: `__getattr__` (L23).

### [pipeline/agentic/acp_agent.py](../../pipeline/agentic/acp_agent.py)

Symbols: `_Session` (L32), `JobwatchACPAgent` (L42), `main` (L195).

Local imports: `jobwatch`, `jobwatch.config`, `pipeline.agentic.chat`, `pipeline.agentic.execution`, `pipeline.agentic.runtime`.

### [pipeline/agentic/api.py](../../pipeline/agentic/api.py)

Symbols: `Principal` (L36), `credentials_from_env` (L41), `_Body` (L65), `Message` (L69), `InteractionResponse` (L73), `create_api` (L78), `main` (L507).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate`, `jobwatch.config`, `jobwatch.execution_mode`, `jobwatch.origin_guard`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`, `pipeline.agentic.client_api`, `pipeline.agentic.evaluation`, `pipeline.agentic.execution`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`, `pipeline.agentic.selection`, `pipeline.agentic.service`.

### [pipeline/agentic/api_store.py](../../pipeline/agentic/api_store.py)

Symbols: `Conflict` (L16), `encoded` (L22), `fingerprint` (L26), `APIStore` (L30).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `pipeline.agentic.private_sqlite`.

### [pipeline/agentic/attachments.py](../../pipeline/agentic/attachments.py)

Symbols: `decode` (L21), `receive` (L64).

Local imports: `jobwatch`, `jobwatch.candidate`.

### [pipeline/agentic/autonomous.py](../../pipeline/agentic/autonomous.py)

Symbols: `skill_files` (L44), `version` (L49), `_token_metrics` (L53), `AssessmentFilesystem` (L71), `StageSkillRead` (L75), `_NoDelegation` (L81), `_NoSummarization` (L87), `CachedEmbeddings` (L93), `NativeModel` (L136), `Slice` (L222), `validate_evaluation` (L254), `evaluate_autonomous` (L291), `evaluate_posting` (L474).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.analysis`, `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.llm`, `jobwatch.prescreen.engine`, `pipeline.agentic`, `pipeline.agentic.chat_storage`, `pipeline.agentic.contracts`, `pipeline.agentic.deepagents_runtime`, `pipeline.agentic.evaluator`, `pipeline.agentic.gateway`, `pipeline.agentic.matching`, `pipeline.agentic.private_sqlite`, `pipeline.agentic.runtime`.

### [pipeline/agentic/baseline.py](../../pipeline/agentic/baseline.py)

Symbols: `FrozenCase` (L51), `Baseline` (L73), `_source_path` (L104), `gate_sources` (L118), `current_gate_version` (L134), `_field` (L147), `group_keys_for` (L155), `group_ids` (L167), `_statuses` (L201), `tag_case` (L206), `_utcnow` (L253), `_git_commit` (L257), `_canonical` (L271), `_sha` (L276), `_corrupt` (L280), `_baselines_root` (L286), `_baseline_dir` (L290), `_read_verified` (L302), `_read_record` (L315), `_read_blob` (L329), `_inflate` (L340), `load_baseline` (L361), `list_baselines` (L378), `_verify_profile` (L392), `pinned_profile` (L404), `frozen_approved` (L414), `frozen_decision_policy` (L427), `_active_decision_policy` (L444), `decide_frozen` (L456), `_check_arguments` (L489), `_has_table` (L497), `_first` (L501), `_select_runs` (L509), `_copy_profile` (L538), `_load_artifact` (L557), `_snapshot_ad_hash` (L570), `_stored` (L586), `_charged_tokens` (L595), `_latency_seconds` (L604), `_write_blob` (L619), `_prepare_case` (L628), `_evidence_hash` (L680), `_freeze_into` (L687), `freeze_baseline` (L765), `OwnerLabel` (L811), `_labels_invalid` (L829), `_parse_labels` (L833), `_read_labels_file` (L851), `read_labels` (L860), `latest_labels` (L865), `_labels_locked` (L874), `write_label` (L884), `label_case` (L899), `effective_tags` (L922).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.paths`, `jobwatch.candidate`, `jobwatch.candidate._private_io`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.policy`, `jobwatch.dedupe`.

### [pipeline/agentic/browser_api.py](../../pipeline/agentic/browser_api.py)

Symbols: `ReviewBody` (L24), `OpenBody` (L29), `WebsiteOperation` (L36), `BrowserAnswers` (L45), `mount` (L51).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.browser`, `jobwatch.apply.prepare`, `jobwatch.web.accounts_routes`, `jobwatch.web.browser_session`, `pipeline.agentic.chat`.

### [pipeline/agentic/cards.py](../../pipeline/agentic/cards.py)

Symbols: `resolve` (L9).

### [pipeline/agentic/chat.py](../../pipeline/agentic/chat.py)

Symbols: `_career_ops_skill` (L101), `skill_files` (L106), `skill_version` (L112), `job_database` (L116), `job_connection` (L123), `_tool_arguments` (L139), `_identity` (L151), `_human_text` (L158), `_approval_binding` (L169), `ConversationModel` (L247), `_route` (L297), `_PrivateBoundary` (L301), `_build` (L335), `_chat_interactions` (L894), `dispatch` (L923).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.paths`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.policy`, `jobwatch.config`, `jobwatch.execution_mode`, `jobwatch.followup_drafts`, `jobwatch.interview_prep`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.chat_storage`, `pipeline.agentic.company_research`, `pipeline.agentic.contracts`, `pipeline.agentic.deepagents_runtime`, `pipeline.agentic.gateway`, `pipeline.agentic.genui`, `pipeline.agentic.mcp_client`, `pipeline.agentic.model_insights`, `pipeline.agentic.persistence`, `pipeline.agentic.private_sqlite`, `pipeline.agentic.research`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [pipeline/agentic/chat_storage.py](../../pipeline/agentic/chat_storage.py)

Symbols: `ChatSaver` (L17), `ChatStore` (L95).

### [pipeline/agentic/chatgpt_connector.py](../../pipeline/agentic/chatgpt_connector.py)

Symbols: `counts_text` (L48), `_http_url` (L53), `_list` (L58), `_person_config` (L66), `application_overview` (L72), `overview` (L89), `recommended_detail` (L116), `prepare_selected` (L129), `_assessment_projection` (L144), `detail` (L212), `_forget_expired` (L253), `_hand_off` (L259), `_outcome` (L269), `decide` (L306), `_chat_digest` (L325), `with_confirm_digest` (L332), `approve_in_chat` (L340), `_application_and_digest` (L367), `submit_digest` (L381), `submit_reviewed` (L387), `status` (L421), `_answer_text` (L432), `_NativeLiveForm` (L444), `_live_form` (L464), `_doc_rows` (L469), `_live_answers` (L478), `review` (L494), `_review` (L504), `_overview_text` (L556), `_detail_text` (L564), `register` (L576).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.paths`, `jobwatch.config`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.contracts`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`.

### [pipeline/agentic/cli.py](../../pipeline/agentic/cli.py)

Symbols: `main` (L15).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.config`, `pipeline.agentic.contracts`, `pipeline.agentic.service`.

### [pipeline/agentic/client_api.py](../../pipeline/agentic/client_api.py)

Symbols: `configured_models` (L35), `model_catalog` (L48), `_db` (L83), `_ticket` (L98), `ticket` (L109), `upload_ticket` (L124), `receive_upload` (L131), `UploadRequest` (L164), `ModelRequest` (L172), `BrowserControlRequest` (L177), `mount` (L182).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate`, `pipeline.agentic.api_store`, `pipeline.agentic.execution`, `pipeline.agentic.persistence`, `pipeline.agentic.private_sqlite`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [pipeline/agentic/company_research.py](../../pipeline/agentic/company_research.py)

Symbols: `company_brief` (L16), `_CitedAdItem` (L65), `_CompanyFact` (L72), `CompanyBrief` (L79), `run_company_researcher` (L101).

Local imports: `pipeline.agentic.contracts`, `pipeline.agentic.execution`, `pipeline.agentic.research`, `pipeline.agentic.runtime`.

### [pipeline/agentic/connector_http.py](../../pipeline/agentic/connector_http.py)

Symbols: `Prepare` (L30), `Revise` (L45), `Decide` (L49), `Approve` (L55), `OnboardingBody` (L64), `OnboardingStart` (L68), `OnboardingProposal` (L73), `AddFact` (L77), `SetFact` (L83), `RemoveFact` (L90), `OnboardingUpdate` (L95), `OnboardingAnswer` (L100), `OnboardingConfirm` (L106), `DiscoveryStart` (L119), `DiscoveryRetry` (L123), `Submit` (L129), `Verify` (L134), `_oauth_state_path` (L139), `_public_origin` (L147), `create_app` (L157), `_mount_oauth` (L333), `main` (L398).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.config`, `jobwatch.preferences`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.discovery_settings`, `pipeline.agentic.mcp_oauth`, `pipeline.agentic.profile_api`, `pipeline.agentic.runtime`, `pipeline.agentic.selection`.

### [pipeline/agentic/connector_onboarding.py](../../pipeline/agentic/connector_onboarding.py)

Symbols: `_status` (L14), `status` (L22), `start` (L27), `update` (L35), `answer` (L40), `review` (L46), `confirm` (L56).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.config`, `pipeline.agentic`.

### [pipeline/agentic/contracts.py](../../pipeline/agentic/contracts.py)

Symbols: `PublicAgenticError` (L29), `_safe_raise` (L40), `_finite_json` (L45), `StrictFrozen` (L56), `SourceCitation` (L60), `validate_citations` (L73), `AgenticScreeningAnswer` (L104), `answers_content_hash` (L130), `Requirement` (L144), `RequirementSet` (L166), `check_frozen_requirements` (L189), `RunKey` (L206), `AgenticGateDecision` (L231), `EvidenceJudgment` (L246), `RequirementMatch` (L265), `Dimension` (L293), `AgenticEvaluation` (L309), `DraftProposal` (L388), `ReviewVerdict` (L419), `validate_review` (L455), `PackageManifest` (L474), `Reservation` (L511), `parse_budget_checkpoint_json` (L532), `BudgetCheckpoint` (L556).

Local imports: `jobwatch.candidate.contracts`, `pipeline.schemas`.

### [pipeline/agentic/controls.css](../../pipeline/agentic/controls.css)

Static asset/configuration/tooling entry; inspect the linked source.

### [pipeline/agentic/controls.html](../../pipeline/agentic/controls.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [pipeline/agentic/controls.js](../../pipeline/agentic/controls.js)

Static asset/configuration/tooling entry; inspect the linked source.

### [pipeline/agentic/data/metro-localities.json](../../pipeline/agentic/data/metro-localities.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [pipeline/agentic/data/vic-geo.json](../../pipeline/agentic/data/vic-geo.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [pipeline/agentic/decision_log.py](../../pipeline/agentic/decision_log.py)

Symbols: `ensure` (L12), `record` (L19), `latest` (L27).

### [pipeline/agentic/deepagents_runtime.py](../../pipeline/agentic/deepagents_runtime.py)

Symbols: `_NoFilesystem` (L47), `_Execution` (L56), `_log_failure` (L92), `GatewayChatModel` (L116), `_RegistryBoundary` (L242), `_tool_for_graph` (L270), `_invoke` (L302), `run_deepagents_role` (L327).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.gateway`, `pipeline.agentic.runtime`.

### [pipeline/agentic/discovery.py](../../pipeline/agentic/discovery.py)

Symbols: `settings` (L32), `_fields` (L53), `field_hypotheses` (L58), `refresh` (L62), `_current_plan` (L77), `prepare_run` (L84), `recall_filter` (L109), `RelevanceJudgment` (L114), `RelevanceExtraction` (L126), `ad_passages` (L133), `ScreenContext` (L143), `judge_relevance` (L154), `exclusion_rule_hit` (L197), `enforce_exclusions` (L203), `_has_table` (L230), `latest_judgment_row` (L234), `latest_judgment` (L244), `context_for` (L250), `_store_judgment` (L275), `screen_step` (L282), `restore_archived` (L333), `ensure_ad_vectors` (L348), `same_vacancy_structured` (L370), `semantic_duplicates` (L383), `order_pending` (L422), `reconsider` (L432), `main` (L462).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `jobwatch.config`, `jobwatch.dedupe`, `jobwatch.execution_mode`, `jobwatch.occupations`, `jobwatch.occupations.embeddings`, `jobwatch.occupations.hypotheses`, `jobwatch.occupations.loaders`, `jobwatch.occupations.plan`, `jobwatch.prescreen`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.evaluator`, `pipeline.agentic.runtime`, `pipeline.schemas`, `pipeline.store`.

### [pipeline/agentic/discovery_api.py](../../pipeline/agentic/discovery_api.py)

Symbols: `DiscoveryRequest` (L17), `RetryRequest` (L22), `flags` (L28), `mount` (L33).

Local imports: `jobwatch`, `jobwatch.occupations.hypotheses`, `jobwatch.occupations.plan`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.discovery_settings`.

### [pipeline/agentic/discovery_ops.py](../../pipeline/agentic/discovery_ops.py)

Symbols: `_context` (L17), `status` (L28), `get_settings` (L58), `set_settings` (L63), `start` (L68), `execute` (L94).

Local imports: `jobwatch`, `jobwatch.candidate`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`.

### [pipeline/agentic/discovery_settings.py](../../pipeline/agentic/discovery_settings.py)

Symbols: `DailySettings` (L19), `_path` (L29), `_override` (L35), `job_defaults` (L49), `job_limits` (L55), `get_settings` (L68), `_daily` (L76), `set_settings` (L91), `allowance` (L110), `allowance_reason` (L120).

Local imports: `jobwatch`, `jobwatch.candidate`, `pipeline.agentic.service`.

### [pipeline/agentic/draft.py](../../pipeline/agentic/draft.py)

Symbols: `DraftArtifacts` (L36), `_Strict` (L49), `_Claim` (L53), `_Experience` (L62), `_Education` (L69), `_CV` (L74), `_Letter` (L83), `_Gap` (L87), `_Content` (L92), `_ProposalArgs` (L98), `_EvidenceRead` (L107), `_SourceRead` (L111), `_NoArgs` (L115), `_CheckClaims` (L119), `_submit_proposal` (L123), `_research_tools` (L128), `_trim_cv` (L151), `_role` (L165), `profile_from_snapshot` (L234), `_evaluation_hash` (L251), `_claim_report` (L255), `_proposal` (L266), `_inventory` (L295), `_save_pdf_failure` (L306), `_save_rejection` (L321), `draft_and_review` (L339), `drop_claims` (L508).

Local imports: `jobwatch.apply.careerops_cv`, `jobwatch.apply.evidence`, `jobwatch.apply.paths`, `jobwatch.apply.render`, `jobwatch.apply.review`, `jobwatch.apply.verify`, `jobwatch.apply.verify_pdf`, `jobwatch.candidate.evidence`, `jobwatch.model_choice`, `jobwatch.settings`, `pipeline.agentic`, `pipeline.agentic.company_research`, `pipeline.agentic.contracts`, `pipeline.agentic.evaluator`, `pipeline.agentic.forms`, `pipeline.agentic.letter_rules`, `pipeline.agentic.research`, `pipeline.agentic.review`, `pipeline.agentic.runtime`, `pipeline.agentic.writing_guide`.

### [pipeline/agentic/eval_data.py](../../pipeline/agentic/eval_data.py)

Symbols: `code_hash` (L28), `private_dir` (L38), `locked` (L49), `write_once` (L59), `capture_case_context` (L70), `capture_inputs` (L80), `freeze_cases` (L110), `record_for` (L126), `load_inputs` (L137), `_case` (L153), `_seal` (L167), `_validate_seal` (L171), `create_split` (L176), `_check_split` (L212), `load_split` (L233), `audit_holdout` (L246), `partition_ids` (L265), `load_partition` (L274).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.preferences`, `pipeline.agentic`, `pipeline.agentic.contracts`.

### [pipeline/agentic/eval_fit.py](../../pipeline/agentic/eval_fit.py)

Symbols: `FrozenChoices` (L15), `eligible_choices` (L35), `fit_development` (L78).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `jobwatch.preferences.features`, `jobwatch.preferences.model`, `jobwatch.preferences.store`, `pipeline.agentic`.

### [pipeline/agentic/eval_metrics.py](../../pipeline/agentic/eval_metrics.py)

Symbols: `_label_value` (L17), `_owner_label` (L21), `_valid_relevance` (L25), `_ranked` (L29), `_missing` (L34), `_suitable` (L38), `_ordering` (L48), `_number` (L83), `_count` (L87), `_usage` (L91), `_diagnostics` (L107), `compute_metrics` (L133).

### [pipeline/agentic/evaluate_runs.py](../../pipeline/agentic/evaluate_runs.py)

Symbols: `_usage` (L25), `_bundle` (L30), `_citation_failures` (L34), `replay_case` (L59), `_paid_evaluation` (L101), `replay` (L131), `load_result` (L242).

Local imports: `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.policy`, `jobwatch.llm`, `jobwatch.model_choice`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.discovery`, `pipeline.agentic.eval_fit`, `pipeline.agentic.eval_metrics`, `pipeline.agentic.evaluator`, `pipeline.agentic.execution`, `pipeline.agentic.runtime`, `pipeline.agentic.shortlist`.

### [pipeline/agentic/evaluation.py](../../pipeline/agentic/evaluation.py)

Symbols: `MatchingPrediction` (L12), `MatchingReview` (L20), `MatchingCase` (L26), `_matching_cases` (L34), `blind_matching_packet` (L63), `compare_matching_runs` (L95), `evaluate_tools` (L136).

Local imports: `pipeline.agentic.contracts`, `pipeline.agentic.runtime`.

### [pipeline/agentic/evaluator.py](../../pipeline/agentic/evaluator.py)

Symbols: `ExtractedJobFacts` (L28), `JDExtraction` (L37), `_exact_ad_citation` (L47), `_find_in_ad` (L68), `_loose_find` (L84), `JobSummary` (L97), `RequirementAssessments` (L115), `JobAssessment` (L130), `ResearchQuery` (L134), `ResearchFetch` (L138), `_snapshot_analysis` (L142), `evaluate_job` (L165).

Local imports: `jobwatch.candidate.analysis`, `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.gateway`, `pipeline.agentic.matching`, `pipeline.agentic.research`, `pipeline.agentic.runtime`, `pipeline.schemas`.

### [pipeline/agentic/execution.py](../../pipeline/agentic/execution.py)

Symbols: `embedding_model_allowed` (L23), `require_route` (L29), `Execution` (L46), `current` (L111), `use` (L116).

Local imports: `jobwatch`, `pipeline.agentic.runtime`.

### [pipeline/agentic/feedback.py](../../pipeline/agentic/feedback.py)

Symbols: `Reason` (L18), `FeedbackError` (L51), `_text` (L61), `_positive_id` (L69), `_common` (L76), `_reason` (L92), `_json_value` (L103), `_event` (L122), `_prior` (L130), `_retry` (L136), `append_event` (L143), `_latest_dismissal` (L193), `record_feedback` (L201), `_has_events` (L264), `_dismissals` (L268), `rejected_posting_ids` (L279), `dismissal_state_hash` (L283), `list_events` (L288).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `pipeline.agentic`.

### [pipeline/agentic/feedback_api.py](../../pipeline/agentic/feedback_api.py)

Symbols: `Body` (L15), `Rejection` (L19), `Restoration` (L25), `RuleProposal` (L29), `RuleConfirmation` (L36), `Comparison` (L40), `Answer` (L44), `Selected` (L48), `rebuild` (L54), `confirm_rule` (L59), `mount` (L74).

Local imports: `jobwatch`, `jobwatch.candidate`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`.

### [pipeline/agentic/feedback_chat.py](../../pipeline/agentic/feedback_chat.py)

Symbols: `_selection_args` (L20), `preview` (L30), `apply` (L70), `tools` (L95).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.feedback_api`, `pipeline.agentic.runtime`.

### [pipeline/agentic/feedback_prompts.py](../../pipeline/agentic/feedback_prompts.py)

Symbols: `PromptError` (L33), `_now` (L41), `_time` (L45), `_settings` (L52), `_pool` (L64), `_preference_store` (L68), `_entries` (L72), `_snapshot` (L76), `_entropy` (L99), `_choices` (L103), `posterior_choices` (L122), `information_gain` (L128), `cold_start_triple` (L141), `_has_prompts` (L166), `_rows` (L170), `_get` (L187), `_body` (L196), `_render` (L200), `outstanding_prompt` (L209), `list_prompts` (L214), `prompts_this_week` (L220), `_transaction` (L229), `_questions` (L241), `_is_current` (L266), `_close` (L277), `_stale` (L282), `_finish_set` (L287), `next_prompt` (L307), `_validate_write` (L401), `_request` (L409), `_prior_response` (L414), `_reserve` (L433), `_existing_pick` (L455), `_finalize` (L473), `answer_comparison` (L500), `answer_question` (L532), `dismiss_prompt` (L550).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `jobwatch.preferences`, `jobwatch.preferences.features`, `jobwatch.preferences.model`, `pipeline.agentic`.

### [pipeline/agentic/followup.py](../../pipeline/agentic/followup.py)

Symbols: `FollowupClaim` (L26), `FollowupProposal` (L32), `FollowupReview` (L42), `FollowupDraft` (L49), `ReadSource` (L59), `source_map` (L63), `snapshot_hash` (L73), `validate_proposal` (L78), `compose_followup` (L101).

Local imports: `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.runtime`.

### [pipeline/agentic/forms.py](../../pipeline/agentic/forms.py)

Symbols: `validate_screening_answers` (L9), `build_form_map` (L40).

Local imports: `jobwatch.candidate.evidence`, `pipeline.agentic.contracts`, `pipeline.schemas`.

### [pipeline/agentic/gate.py](../../pipeline/agentic/gate.py)

Symbols: `_hold` (L14), `_archive` (L21), `_draft` (L26), `_verified` (L31), `_logistics` (L43), `decide` (L64).

Local imports: `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.eligibility`, `jobwatch.candidate.evidence`, `jobwatch.candidate.policy`, `pipeline.agentic.contracts`.

### [pipeline/agentic/gateway.py](../../pipeline/agentic/gateway.py)

Symbols: `PaidGatewayEmbeddings` (L19), `messages_for_gateway` (L82), `call` (L105).

Local imports: `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.runtime`.

### [pipeline/agentic/genui.py](../../pipeline/agentic/genui.py)

Symbols: `enabled` (L79), `guidance` (L83).

### [pipeline/agentic/identity.py](../../pipeline/agentic/identity.py)

Symbols: `registry` (L20), `credentials` (L33), `Enrollment` (L48), `mount` (L53).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `pipeline.agentic.api`, `pipeline.agentic.private_sqlite`.

### [pipeline/agentic/incidents.py](../../pipeline/agentic/incidents.py)

Symbols: `_exists` (L39), `ensure` (L43), `_dict` (L68), `_get` (L80), `list_incidents` (L85), `is_paused` (L93), `_message` (L100), `report` (L106), `release` (L148), `_digest` (L166), `flush_notifications` (L184), `begin_run` (L235), `mark_phase` (L244), `end_run` (L255), `reconcile_service_exit` (L264), `reconcile_known_failures` (L281).

Local imports: `jobwatch`, `jobwatch.notifier`.

### [pipeline/agentic/interview.py](../../pipeline/agentic/interview.py)

Symbols: `InterviewSource` (L41), `ResultFirstAnswer` (L56), `InterviewItem` (L63), `InterviewSection` (L85), `InterviewProposal` (L91), `ReviewCriterion` (L119), `InterviewReview` (L124), `InterviewReport` (L132), `ReadSource` (L150), `SearchPublic` (L154), `FetchPublic` (L158), `_text` (L162), `source_map` (L166), `snapshot_hash` (L186), `validate_review` (L190), `validate_proposal` (L196), `prepare_interview` (L280), `validate_report` (L371).

Local imports: `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.research`, `pipeline.agentic.runtime`.

### [pipeline/agentic/jev_skills.py](../../pipeline/agentic/jev_skills.py)

Symbols: `safe_facts` (L34), `labelled` (L48), `_facts_block` (L71), `fit_scores` (L82), `unsupported_claims` (L98), `requirement_map` (L125), `save` (L176), `latest` (L185).

Local imports: `jobwatch.candidate.person`, `jobwatch.openrouter_extras`.

### [pipeline/agentic/jobwatch-app.html](../../pipeline/agentic/jobwatch-app.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [pipeline/agentic/langgraph_entry.py](../../pipeline/agentic/langgraph_entry.py)

Symbols: `_FakeModel` (L23), `make_graph` (L42).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.config`, `pipeline.agentic`, `pipeline.agentic.chat_storage`, `pipeline.agentic.private_sqlite`, `pipeline.agentic.service`.

### [pipeline/agentic/letter_rules.py](../../pipeline/agentic/letter_rules.py)

Symbols: `letter_text` (L19), `third_opinion` (L24).

### [pipeline/agentic/librechat.py](../../pipeline/agentic/librechat.py)

Symbols: `ChatMessage` (L24), `Completion` (L31), `_view_tool` (L38), `_continuation` (L44), `_current_run` (L71), `_message` (L84), `_uploads` (L102), `_enqueue` (L117), `_answer` (L164), `mount` (L193).

Local imports: `jobwatch`, `jobwatch.candidate`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`, `pipeline.agentic.client_api`, `pipeline.agentic.genui`, `pipeline.agentic.profile_conversation`.

### [pipeline/agentic/liveness.py](../../pipeline/agentic/liveness.py)

Symbols: `PostingObservation` (L27), `_strip_page_chrome` (L57), `observe_posting` (L70), `latest_observation` (L127), `observation_current` (L138), `observation_metadata` (L151).

Local imports: `jobwatch.candidate.contracts`, `jobwatch.interview_ad`, `jobwatch.interview_browser`, `jobwatch.models`, `pipeline.agentic.contracts`.

### [pipeline/agentic/location.py](../../pipeline/agentic/location.py)

Symbols: `_state` (L31), `_names_state` (L39), `_own_state_cited` (L44), `cited_melbourne_location` (L57), `victorian_place` (L124), `cited_victoria_location` (L139), `_km` (L151), `_home_for` (L159), `_profile_home` (L163), `home_place` (L175), `km_from_home` (L189), `regions_named` (L213), `location_verdict` (L228), `_names_other_state` (L246), `commute_km_for` (L261).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.place`.

### [pipeline/agentic/matching.py](../../pipeline/agentic/matching.py)

Symbols: `_terms` (L23), `EvidenceSearch` (L27), `EvidenceSearchBatch` (L34), `RequirementEvidenceSearch` (L38).

Local imports: `jobwatch.candidate.assessment`, `pipeline.agentic.contracts`.

### [pipeline/agentic/mcp_app.py](../../pipeline/agentic/mcp_app.py)

Symbols: `Verifier` (L32), `create_server` (L47), `main` (L247).

Local imports: `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.cards`, `pipeline.agentic.runtime`.

### [pipeline/agentic/mcp_client.py](../../pipeline/agentic/mcp_client.py)

Symbols: `MCPToolset` (L45), `_timeout` (L56), `_servers` (L62), `_allowed` (L73), `_transport` (L82), `_client` (L126), `_list_tools` (L135), `_call_tool` (L143), `_wrap` (L160), `load_mcp_tools` (L186).

### [pipeline/agentic/mcp_oauth.py](../../pipeline/agentic/mcp_oauth.py)

Symbols: `_h` (L39), `JobwatchOAuth` (L43).

### [pipeline/agentic/mcp_server.py](../../pipeline/agentic/mcp_server.py)

Symbols: `_JobwatchTokenVerifier` (L30), `_person_from_request` (L44), `_input_request` (L52), `_resume_decisions` (L93), `_state` (L115), `_requests` (L131), `_turn` (L146), `create_server` (L194), `main` (L249).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.mcp_oauth`, `pipeline.agentic.runtime`.

### [pipeline/agentic/model_insights.py](../../pipeline/agentic/model_insights.py)

Symbols: `candidate_paths` (L10), `preference_insights` (L19), `callback_insights` (L52), `pipeline_insights` (L62).

Local imports: `jobwatch.candidate.analysis`, `jobwatch.outcomes.callback`, `jobwatch.preference_service`, `jobwatch.preferences`, `jobwatch.preferences.features`, `pipeline.agentic`.

### [pipeline/agentic/persistence.py](../../pipeline/agentic/persistence.py)

Symbols: `_now` (L26), `_json` (L30), `_sha` (L34), `_read_artifact` (L38), `latest_result` (L55), `PersistenceAdapter` (L112).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.contracts`, `jobwatch.models`, `pipeline`, `pipeline.agentic.contracts`, `pipeline.agentic.liveness`, `pipeline.agentic.runtime`, `pipeline.agentic.service`, `pipeline.agentic.store`, `pipeline.schemas`.

### [pipeline/agentic/private_sqlite.py](../../pipeline/agentic/private_sqlite.py)

Symbols: `connect` (L15).

### [pipeline/agentic/profile_api.py](../../pipeline/agentic/profile_api.py)

Symbols: `_Body` (L27), `ProposalRequest` (L31), `UploadsRequest` (L36), `EditRequest` (L40), `AnswerRequest` (L45), `ConfirmRequest` (L51), `mount` (L56).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.intake`, `pipeline.agentic`.

### [pipeline/agentic/profile_conversation.py](../../pipeline/agentic/profile_conversation.py)

Symbols: `tables` (L15), `pending` (L22), `prompt` (L26), `remember` (L56), `respond` (L65), `_remember_response` (L115).

Local imports: `jobwatch`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`, `pipeline.agentic.contracts`.

### [pipeline/agentic/ranking.py](../../pipeline/agentic/ranking.py)

Symbols: `Coverage` (L28), `_status` (L47), `_rows` (L54), `_mandatory` (L60), `coverage` (L64), `candidate_status` (L97), `_relevance` (L101), `label_for` (L105), `exclusion_reason` (L115), `Scored` (L125), `Ranked` (L137), `_finite` (L146), `_posting_order` (L150), `rank_candidates` (L158), `ShortlistEntry` (L188), `_unique` (L213), `_fact_text` (L217), `_fact_supported` (L225), `explain` (L241).

Local imports: `jobwatch.candidate.projection`, `jobwatch.place`, `pipeline.agentic.contracts`, `pipeline.agentic.location`.

### [pipeline/agentic/research.py](../../pipeline/agentic/research.py)

Symbols: `ResearchUnavailable` (L20), `PublicHTTPStatus` (L25), `ResearchIntent` (L33), `PublicSnapshot` (L43), `ResearchResult` (L57), `ResearchPage` (L64), `LocalSearxSearch` (L69), `PublicDocument` (L128), `_pinned_https_fetch` (L133), `_readable_public_text` (L194), `SafeFetcher` (L227), `ResearchCapability` (L286).

### [pipeline/agentic/review.py](../../pipeline/agentic/review.py)

Symbols: `_ReviewArgs` (L21), `_ReadEvidence` (L28), `_ReadSources` (L33), `_claim_evidence_ids` (L38), `_accept_review` (L50), `capture_private_failures` (L54), `write_private` (L59), `_log_review_failure` (L69), `review_proposal` (L83).

Local imports: `jobwatch.apply.paths`, `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.runtime`.

### [pipeline/agentic/revisions.py](../../pipeline/agentic/revisions.py)

Symbols: `_path` (L11), `current` (L17), `record` (L27), `fingerprint` (L35).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `pipeline.agentic.runtime`.

### [pipeline/agentic/runtime.py](../../pipeline/agentic/runtime.py)

Symbols: `RuntimeErrorSafe` (L31), `Tool` (L36), `RoleSpec` (L49), `RoleResult` (L69), `_BatchState` (L76), `BatchBudget` (L88), `JobBudget` (L123), `_json_tuples` (L314), `validate_model_payload` (L350), `_json_bytes` (L370), `run_role` (L378), `_usage_total` (L386).

Local imports: `pipeline.agentic.contracts`, `pipeline.agentic.deepagents_runtime`, `pipeline.agentic.execution`.

### [pipeline/agentic/selection.py](../../pipeline/agentic/selection.py)

Symbols: `SelectionError` (L16), `_now` (L22), `status` (L26), `preview` (L39), `_preparation_hash` (L68), `request` (L82), `_manifest` (L116), `_mark_queued` (L132), `dispatch_pending` (L137), `cancel` (L173), `execute` (L192), `finish_error` (L242), `reconcile` (L252).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`, `pipeline.agentic.persistence`.

### [pipeline/agentic/service.py](../../pipeline/agentic/service.py)

Symbols: `_runtime_stop_reason` (L55), `_defer_budget_tail` (L65), `settings` (L75), `agentic_settings` (L79), `enabled` (L87), `_config` (L92), `_run_timing` (L133), `decision_policy_mode` (L153), `decision_policy_for` (L162), `commute_km_of` (L168), `gate_current` (L177), `applicable_knockouts` (L192), `_draft_limits` (L197), `_research` (L207), `configured_llm` (L218), `_posting` (L229), `_capture` (L235), `_prescreen_fingerprint` (L244), `_run_key` (L259), `snapshot_inventory` (L281), `_make_batch` (L321), `_budget` (L335), `_restore_package` (L416), `_package_payload` (L427), `_reusable_candidate` (L435), `run_agentic_job` (L451), `agentic_batch_run` (L787), `_tell_owner_ready` (L904), `_alert_if_error` (L916), `_now` (L929), `_spent_today` (L933), `_local_midnight` (L948), `_evaluation_current` (L954), `_without_completed` (L966), `_refresh_shortlist` (L991), `after_collect` (L1003), `_repeat_backoff` (L1166), `_unreadable_backoff` (L1177), `_invalid_backoff` (L1184), `_target_first` (L1190), `_near_duplicates` (L1210), `bundle_name` (L1261).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate`, `jobwatch.candidate.analysis`, `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.inputs`, `jobwatch.candidate.policy`, `jobwatch.execution_mode`, `jobwatch.llm`, `jobwatch.model_choice`, `jobwatch.notify`, `jobwatch.occupations.embeddings`, `jobwatch.openrouter_extras`, `jobwatch.place`, `jobwatch.prescreen.engine`, `jobwatch.settings`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.autonomous`, `pipeline.agentic.company_research`, `pipeline.agentic.contracts`, `pipeline.agentic.discovery_settings`, `pipeline.agentic.draft`, `pipeline.agentic.evaluator`, `pipeline.agentic.execution`, `pipeline.agentic.forms`, `pipeline.agentic.gate`, `pipeline.agentic.liveness`, `pipeline.agentic.location`, `pipeline.agentic.model_insights`, `pipeline.agentic.persistence`, `pipeline.agentic.research`, `pipeline.agentic.revisions`, `pipeline.agentic.runtime`, `pipeline.agentic.store`, `pipeline.nodes`, `pipeline.schemas`.

### [pipeline/agentic/shortlist.py](../../pipeline/agentic/shortlist.py)

Symbols: `_tables` (L25), `_fields` (L29), `_focus_hypotheses` (L34), `_pin` (L41), `_latest` (L95), `_empty` (L103), `_current_relevance` (L108), `_preference_utilities` (L115), `build_shortlist` (L144), `load_latest` (L253), `latest_entries` (L277), `load_entry` (L281), `record_impressions` (L285).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate._private_io`, `jobwatch.candidate.analysis`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `jobwatch.occupations.hypotheses`, `jobwatch.outcomes.readiness`, `jobwatch.preferences`, `jobwatch.preferences.features`, `jobwatch.preferences.model`, `pipeline.agentic`, `pipeline.agentic.baseline`, `pipeline.agentic.matching`, `pipeline.agentic.persistence`.

### [pipeline/agentic/shortlist_api.py](../../pipeline/agentic/shortlist_api.py)

Symbols: `mount` (L15).

Local imports: `jobwatch`, `jobwatch.preferences`, `pipeline.agentic`, `pipeline.agentic.chat`.

### [pipeline/agentic/store.py](../../pipeline/agentic/store.py)

Symbols: `Claim` (L15), `_fail` (L26), `_parse_wire` (L30), `_json` (L43), `_digest` (L47), `_canonical` (L51), `_checkpoint_equal` (L55), `AgenticStore` (L63).

### [pipeline/agentic/task_state.py](../../pipeline/agentic/task_state.py)

Symbols: `_selections` (L22), `task_card` (L30), `_epoch` (L53), `_has` (L62), `jobs_overview` (L66), `overview_counts` (L92), `retry_blocked` (L100), `stop` (L107).

Local imports: `jobwatch`, `jobwatch.apply`, `pipeline.agentic`.

### [pipeline/agentic/tui.py](../../pipeline/agentic/tui.py)

Symbols: `_session_path` (L62), `_read_session` (L68), `_write_session` (L75), `PromptInput` (L82), `JobwatchTUI` (L89), `usage_note` (L802), `theme_unknown` (L815), `main` (L825).

Local imports: `jobwatch`, `jobwatch.config`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.execution`, `pipeline.agentic.runtime`, `pipeline.agentic.task_state`, `pipeline.agentic.tui_data`, `pipeline.agentic.tui_home`.

### [pipeline/agentic/tui_data.py](../../pipeline/agentic/tui_data.py)

Symbols: `Backend` (L17), `check_attachment` (L43), `_extensions` (L58), `WebBackend` (L66).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.config`, `jobwatch.web`, `jobwatch.web.auth_routes`, `jobwatch.web.models_routes`, `pipeline.agentic`, `pipeline.agentic.chat`.

### [pipeline/agentic/tui_files.py](../../pipeline/agentic/tui_files.py)

Symbols: `size_text` (L25), `kind_for` (L29), `fuzzy_score` (L38), `scan` (L53), `listing` (L67), `FilePicker` (L76), `open_picker` (L229), `chips_text` (L237).

### [pipeline/agentic/tui_home.py](../../pipeline/agentic/tui_home.py)

Symbols: `logo_lines` (L38), `version` (L55), `menu_lines` (L63), `side_lines` (L86), `HomePrompt` (L107), `HomeScreen` (L114).

### [pipeline/agentic/tui_screens.py](../../pipeline/agentic/tui_screens.py)

Symbols: `app_state` (L31), `row_state` (L36), `score_cell` (L41), `pid_of` (L47), `open_view` (L51), `ViewScreen` (L69), `big_buttons` (L239), `needs_you` (L252), `TodayScreen` (L275), `JobsScreen` (L354), `empty_feed` (L387), `DetailScreen` (L396), `outcome_unknown_lines` (L491), `ReviewScreen` (L500), `ApplicationsScreen` (L598), `InboxScreen` (L687), `TableScreen` (L749), `SourcesScreen` (L846), `InsightsScreen` (L926), `dayname` (L1000), `day_chart` (L1007), `top_n` (L1026), `ModelsScreen` (L1031).

### [pipeline/agentic/tui_theme.py](../../pipeline/agentic/tui_theme.py)

Symbols: `clean` (L22), `esc` (L27), `plain` (L31), `join` (L35), `styled` (L46), `badge` (L52), `fit` (L57), `score_text` (L62), `two_col` (L66).

### [pipeline/agentic/tui_views.py](../../pipeline/agentic/tui_views.py)

Symbols: `counts_lines` (L17), `feed_rows` (L29), `sidebar` (L46), `narrow_header` (L61), `narrow_feed` (L71), `approval_strip` (L87), `user_block` (L113), `gutter` (L123), `tool_line` (L133), `hint` (L138), `footer` (L150), `empty_feed` (L160).

### [pipeline/agentic/tui_widgets.py](../../pipeline/agentic/tui_widgets.py)

Symbols: `btn` (L11), `keyhint` (L17), `heading` (L26), `caps` (L33), `bar` (L37), `box` (L46), `selected` (L71), `row` (L81), `header_row` (L96), `lines_of` (L100), `amber` (L107), `wrap` (L111), `Cols` (L116).

### [pipeline/agentic/writing_guide.py](../../pipeline/agentic/writing_guide.py)

Symbols: `_reference_material` (L23), `approved_writing_profile` (L90), `writing_preferences` (L96), `templates_for` (L134), `writing_guide` (L140).

Local imports: `jobwatch`, `jobwatch.candidate._private_io`, `jobwatch.candidate.intake`.

### [pipeline/cli.py](../../pipeline/cli.py)

Symbols: `register` (L13), `handle` (L22).

Local imports: `jobwatch`, `jobwatch.config`.

### [pipeline/graph.py](../../pipeline/graph.py)

Symbols: `Edge` (L35), `Settings` (L52), `Graph` (L72), `_GaveUp` (L227), `run_once` (L231), `enabled` (L237), `after_collect` (L243).

Local imports: `jobwatch`, `jobwatch.execution_mode`, `jobwatch.llm`, `jobwatch.settings`.

### [pipeline/nodes/__init__.py](../../pipeline/nodes/__init__.py)

Symbols: none at module scope.

### [pipeline/nodes/draft.py](../../pipeline/nodes/draft.py)

Symbols: `ensure_match` (L19), `run` (L33).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.models`.

### [pipeline/nodes/evaluate.py](../../pipeline/nodes/evaluate.py)

Symbols: `run` (L39).

Local imports: `jobwatch.reader`.

### [pipeline/nodes/extract.py](../../pipeline/nodes/extract.py)

Symbols: `ExtractedJobFacts` (L25), `build_profile` (L57), `run` (L70).

Local imports: `jobwatch.apply.evidence`, `jobwatch.candidate.contracts`, `jobwatch.reader`.

### [pipeline/nodes/form_map.py](../../pipeline/nodes/form_map.py)

Symbols: `_flat` (L37), `answers_file` (L50), `screening` (L59), `run` (L75).

Local imports: `jobwatch`, `jobwatch.apply.evidence`, `jobwatch.apply.paths`, `jobwatch.reader`.

### [pipeline/nodes/gate.py](../../pipeline/nodes/gate.py)

Symbols: `decide` (L17).

Local imports: `jobwatch.candidate.eligibility`.

### [pipeline/nodes/ingest.py](../../pipeline/nodes/ingest.py)

Symbols: `content_hash` (L33), `posting_of` (L38), `candidates` (L44), `run` (L55), `_prescreen` (L137), `_browser_text` (L156), `ad_text` (L173).

Local imports: `jobwatch`, `jobwatch.filters`, `jobwatch.interview_browser`, `jobwatch.models`, `jobwatch.prescreen.engine`, `jobwatch.reader`, `pipeline.agentic.discovery`.

### [pipeline/nodes/sort.py](../../pipeline/nodes/sort.py)

Symbols: `KindItem` (L36), `KindReply` (L41), `pending` (L45), `_line` (L56), `run` (L69).

Local imports: `jobwatch.llm`, `jobwatch.reader`.

### [pipeline/schemas.py](../../pipeline/schemas.py)

Symbols: `Strict` (L15), `Stage` (L19), `JobAd` (L32), `WorkRights` (L50), `JobFacts` (L55), `Profile` (L69), `RubricMark` (L80), `MatchScore` (L88), `GateDecision` (L102), `ApplicationPackage` (L109), `ScreeningAnswer` (L120), `ScreeningAnswers` (L126), `FormField` (L130), `FormMap` (L136).

### [pipeline/store.py](../../pipeline/store.py)

Symbols: `now` (L49), `ensure` (L53), `get` (L57), `at_stage` (L66), `admit` (L72), `move` (L79), `annotate` (L93), `event` (L105), `dead_letter` (L111), `retry_dlq` (L117), `drafted_since` (L127), `counts` (L134).

### [pipeline/structured.py](../../pipeline/structured.py)

Symbols: `StructuredFailure` (L21), `schema_text` (L27), `call` (L31).

Local imports: `jobwatch.llm`.

## scripts (4 files)

### [scripts/agentic_acceptance.py](../../scripts/agentic_acceptance.py)

Symbols: `_tables` (L25), `_inside` (L29), `_reason` (L38), `audit_database` (L90), `load_approvals` (L132), `main` (L146).

Local imports: `jobwatch.apply.evidence`, `jobwatch.apply.verify_pdf`, `pipeline.agentic.contracts`.

### [scripts/legacy_too_senior.py](../../scripts/legacy_too_senior.py)

Symbols: `GuardError` (L14), `object_json` (L18), `digest` (L26), `rows` (L30), `eligible` (L40), `selected` (L61), `aggregates` (L65), `preflight` (L71), `require_four` (L75), `begin` (L80), `apply` (L88), `verify_records` (L127), `rollback` (L138), `main` (L157).

Local imports: `jobwatch.web`.

### [scripts/live_legacy_procedure.py](../../scripts/live_legacy_procedure.py)

Symbols: `snapshot` (L16), `snap_hash` (L27), `identity` (L31), `inspect` (L37), `sync_parent` (L47), `durable_backup` (L55), `corrected_snapshot` (L79), `check_after` (L90), `execute` (L95), `restore` (L113), `approve` (L136), `main` (L151).

### [scripts/seed_profile.py](../../scripts/seed_profile.py)

Symbols: `main` (L20).

Local imports: `jobwatch.apply.evidence`, `jobwatch.apply.paths`.

## tests (267 files)

### [tests/apply/__init__.py](../../tests/apply/__init__.py)

Symbols: none at module scope.

### [tests/apply/conftest.py](../../tests/apply/conftest.py)

Symbols: `write_profile` (L88), `apply_env` (L98), `profile` (L107), `eid` (L111), `conn` (L121), `fake_requirements` (L136), `fake_draft` (L151), `FakeLLM` (L202).

Local imports: `jobwatch`, `jobwatch.apply.evidence`, `jobwatch.llm`.

### [tests/apply/test_answers_agent.py](../../tests/apply/test_answers_agent.py)

Symbols: `test_answer_sources_reuse_only_exact_canonical_cv_alias` (L13), `test_answer_sources_refuse_noncanonical_cv_alias` (L24), `test_answer_sources_refuse_canonical_alias_to_another_symlink` (L31), `test_personal_facts_and_written_answers_are_filled_without_manual_fields` (L38), `test_missing_fact_is_asked_once_and_reused` (L78), `test_invalid_candidate_citation_fails_before_browser` (L90), `test_questions_cannot_silently_disappear` (L107), `test_no_approval_if_reviewer_omits_a_required_check` (L119), `_answer_runner` (L134), `test_control_types_and_required_values_cannot_claim_false_completion` (L153), `test_exact_supported_control_shapes_are_accepted` (L167), `test_career_preferences_cannot_prove_qualifications_or_contact_facts` (L177), `test_agent_narrative_does_not_authorize_a_consent_or_contact_field` (L187), `test_legacy_verified_contact_records_and_groups_exclude_unverified_values` (L197), `test_simultaneous_owner_answers_preserve_every_answer_and_revision` (L223), `test_owner_answer_lock_refuses_symlinks` (L236), `test_actual_deepagents_reads_source_then_answers_and_gets_fresh_review` (L245).

Local imports: `jobwatch.apply.answers_agent`, `jobwatch.llm`, `pipeline.agentic.runtime`.

### [tests/apply/test_apply_chain.py](../../tests/apply/test_apply_chain.py)

Symbols: `test_chain_end_to_end` (L23), `test_reviewer_gets_only_drafts_and_named_refs` (L53), `test_chain_failure_is_recorded` (L73), `test_gate_refuses` (L85), `test_ledger_reindex_round_trip` (L101), `test_reindex_refuses_rows_missing_from_ledger` (L119), `_write_pdfs` (L130), `test_verify_pdf_pass_and_ligatures_off` (L138), `test_verify_pdf_page_limit_and_missing_span` (L150), `test_garbage_detection` (L161), `test_ledger_upsert_text_primary_key` (L170), `test_drafting_never_moves_an_application_backwards` (L186), `test_a_status_changed_during_the_chain_is_not_overwritten` (L197), `test_a_draft_already_running_for_a_submitted_application_is_refused` (L207).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.chain`, `jobwatch.apply.verify_pdf`, `jobwatch.settings`.

### [tests/apply/test_apply_units.py](../../tests/apply/test_apply_units.py)

Symbols: `test_gateway_must_be_loopback` (L22), `test_key_fallback_and_no_key_in_call_log` (L27), `test_quote_verification_and_downgrade` (L45), `test_inferred_never_blocker_code_and_db` (L59), `test_requirements_extracted_once_and_ledgered` (L66), `_verify` (L77), `test_verifier_removes_invented_metric` (L81), `test_verifier_reasons` (L105), `test_verifier_derived_and_framing` (L112), `test_verifier_rejects_trivial_spans_overclaimed_years_and_unparsable_results` (L124), `test_letter_date_uses_the_persons_timezone` (L138), `test_verifier_headings_come_from_evidence_only` (L154), `test_verifier_drops_gaps_for_unknown_requirements` (L163), `test_profile_write_guard` (L171), `test_evidence_is_verbatim_and_excludes_contact` (L190), `test_seed_script_copies_not_moves` (L204), `test_bind_loopback_ok` (L230), `test_bind_non_loopback_refused` (L235), `test_request_headers` (L240), `test_stock_edits_flags_template_phrases_and_i_openings` (L260), `test_full_posting_text_prefers_fetched_ad` (L274), `test_meta_text_removed_and_stock_framing_dropped` (L290), `test_repeated_fact_in_new_words_flagged_and_dropped` (L305), `test_caps_checks_a_line_opening_proper_noun_but_not_a_leading_verb` (L324).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.evidence`, `jobwatch.apply.requirements`, `jobwatch.apply.review`, `jobwatch.apply.verify`, `jobwatch.origin_guard`.

### [tests/apply/test_jev_forms.py](../../tests/apply/test_jev_forms.py)

Symbols: `test_jev_sees_labels_only_and_code_types_the_value` (L4), `test_next_button_never_offers_submit_like_labels` (L27), `test_first_name_is_everything_before_the_surname` (L41), `test_career_facts_follow_the_generator_contract` (L47), `test_previous_employer_matches_whole_words_not_substrings` (L67).

Local imports: `jobwatch.apply.career_retrieval`, `jobwatch.apply.jev_forms`.

### [tests/apply/test_prefill.py](../../tests/apply/test_prefill.py)

Symbols: `page` (L13), `answer` (L32), `test_fill_controls_documents_and_never_submit` (L36), `test_unverified_partial_unknown_and_invalid_choices_remain_blank` (L57), `test_requires_exact_application_authorization_before_mutation` (L68), `test_duplicate_names_and_unsupported_controls_fail_closed` (L74), `test_answers_file_private_and_schema_errors_do_not_echo_values` (L81).

Local imports: `jobwatch.apply`.

### [tests/apply/test_prefill_attach.py](../../tests/apply/test_prefill_attach.py)

Symbols: `owner` (L19), `cli` (L54), `test_cli_discovery_attaches_post_step_without_navigation` (L62), `test_cli_fill_existing_step` (L86), `test_host_mismatch_and_ambiguous_tabs_refuse` (L108), `test_cli_host_refusal_no_template_or_mutation` (L122), `test_discovery_wrapped_labels_exclude_control_contents` (L134), `test_login_discovery_and_password_target_refusal` (L143), `test_template_refuses_existing_without_carry_over` (L156), `test_template_symlink_refused_password_omitted_and_id_fallback` (L163).

Local imports: `jobwatch.apply`.

### [tests/apply/test_prefill_cdp.py](../../tests/apply/test_prefill_cdp.py)

Symbols: `get_free_port` (L18), `FixtureHandler` (L23), `test_prefill_cdp_integration` (L72).

### [tests/apply/test_prefill_dynamic.py](../../tests/apply/test_prefill_dynamic.py)

Symbols: `page` (L10), `test_dynamic_controls_never_retarget_verified_answer` (L25), `test_valueless_radio_never_uses_absent_unverified_or_null_answer` (L42).

Local imports: `jobwatch.apply.prefill`.

### [tests/apply/test_prefill_expiry.py](../../tests/apply/test_prefill_expiry.py)

Symbols: `clock` (L16), `test_cli_expiry_before_first_mutation` (L30), `test_expiry_during_multifield_fill_stops_next_upload` (L80), `test_expiry_during_control_validation_blocks_each_mutation` (L110).

Local imports: `jobwatch.apply`.

### [tests/apply/test_prefill_guard.py](../../tests/apply/test_prefill_guard.py)

Symbols: `test_guard_blocks_buttons_and_both_submit_apis_then_releases_owner` (L10).

Local imports: `jobwatch.apply.prefill`.

### [tests/apply/test_prefill_manifest.py](../../tests/apply/test_prefill_manifest.py)

Symbols: `bundle` (L22), `authorize` (L39), `test_refuses_before_any_fill_or_upload` (L49), `test_matching_manifest_uses_authorized_snapshots` (L81), `test_even_self_bound_unsupported_paths_are_refused` (L103), `test_supported_path_still_requires_one_counter` (L113), `test_supported_path_does_not_bypass_url_safety` (L128), `test_hash_command_outputs_only_hashes_and_verified_names` (L136), `test_authorize_cli_requires_manifest_before_browser` (L146).

Local imports: `jobwatch.apply`.

### [tests/apply/test_prefill_pageup.py](../../tests/apply/test_prefill_pageup.py)

Symbols: `public_shape` (L18), `test_pageup_advert_filters_do_not_become_answers_and_owner_challenge_can_resume` (L43), `test_captcha_fragment_is_explicit_owner_checkpoint_not_invalid_url` (L78), `test_pageup_entry_refuses_ambiguous_or_uninspected_destination` (L89), `test_pageup_entry_resource_scope_is_read_only_and_specific` (L107), `test_embedded_manager_pageup_entry_loads_declared_form_then_stops_for_owner` (L115).

Local imports: `jobwatch.apply`, `jobwatch.apply.ats`, `jobwatch.apply.prefill`, `jobwatch.apply.prefill_workflow`, `jobwatch.web`, `jobwatch.web.browser_session`.

### [tests/apply/test_prefill_workflow.py](../../tests/apply/test_prefill_workflow.py)

Symbols: `site` (L21), `pdf_bytes` (L69), `recipe` (L85), `bank` (L104), `run` (L110), `test_multi_step_custom_frame_pdfs_private_snapshot_and_owner_submit` (L116), `test_unknown_or_unverified_answers_stop_before_next` (L140), `test_binding_faults_fail_closed` (L154), `test_network_submit_side_effect_is_blocked` (L181), `test_dynamic_replacement_does_not_receive_verified_answer` (L191), `test_authorized_manifest_binds_verified_package_bytes_and_session` (L200), `test_discovery_covers_questions_frames_options_without_candidate_values` (L230), `test_handoff_removes_guards_from_future_navigation` (L256), `test_network_body_allowlist_distinguishes_save_from_submit` (L266), `test_strict_native_fields_can_attach_hidden_file_input` (L278), `test_authority_bound_sources_fill_without_per_field_owner_verification` (L293), `test_native_next_request_is_derived_from_filled_form` (L323), `test_native_submit_next_advances_without_clicking_final_submit` (L335), `test_final_or_ambiguous_controls_never_become_native_next` (L356), `test_native_post_next_same_url_uses_prepared_exact_body` (L364), `test_dynamically_added_frame_stops_completion` (L383), `test_native_multiple_select_uses_exact_verified_choices` (L392), `test_continue_label_does_not_authorize_final_endpoint_or_action` (L408), `test_continue_label_does_not_authorize_hidden_or_submitter_final_action` (L420), `test_repeated_native_radio_choices_preserve_distinct_group_questions` (L430), `test_websocket_route_retains_owner_browser_policy_after_fill` (L446), `test_custom_radio_applies_selection_before_false_checks_and_verifies_group` (L469).

Local imports: `jobwatch.apply.prefill`, `jobwatch.apply.prefill_workflow`, `jobwatch.apply.verify_pdf`.

### [tests/apply/test_prepare.py](../../tests/apply/test_prepare.py)

Symbols: `inputs` (L14), `planner` (L31), `final_page` (L64), `test_prepares_personal_details_questions_and_both_pdfs_without_manual_bindings` (L73), `test_missing_fact_is_one_private_intake_then_saved_answer_fills_it` (L93), `test_controller_rediscovers_and_answers_native_next_page` (L111), `test_changed_pdf_refuses_before_browser_values` (L130), `test_complex_next_is_reported_as_adapter_gap_without_click` (L142), `test_owner_authorization_is_required_before_read_or_fill` (L153), `test_latest_private_review_and_only_current_intake_acceptance` (L160), `test_advert_apply_anchor_is_followed_without_user_mapping` (L183), `test_resume_only_form_reports_absent_letter_control_honestly` (L197), `test_multipart_upload_next_then_missing_answer_retry_keeps_bound_attachments` (L210), `test_multipart_uploads_questions_and_final_review_are_fully_automatic` (L236), `test_embedded_browser_controller_uploads_through_pinned_transport_and_binds_review` (L253), `test_blocked_autosave_or_upload_never_claims_ready` (L283), `test_a_ready_fill_records_what_a_submit_confirmation_binds_to` (L296), `test_the_original_cv_and_letter_file_names_are_kept_and_are_what_the_form_receives` (L310), `test_an_unsafe_original_name_falls_back_to_the_generic_one` (L325).

Local imports: `jobwatch.apply`, `jobwatch.apply.answers_agent`, `jobwatch.web.browser_session`.

### [tests/baseline_support.py](../../tests/baseline_support.py)

Symbols: `world` (L29), `_match` (L44), `synthetic_case` (L72), `frozen` (L114).

Local imports: `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.service`, `pipeline.schemas`.

### [tests/candidate/__init__.py](../../tests/candidate/__init__.py)

Symbols: none at module scope.

### [tests/candidate/fixtures.py](../../tests/candidate/fixtures.py)

Symbols: `write_cv` (L9), `write_profile` (L16), `fictional_profile` (L24), `fictional_reference` (L33), `fictional_reference_bundle` (L63).

Local imports: `jobwatch.candidate.contracts`.

### [tests/candidate/policy_fixtures.py](../../tests/candidate/policy_fixtures.py)

Symbols: `fact` (L10), `approved` (L17), `policy_of` (L23).

Local imports: `jobwatch.candidate.policy`.

### [tests/candidate/test_acceptance.py](../../tests/candidate/test_acceptance.py)

Symbols: `fictional_reference` (L22), `_confirmed` (L27), `_filesystem_state` (L40), `test_callable_flow_is_read_only_and_exposes_safe_metadata` (L48), `test_education_only_evidence_is_diagnostic_and_never_recommends` (L95), `test_suggested_and_gwa_only_evidence_remain_diagnostic` (L109), `test_unknown_declared_policy_taxonomy_and_explicit_exclusion_are_distinct` (L134), `test_changed_inputs_invalidate_run_identity_and_stale_receipts_fail` (L165), `test_missing_reference_and_unmapped_paths_are_explicit_empty_results` (L203), `test_forged_safe_projection_is_rejected_without_echoing_private_fields` (L221).

Local imports: `jobwatch.candidate`.

### [tests/candidate/test_analysis.py](../../tests/candidate/test_analysis.py)

Symbols: `_reference` (L24), `_mapped` (L55), `test_policy_contract_does_not_read_legacy_family_preferences` (L68), `test_confirmed_ledger_mapping_recommends_target_not_excluded_high_similarity` (L73), `test_hospitality_evidence_does_not_become_target_path` (L101), `test_reference_unavailable_and_no_mappings_is_explicit_empty_result` (L114), `test_unrelated_confirmed_dwa_does_not_ground_candidate_path_for_occupation` (L127), `test_stale_mutated_mapping_fails_at_analysis_entry` (L141), `test_suggested_mapping_remains_diagnostic_and_policy_changes_run_key` (L154), `test_mutated_evidence_receipt_is_rejected_at_analysis_entry` (L170), `_fit` (L181), `test_clusters_never_retain_a_low_rated_gwa_through_a_bridge` (L189), `test_clusters_emit_supported_singleton_proposals` (L200), `test_cluster_seed_cap_is_global_per_policy_partition` (L208), `test_analysis_metadata_rejects_forged_private_run_key` (L220), `test_invalid_forged_policy_error_has_no_nested_context` (L231), `test_unmapped_has_no_recommendations_and_metadata_is_safe` (L244), `test_reference_desirability_annotations_do_not_exclude_careers` (L263).

Local imports: `jobwatch.candidate`, `jobwatch.candidate.analysis`, `jobwatch.candidate.contracts`.

### [tests/candidate/test_assessment.py](../../tests/candidate/test_assessment.py)

Symbols: `Model` (L18), `case` (L29), `budget` (L49), `test_candidate_assessment_runs_before_jobs_and_reference_absence_is_honest` (L53), `test_assessment_identity_changes_for_evidence_profile_policy_or_model` (L70), `test_candidate_findings_cannot_cite_non_primary_sources` (L86), `test_excluded_and_non_target_paths_are_rejected` (L93), `test_snapshot_hashes_career_profile_without_extracting_it_as_evidence` (L101), `test_profile_cannot_silently_replace_bound_source` (L112), `test_authenticated_reference_and_mapping_reuse_existing_structural_analysis` (L120).

Local imports: `jobwatch`, `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `pipeline.agentic.contracts`, `pipeline.agentic.runtime`.

### [tests/candidate/test_contracts.py](../../tests/candidate/test_contracts.py)

Symbols: `test_stable_digest` (L34), `test_digest_rejects_nonfinite_floats` (L41), `test_content_hash` (L48), `test_error_is_safe` (L57), `test_hide_input_in_errors_on_validation_failure` (L63), `test_malformed_hashes_rejected` (L83), `test_evidence_item_education_status_invariants` (L130), `test_quote_suppressed_in_repr` (L229), `test_evidence_item_line_number_bounds` (L252), `test_evidence_bundle_duplicate_ids_rejected` (L286), `test_evidence_bundle_source_mismatch_rejected` (L316), `test_evidence_bundle_path_traversal_filenames_rejected` (L338), `test_evidence_bundle_contents_excluded_from_serialization` (L359), `test_occupation_nonfinite_weights_and_ratings_rejected` (L385), `test_occupation_code_and_family_canonicalization` (L433), `test_canonicalize_family_helper` (L471), `test_target_policy_neutral_defaults_and_explicit_exclusions` (L478), `test_reference_bundle_validation` (L489), `test_reference_bundle_receipt_is_private_and_required_for_verification` (L552), `test_crosswalk_validation` (L565), `test_occupation_fit_and_archetype_and_analysis_result` (L577), `test_analysis_result_rejects_non_digest_run_key` (L630), `test_fixtures_builders` (L639), `test_mapping_method_cap_and_validation` (L656), `test_occupation_fit_structural_metric_bounds` (L687), `test_evidence_bundle_safe_validator_messages_no_private_leak` (L721), `test_nonstring_family_raises_controlled_validation_error` (L756), `test_reference_metadata_families_validation_and_unknown_family_preservation` (L793), `test_arbitrary_mapping_key_never_appears_in_validation_error` (L881), `test_an_unknown_field_name_is_dropped_and_never_surfaces` (L888).

Local imports: `jobwatch.candidate.contracts`, `jobwatch.candidate.reference`.

### [tests/candidate/test_eligibility.py](../../tests/candidate/test_eligibility.py)

Symbols: `check` (L6), `test_hours_compare_numbers_not_fulltime_label` (L9), `test_missing_hours_are_unresolved_only_when_limit_matters` (L15), `test_junior_preference_does_not_impose_two_year_cap` (L19), `test_pr_is_not_citizenship` (L26), `test_clearance_matches_level_and_unknown_never_becomes_no` (L30), `test_no_sponsorship_only_blocks_confirmed_need` (L37), `test_location_and_remote_are_personal` (L43), `test_explicit_none_is_neutral_and_does_not_read_live_profile` (L49), `test_rights_quotes_must_resolve` (L54), `test_foreign_status_does_not_establish_australian_status` (L66), `test_plural_pr_alternative_does_not_waive_nationality_conjunction` (L72), `test_boolean_keyword_flood_stays_bounded` (L79), `test_negated_citizenship_requirement_cannot_be_reintroduced_by_model_label` (L87), `test_verbatim_unrelated_quote_does_not_prove_citizenship_requirement` (L94), `test_same_sentence_requires_both_citizenship_and_clearance` (L102), `test_confirmed_disjunctive_rights_statement_does_not_prove_citizenship_alone` (L108), `test_negative_citizenship_disjunction_does_not_become_positive_residence` (L113), `test_contradictory_confirmed_clearance_claims_require_resolution` (L122), `test_able_to_obtain_clearance_does_not_require_already_holding_it` (L127), `test_clearance_text_cannot_make_one_level_prove_another` (L132), `test_unrelated_or_included_hours_do_not_reduce_required_working_hours` (L141), `test_multiple_confirmed_hour_limits_do_not_expand_permission_by_fact_order` (L145), `test_numeric_weekly_hour_limit_inside_work_rights_is_not_dropped` (L151), `test_profile_title_exception_cannot_override_approved_hours_limit` (L156), `test_no_sponsorship_support_needed_is_not_an_employer_refusal` (L162), `test_contradictory_explicit_citizen_claims_cannot_be_resolved_by_combined_claim` (L167), `test_required_onsite_location_overrides_generic_office_alternatives` (L173), `test_required_onsite_location_missing_from_metadata_is_still_checked` (L179), `test_missing_location_or_commute_cannot_become_verified_eligibility` (L184), `test_omitted_policy_resolves_only_the_current_person_on_each_call` (L191), `test_inferred_rights_cannot_certify_a_restriction` (L202), `test_generic_clearance_prerequisite_is_unknown_without_a_confirmed_clearance` (L207), `test_supplied_quote_must_corroborate_rights_independently_of_another_sentence` (L211), `test_named_visa_alternative_does_not_require_citizenship_or_establish_visa_match` (L217), `test_explicit_valid_rights_requirement_is_unresolved_without_approved_rights` (L223), `test_only_allowlisted_split_keywords_are_repaired_for_rights_scanning` (L227), `test_attendance_requirement_keeps_location_before_the_required_word` (L233), `test_remote_work_needs_posting_evidence_for_the_supported_country` (L238), `test_conflicting_explicit_rights_are_not_overwritten_by_citizenship_inference` (L243), `test_conflicting_combined_and_independent_rights_need_resolution` (L248), `test_conflicting_combined_rights_claims_do_not_make_a_negative_fact` (L255), `test_inconsistent_sponsorship_and_citizenship_facts_need_resolution` (L261), `test_supported_country_boundary_applies_without_personal_regional_limits` (L270), `test_citizenship_and_negated_clearance_are_independent_clauses` (L274), `test_citizenship_or_clearance_allows_either_confirmed_alternative` (L285), `test_unrecognized_family_does_not_bypass_a_confirmed_family_exclusion` (L291), `test_negated_onsite_requirement_does_not_override_remote_availability` (L298), `test_without_restrictions_or_sponsorship_is_not_a_choice_of_restrictions` (L304), `test_foreign_residency_requirement_uses_reside_live_and_resident_wording` (L312), `test_explicit_supported_country_alternative_is_not_a_foreign_only_restriction` (L321), `test_negative_attendance_and_residency_requirements_are_not_positive_demands` (L327), `test_foreign_only_shortcut_also_preserves_australian_alternatives` (L335), `test_duties_for_foreign_residents_are_not_an_applicant_residency_requirement` (L339).

Local imports: `jobwatch`, `jobwatch.candidate.eligibility`.

### [tests/candidate/test_evidence.py](../../tests/candidate/test_evidence.py)

Symbols: `test_cv_quote_binds_exact_primary_line_and_bytes` (L18), `test_exact_relative_cv_alias_reuses_canonical_primary_identity` (L28), `test_cv_alias_accepts_no_other_relative_target` (L40), `test_cv_alias_never_follows_a_second_symlink` (L47), `test_preferred_cv_alias_does_not_fallback_after_parse_failure` (L56), `test_symlink_primary_is_refused_without_private_error_context` (L65), `test_symlink_root_is_refused` (L78), `test_intermediate_symlink_component_is_refused` (L86), `test_ancestor_replacement_at_root_open_never_reads_outside` (L97), `test_absent_primary_sources_reject` (L143), `test_profile_yaml_literal_folded_and_escaped_quoted_scalars_are_decoded` (L155), `test_profile_yaml_quotes_are_decoded_and_have_exact_node_spans` (L164), `test_yaml_unsafe_or_ambiguous_syntax_rejected` (L184), `test_contacts_are_dropped_without_rewriting_quotes` (L190), `test_genuine_annotation_accepts_only_with_primary_bytes` (L198), `_legacy_catalogue` (L207), `test_legacy_generated_catalogue_validates_without_promoting_taxonomy_proof` (L219), `test_legacy_import_cannot_change_a_primary_or_derived_record` (L233), `test_annotation_cannot_forge_primary_quote_or_relabel_kind` (L244), `test_snapshot_verifier_rejects_caller_rehashed_fabrication` (L256), `test_snapshot_verifier_rejects_rehashed_dropped_contact_count` (L271), `test_snapshot_verifier_rejects_rehashed_malformed_annotation_yaml` (L284), `test_verify_error_exposes_no_private_validation_context` (L299), `test_mutated_source_contents_are_rejected` (L315), `test_source_size_is_bounded_and_nonregular_files_rejected` (L326), `test_source_bytes_remain_unchanged` (L332), `test_year_ranges_and_dates_are_not_phone_numbers` (L340), `test_a_phone_number_with_year_like_digit_groups_is_still_contact_data` (L354), `test_bundle_from_contents_equals_snapshot_evidence` (L360), `test_bundle_from_contents_refuses_unknown_names_and_empty_contents` (L366).

Local imports: `jobwatch.apply.evidence`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`.

### [tests/candidate/test_intake.py](../../tests/candidate/test_intake.py)

Symbols: `FakeLLM` (L22), `local_gateway` (L40), `person` (L45), `fake_llm` (L54), `upload_id` (L59), `fact` (L63), `test_upload_is_private_and_outside_profile` (L67), `test_upload_limits` (L80), `test_unreferenced_kind_is_refused` (L85), `test_verbatim_evidence_keeps_its_source` (L90), `test_quote_not_in_upload_is_downgraded_to_inference` (L104), `test_quote_far_from_cited_line_is_downgraded` (L112), `test_cv_gap_never_becomes_unemployed` (L118), `test_employment_evidence_needs_a_quote_that_states_it` (L127), `_status` (L141), `test_employment_status_is_evidence_only_when_the_quote_states_it_and_the_value_agrees` (L150), `test_a_date_range_ending_present_does_not_state_employment` (L156), `test_an_employment_status_that_disagrees_with_its_quote_is_not_evidence` (L163), `test_missing_decision_sections_become_unknown_with_a_question` (L167), `test_model_question_is_kept_and_not_duplicated` (L175), `test_unknown_section_and_bad_basis_are_handled` (L183), `test_prompt_rules_and_numbered_lines` (L190), `_pdf_with_text` (L198), `_docx` (L213), `test_scanned_pdf_has_no_text` (L223), `test_text_pdf_is_extracted_and_reaches_the_model` (L230), `test_docx_is_extracted_and_reaches_the_model` (L238), `test_corrupt_document_is_unreadable_not_empty` (L245), `test_missing_extractor_is_reported_distinctly` (L252), `test_unknown_upload_and_proposal_ids` (L261), `test_uploads_are_per_person` (L271), `test_non_object_model_output_is_parse_failed` (L277), `test_models_are_frozen_and_strict` (L283), `test_extract_text_is_shared_with_the_web_route` (L291), `draft` (L299), `test_edit_with_stale_revision_is_refused` (L304), `test_edit_set_remove_add` (L313), `test_edit_unknown_fact_is_refused_and_nothing_changes` (L329), `test_invalid_edits_are_refused` (L339), `test_answer_records_a_person_fact` (L347), `test_person_facts_are_never_marked_parser` (L364), `test_confirmed_proposal_is_not_editable` (L373), `test_concurrent_edits_do_not_lose_updates` (L384), `test_digest_is_deterministic_and_tracks_every_input` (L400), `Proposal_copy` (L413), `full` (L429), `ok` (L439), `vdir` (L445), `test_confirmation_shows_scope_and_limits` (L449), `test_confirm_with_stale_digest_writes_nothing` (L460), `test_confirm_with_stale_scope_writes_nothing` (L470), `test_only_the_person_confirms` (L476), `test_confirm_writes_immutable_version_and_snapshot` (L482), `test_projection_feeds_existing_readers` (L498), `test_inferred_facts_only_enter_after_confirmation` (L509), `test_person_fact_replaces_parser_unknown_and_unanswered_stay_unknown` (L519), `test_second_confirm_supersedes_drafts_and_numbers_versions` (L530), `test_stale_base_version_is_refused` (L542), `test_existing_profile_without_a_version_must_be_adopted` (L550), `test_confirm_races_with_edit` (L561), `test_hand_made_interests_file_must_be_adopted` (L582), `test_draft_without_base_is_refused_when_versions_exist` (L591), `test_confirm_resumes_after_a_crash` (L603), `hand_made` (L633), `test_owner_profile_is_not_overwritten_without_adoption` (L641), `test_adoption_then_amendment_projects_normally` (L659), `test_an_adopted_owner_onboards_by_a_proposal_on_the_current_version` (L668), `test_adoption_with_extra_hand_made_file_still_allows_next_version` (L682), `test_adoption_refusals` (L689), `test_adoption_is_refused_once_any_version_exists` (L703), `test_amendment_does_not_change_approved_facts_until_confirmed` (L710), `test_hand_edit_after_adoption_is_refused_not_overwritten` (L731), `test_hand_edit_after_a_confirmed_version_is_refused` (L743), `test_a_hand_edit_after_confirmation_turns_discovery_off_until_the_files_match_again` (L751), `test_a_removed_file_or_an_added_file_does_not_turn_discovery_off` (L766), `test_discovery_scope_is_checked_as_the_person_not_the_ambient_user` (L774), `test_adopted_extras_are_carried_into_the_next_evidence_snapshot` (L782), `test_new_hand_made_file_after_adoption_still_needs_adoption` (L794), `test_adopted_version_is_listed_and_symlinks_are_not_adopted` (L803), `test_confirm_refuses_a_proposal_with_an_empty_basis` (L818), `test_stored_scope_with_empty_basis_authorises_nothing` (L826), `BlockingLLM` (L841), `settle` (L855), `held` (L866), `test_questions_available_before_parse_finishes` (L875), `test_answer_during_parse_survives_merge` (L888), `test_confirm_refused_while_parsing` (L910), `test_one_parse_per_person_and_slot_released` (L918), `test_start_proposal_unknown_upload_creates_nothing` (L932), `test_parse_failure_keeps_answers` (L938), `test_add_uploads_merges_incrementally` (L954), `test_add_uploads_needs_a_draft_and_no_parse_in_flight` (L975), `test_parse_runs_as_the_person_and_slot_is_per_person` (L987), `_profile` (L998), `test_upload_profile_files_offers_the_persons_own_files` (L1006), `test_upload_profile_files_refuses_symlinks` (L1015), `test_upload_profile_files_with_nothing_to_offer` (L1026), `_backdate` (L1030), `test_a_parsing_draft_with_no_live_parse_is_recovered` (L1037), `test_a_parsing_draft_with_a_live_slot_is_not_recovered` (L1055), `test_start_proposal_that_cannot_spawn_finishes_as_parse_failed` (L1063), `_bodies_after` (L1074), `test_every_parse_path_refuses_a_model_that_is_not_an_approved_paid_route` (L1083), `test_every_parse_path_refuses_a_gateway_that_is_not_the_local_one` (L1094).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.candidate.evidence`, `jobwatch.llm`, `jobwatch.web`.

### [tests/candidate/test_mapping.py](../../tests/candidate/test_mapping.py)

Symbols: `test_mapping_batch_is_bound_and_sorted_stably` (L15), `test_duplicate_and_stale_mappings_refuse_the_whole_batch` (L27), `test_mapping_limit_is_three_per_evidence` (L43), `test_mapping_output_is_stable_across_input_permutations` (L68).

Local imports: `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.mapping`, `jobwatch.candidate.reference`.

### [tests/candidate/test_person.py](../../tests/candidate/test_person.py)

Symbols: `profile` (L12), `test_hours_limit_accepts_numbers_and_numeric_strings` (L19), `test_a_yaml_syntax_error_is_neutral_but_logged` (L24), `test_a_missing_profile_is_silently_neutral` (L31).

Local imports: `jobwatch.candidate`.

### [tests/candidate/test_policy.py](../../tests/candidate/test_policy.py)

Symbols: `test_unemployed_without_contrary_instruction_is_employment_first` (L14), `test_career_focus_wins_over_unemployment` (L18), `test_unemployment_never_overrides_exclusions` (L22), `test_inferred_unemployment_and_unknown_status_are_balanced_and_ask` (L27), `test_inference_and_unknown_facts_never_become_rules` (L31), `test_free_text_exclusion_stays_prompt_text_and_asks` (L37), `test_a_structured_exclusion_becomes_a_rule_with_its_source_fact` (L42), `test_a_family_rule_value_must_be_a_known_family` (L47), `test_location_and_commute_are_read_from_evidence_text` (L51), `test_no_location_facts_means_no_area_limit` (L56), `test_work_rights_come_from_approved_facts` (L60), `test_citizen_or_pr_detection` (L71), `test_seniority_from_stated_levels_ignores_negated_ones` (L74), `test_policy_hash_is_stable_and_tracks_content_and_version` (L79), `test_changed_circumstances_change_the_strategy` (L86), `test_policy_for_needs_a_confirmed_scope_bearing_version_and_is_per_person` (L91), `test_policy_for_builds_from_a_pinned_approved_payload` (L96), `_policy` (L106), `_hit` (L113), `test_exclusion_hit_family_employer_title_term` (L119), `test_exclusion_hit_work_type` (L130), `test_exclusion_hit_location_state_only_when_no_alternative` (L141), `test_exclusion_hit_location_place_token` (L148), `test_exclusion_hit_and_strategy_never_raise_on_odd_text` (L158), `test_rule_id_uses_fact_id_else_hash` (L164), `test_rules_from_fact_ignores_other_shapes` (L171), `test_remote_and_regions_rules` (L178), `test_a_refusal_of_remote_work_is_not_read_as_remote_ok` (L186), `test_describe_modes` (L192), `test_never_in_a_place_asks_and_adds_no_region` (L205), `test_a_welcomed_place_survives_a_negated_one_in_the_same_sentence` (L210), `test_not_australia_wide_is_a_narrowing_that_asks` (L216), `test_anywhere_except_asks` (L221), `test_a_clean_state_and_suburb_pair_is_not_split` (L226), `test_not_far_does_not_negate_a_place` (L231), `test_negated_australia_wide_does_not_clear_regions_or_the_location_question` (L236), `test_australia_wide_answers_the_location_question` (L242), `test_the_question_text_comes_from_any_evidence_fact` (L247), `test_decimal_and_sentence_distances` (L255), `test_a_contracted_negation_ignores_the_level` (L259), `test_a_non_dict_fact_does_not_void_the_policy` (L264), `test_unknown_work_type_is_an_open_question_not_a_rule` (L271), `test_a_policy_survives_a_json_round_trip` (L278), `test_not_near_a_place_rules_it_out` (L284), `test_not_far_from_the_city_keeps_the_home_region_and_asks_nothing` (L290), `test_australia_wide_except_a_place_asks` (L297), `test_not_far_from_a_place_describes_the_area_and_asks_nothing` (L304), `test_not_far_from_the_city_names_no_region_and_keeps_the_location_question` (L309), `test_not_near_and_not_close_are_clause_boundaries` (L317), `test_not_near_a_place_with_no_home_gives_no_region` (L322), `test_home_state_ignores_a_not_near_tail` (L329), `_archived_target_payload` (L349), `test_archived_policy_json_and_hash_remain_parseable_without_becoming_the_default` (L356), `test_legacy_minimum_is_only_an_explicit_archival_contract` (L366), `test_explicit_exclusion_codes_remain_validated_and_round_trip` (L377), `test_profile_target_policy_is_person_independent_and_drops_the_minimum` (L385), `_person_who_excludes` (L392), `test_neutral_projection_ignores_unapproved_interest_files_across_people` (L400), `test_default_policy_applies_only_each_server_bound_persons_confirmed_family_exclusions` (L410), `test_archived_run_key_parses_and_current_policy_does_not_reuse_it` (L433), `test_denied_australian_citizenship_does_not_disprove_permanent_residency` (L447), `test_person_asserted_keeps_the_negation_that_governs_a_span` (L456).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `pipeline.agentic`, `pipeline.agentic.contracts`.

### [tests/candidate/test_projection.py](../../tests/candidate/test_projection.py)

Symbols: `F` (L8), `approved` (L13), `test_project_returns_the_three_files` (L17), `test_resume_quotes_are_verbatim_extract_cv_items` (L23), `test_quote_that_looks_like_markdown_cannot_forge_structure` (L38), `test_work_rights_dict_and_hours_only_from_a_stated_number` (L44), `test_unknown_and_inference_never_reach_files` (L54), `test_structured_family_exclusion_reaches_the_legacy_files` (L61), `test_interests_target_roles_and_exclusions` (L69).

Local imports: `jobwatch.apply.evidence`, `jobwatch.candidate`.

### [tests/candidate/test_reference.py](../../tests/candidate/test_reference.py)

Symbols: `test_missing_reference_is_unavailable` (L13), `test_root_reference_rejects_without_private_context` (L17), `test_duplicate_json_keys_reject_without_private_context` (L24), `test_loader_binds_raw_bytes_and_crosswalk_returns_all_candidates` (L33), `test_reference_revalidation_rejects_nested_mutation_even_with_stale_hash` (L48), `test_required_metadata_must_be_present_and_nonempty` (L57), `test_reference_rejects_both_source_and_license_maps_empty` (L66), `test_reference_requires_nonempty_source_and_license_maps` (L77), `test_declared_excluded_family_remains_available_for_diagnostics` (L86), `test_reference_export_rejects_nonfinite_weights_and_dangling_ids` (L95), `test_ancestor_replacement_at_final_open_never_reads_outside` (L104), `test_reference_loader_rejects_symlink_components_nonregular_and_oversize` (L151), `test_real_hierarchical_dwa_requires_declared_five_segment_gwa_prefix` (L176), `test_reference_bundle_raw_receipt_is_private_and_excluded_from_serialization` (L185).

Local imports: `jobwatch.candidate.contracts`, `jobwatch.candidate.reference`.

### [tests/candidate/test_rules.py](../../tests/candidate/test_rules.py)

Symbols: `test_add_withdraw_retry_and_immutable_history` (L11), `test_digest_races_payload_conflicts_and_identity` (L32), `test_invalid_rule_is_not_a_draft` (L51), `test_active_rules_survive_later_full_profile_confirmation` (L56), `test_confirmation_recovers_projection_without_minting_another_version` (L72).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`.

### [tests/candidate/test_statistical_inputs.py](../../tests/candidate/test_statistical_inputs.py)

Symbols: `world` (L14), `key` (L21), `test_reference_change_invalidates_runtime_identity` (L25), `test_mapping_state_change_invalidates_identity_and_recommendations` (L32), `test_missing_explicit_reference_fails_closed` (L48), `test_mapping_file_rejects_duplicates_and_symlinks` (L53), `test_public_reference_suggestions_never_become_confirmed_paths` (L62), `test_reference_policy_does_not_promote_counter_or_delivery_roles` (L79), `test_details_are_complete_and_unknown_code_rejected` (L90).

Local imports: `jobwatch.candidate.analysis`, `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.inputs`, `jobwatch.candidate.policy`, `jobwatch.candidate.presentation`, `jobwatch.candidate.reference`, `pipeline.agentic.service`.

### [tests/collectors_councils/test_councils_collectors.py](../../tests/collectors_councils/test_councils_collectors.py)

Symbols: `council` (L14), `test_new_collectors_registered_and_in_fast_tier` (L21), `test_pulse_json_fields` (L28), `test_pulse_robots_and_bad_json_are_errors_not_crashes` (L46), `test_pulse_skips_rows_without_title_or_link` (L55), `test_recruitmenthub_list_fields` (L62), `test_recruitmenthub_site_down_is_error` (L78), `test_jobs_search_cards` (L86), `test_jobs_search_multiple_locations_and_short_list_error` (L100), `test_jobs_search_ignores_other_hosts` (L110), `test_elmo_robots_wildcards` (L118), `test_elmo_list_fields_and_robots_fetch` (L129), `test_elmo_robots_disallow_and_missing_robots` (L144), `test_techone_dataset` (L155), `test_techone_http_error_recorded` (L169), `test_scouttalent_shared_host_needs_ref_prefix` (L176), `test_merged_council_registry_is_wellformed` (L191).

Local imports: `jobwatch`, `jobwatch.collectors`, `jobwatch.config`, `jobwatch.http`.

### [tests/commands/cmdkit.py](../../tests/commands/cmdkit.py)

Symbols: `FakeResp` (L12), `make_env` (L20), `add_match` (L31), `ledger_lines` (L45).

Local imports: `jobwatch`, `jobwatch.config`.

### [tests/conftest.py](../../tests/conftest.py)

Symbols: `fixture_text` (L25), `fixture_json` (L29), `FakeResponse` (L33), `FakeHttp` (L38), `make_config` (L79), `make_ctx` (L89), `_no_env` (L100), `_no_live_model` (L107), `_cv_printer_without_browser` (L115), `_no_openrouter_key` (L140), `_person_in_melbourne` (L149), `_person_profile` (L157), `confirm_discovery` (L176), `_confirm` (L192).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.collectors.base`, `jobwatch.config`, `jobwatch.filters`, `jobwatch.http`, `jobwatch.llm`, `jobwatch.openrouter_extras`, `jobwatch.place`, `pipeline.agentic`.

### [tests/fixtures/adtext/careers_vic_job.html](../../tests/fixtures/adtext/careers_vic_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/jobs_search_job.html](../../tests/fixtures/adtext/jobs_search_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/jora_challenge.html](../../tests/fixtures/adtext/jora_challenge.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/jora_job.html](../../tests/fixtures/adtext/jora_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/linkedin_authwall.html](../../tests/fixtures/adtext/linkedin_authwall.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/linkedin_job.html](../../tests/fixtures/adtext/linkedin_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/oracle_details.json](../../tests/fixtures/adtext/oracle_details.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/oracle_empty.json](../../tests/fixtures/adtext/oracle_empty.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/pageup_job.html](../../tests/fixtures/adtext/pageup_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/phenom_job.html](../../tests/fixtures/adtext/phenom_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/smartrecruiters_aldi.json](../../tests/fixtures/adtext/smartrecruiters_aldi.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/successfactors_filled.html](../../tests/fixtures/adtext/successfactors_filled.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/successfactors_job.html](../../tests/fixtures/adtext/successfactors_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/adtext/workday_job.html](../../tests/fixtures/adtext/workday_job.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/ashby.json](../../tests/fixtures/ashby.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/atlassian_listings.json](../../tests/fixtures/atlassian_listings.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/careers_vic_page.html](../../tests/fixtures/careers_vic_page.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_elmo.html](../../tests/fixtures/councils_elmo.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_jobs_search.html](../../tests/fixtures/councils_jobs_search.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_jobs_search_multiloc.html](../../tests/fixtures/councils_jobs_search_multiloc.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_pulse.json](../../tests/fixtures/councils_pulse.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_recruitmenthub.html](../../tests/fixtures/councils_recruitmenthub.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_recruitmenthub_down.html](../../tests/fixtures/councils_recruitmenthub_down.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_scout_shared_host.html](../../tests/fixtures/councils_scout_shared_host.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/councils_techone.json](../../tests/fixtures/councils_techone.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/employmenthero.json](../../tests/fixtures/employmenthero.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/frozen_person_gate_20261022.py](../../tests/fixtures/frozen_person_gate_20261022.py)

Symbols: `_hold` (L18), `_archive` (L26), `_draft` (L31), `_verified` (L36), `_family_from_archetype` (L48), `_is_program` (L61), `_full_time_exempt` (L74), `_logistics` (L92), `_general_work_rights` (L113), `_hours_signals` (L121), `_level_signals` (L142), `_rights_rule` (L186), `_rights_checks` (L200), `_legacy_person_checks` (L230), `_policy_hours` (L316), `_policy_checks` (L323), `decide` (L414).

Local imports: `jobwatch.candidate.assessment`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.person`, `jobwatch.candidate.policy`, `jobwatch.reader`, `pipeline.agentic.contracts`, `pipeline.agentic.location`.

### [tests/fixtures/greenhouse.json](../../tests/fixtures/greenhouse.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/jora_search.html](../../tests/fixtures/jora_search.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/jsonld_careers.html](../../tests/fixtures/jsonld_careers.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/jsonld_detail_engineer.html](../../tests/fixtures/jsonld_detail_engineer.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/jsonld_detail_payroll.html](../../tests/fixtures/jsonld_detail_payroll.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/jsonld_tafe_listing.html](../../tests/fixtures/jsonld_tafe_listing.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/lever.json](../../tests/fixtures/lever.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/oracle_reqs.json](../../tests/fixtures/oracle_reqs.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/phenom_search.html](../../tests/fixtures/phenom_search.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/phenom_widgets.json](../../tests/fixtures/phenom_widgets.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/scouttalent_index.html](../../tests/fixtures/scouttalent_index.html)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/seek_search.json](../../tests/fixtures/seek_search.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/smartrecruiters.json](../../tests/fixtures/smartrecruiters.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/smartrecruiters_detail.json](../../tests/fixtures/smartrecruiters_detail.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/workable.json](../../tests/fixtures/workable.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/workday_detail_cs.json](../../tests/fixtures/workday_detail_cs.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/workday_detail_de.json](../../tests/fixtures/workday_detail_de.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/workday_detail_vn.json](../../tests/fixtures/workday_detail_vn.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/fixtures/workday_jobs.json](../../tests/fixtures/workday_jobs.json)

Static asset/configuration/tooling entry; inspect the linked source.

### [tests/notify_support.py](../../tests/notify_support.py)

Symbols: `FakeChannel` (L8), `use_fake_channel` (L23).

Local imports: `jobwatch`, `jobwatch.notifier`.

### [tests/occupations/__init__.py](../../tests/occupations/__init__.py)

Symbols: none at module scope.

### [tests/occupations/fixtures.py](../../tests/occupations/fixtures.py)

Symbols: `hash_vector` (L17), `hash_transport` (L28), `approved_llm` (L46), `make_config` (L50), `fact` (L55), `write_approved` (L59), `make_policy` (L65), `toy_reference` (L72).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `jobwatch.config`, `jobwatch.llm`, `jobwatch.occupations.loaders`, `pipeline.agentic.execution`.

### [tests/occupations/reference_fixtures.py](../../tests/occupations/reference_fixtures.py)

Symbols: `write_csv` (L8), `write_onet` (L15), `write_esco` (L34), `write_xlsx` (L47).

### [tests/occupations/test_datasets.py](../../tests/occupations/test_datasets.py)

Symbols: `isolated` (L13), `spec` (L17), `test_fetch_refuses_hash_mismatch_and_leaves_nothing` (L23), `test_unpinned_fetch_needs_trust_on_first_use_then_records_the_hash` (L30), `test_verify_detects_tampering` (L40), `test_fetch_refuses_non_https_and_foreign_hosts` (L49), `test_status_never_touches_the_network_and_reports_missing` (L54), `test_fetch_refuses_unsafe_file_names` (L60), `test_manifest_refuses_path_traversal_and_wrong_identity` (L66), `test_dataset_directory_rejects_traversal_and_symlinks` (L75), `test_fetch_caps_bytes_and_normalises_download_failure` (L86), `test_pins_are_checked_even_after_manifest_is_rewritten` (L95), `test_discovery_error_does_not_echo_arbitrary_input` (L106).

Local imports: `jobwatch.occupations`, `jobwatch.occupations.datasets`.

### [tests/occupations/test_discovery_boundaries.py](../../tests/occupations/test_discovery_boundaries.py)

Symbols: `test_ordering_keeps_five_oldest_after_fifteen_closest` (L21), `test_semantic_duplicate_embedding_limit_resumes_backlog_across_calls` (L40), `test_reconsider_reaches_changed_rule_after_twenty_still_excluded_jobs` (L60), `test_dry_run_collection_uses_unpaid_scope_but_never_refreshes_discovery` (L77), `test_prepare_run_uses_unpaid_confirmed_scope_when_reference_changes` (L97).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.policy`, `jobwatch.occupations`, `jobwatch.occupations.embeddings`, `jobwatch.occupations.plan`, `pipeline`, `pipeline.agentic`, `pipeline.schemas`.

### [tests/occupations/test_discovery_workflow.py](../../tests/occupations/test_discovery_workflow.py)

Symbols: `test_confirm_refresh_and_read_native_fields_and_plan` (L15).

Local imports: `jobwatch`, `jobwatch.dedupe`, `jobwatch.models`, `jobwatch.occupations`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.execution`.

### [tests/occupations/test_embeddings.py](../../tests/occupations/test_embeddings.py)

Symbols: `job` (L16), `adapter` (L20), `conn` (L25), `test_default_query_instruction_and_documents_are_unchanged` (L32), `test_field_kind_and_unknown_kind` (L41), `test_vector_cache_is_per_model_and_prunes` (L51), `test_embed_cached_pays_once` (L60), `test_reference_store_is_private_and_resumable` (L70), `test_discovery_spend_counts_including_errors` (L83), `test_budget_ceiling_stops_embedding` (L93), `test_invalid_vectors_are_refused` (L102), `test_corrupt_files_and_rows_are_refused` (L107), `test_make_embedder_refuses_wrong_gateway` (L120), `test_settings_do_not_change_run_key` (L127), `test_text_key_is_content_addressed` (L136), `test_daily_ceiling_shared_across_discovery_contexts` (L140), `test_spent_day_stops_before_discovery_dispatch` (L154), `test_invocation_ceiling_and_cancellation_still_bound_discovery` (L166), `test_discovery_spend_is_in_existing_daily_total` (L180), `test_vector_store_refuses_symlink_to_another_person` (L188), `test_invalid_budget_deadline_is_refused` (L201), `test_daily_limit_includes_existing_agentic_spend` (L208).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.llm`, `jobwatch.occupations`, `jobwatch.occupations.embeddings`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.execution`, `pipeline.agentic.gateway`, `pipeline.agentic.runtime`.

### [tests/occupations/test_hypotheses.py](../../tests/occupations/test_hypotheses.py)

Symbols: `person` (L19), `compute` (L28), `test_related_fields_rank_above_unrelated` (L32), `test_only_approved_usable_facts_support_hypotheses` (L39), `test_explicit_exclusions_remove_titles_and_families` (L47), `test_career_focus_prioritises_focus` (L55), `test_corresponding_records_collapse` (L62), `test_profile_and_dataset_changes_invalidate_cache` (L69), `test_policy_changes_invalidate_cache` (L86), `test_no_usable_facts_and_missing_reference_are_errors` (L93), `test_person_b_never_reads_person_a_cache_and_files_private` (L103), `test_cache_corruption_is_refused` (L111), `test_select_strategy_is_pure_deduplicated_and_bounded` (L121), `test_reference_index_budget_failure_resumes_completed_batches` (L128), `test_same_version_content_replacement_invalidates_cache` (L154), `test_mismatched_profile_policy_is_refused_before_calls` (L161), `test_supplied_connection_is_used_and_remains_open` (L169), `test_invalid_deadline_is_rejected_before_calls` (L184), `test_new_person_database_is_private` (L192), `test_cached_fields_use_explicit_runtime_config_after_refresh` (L198).

Local imports: `jobwatch`, `jobwatch.candidate.policy`, `jobwatch.occupations`, `jobwatch.occupations.embeddings`, `jobwatch.occupations.hypotheses`, `jobwatch.occupations.loaders`, `pipeline.agentic`, `pipeline.agentic.runtime`.

### [tests/occupations/test_ingest_integration.py](../../tests/occupations/test_ingest_integration.py)

Symbols: `setup` (L12), `add` (L18), `test_semantic_mode_does_not_hash_merge_same_template_different_cities_or_requisitions` (L27), `test_search_plan_location_is_not_blocked_by_legacy_victoria_prefilter` (L34), `test_legacy_location_and_hash_dedup_remain_the_default` (L46), `test_semantic_collection_defers_same_key_merges_until_description_comparison` (L57).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.dedupe`, `jobwatch.models`, `jobwatch.occupations.plan`, `pipeline`, `pipeline.nodes`.

### [tests/occupations/test_loaders.py](../../tests/occupations/test_loaders.py)

Symbols: `isolated` (L13), `register` (L18), `test_bundled_reference_gives_one_record_per_occupation` (L28), `test_record_text_cuts_on_a_word_boundary` (L36), `test_onet_loader_orders_core_tasks_first_and_keeps_top_skills` (L43), `test_esco_loader_uses_essential_skills_only` (L50), `test_missing_columns_fail_closed_and_other_datasets_still_load` (L56), `test_unverified_dataset_is_not_loaded_even_after_it_was_cached` (L62), `test_osca_loader_uses_recorded_column_map_and_carries_merged_cells` (L70), `test_osca_missing_columns_fail_closed` (L80), `test_correspondences_with_unloaded_endpoint_are_dropped` (L86), `test_only_bundled_never_includes_optional_sources` (L93), `test_crosswalk_uses_real_esco_numeric_codes_not_a_guessed_uri_column` (L98), `test_osca_correspondence_schema_failure_is_not_silent` (L114), `test_broken_optional_crosswalk_does_not_break_bundled_reference` (L122), `test_esco_requires_its_numeric_crosswalk_code_column` (L131).

Local imports: `jobwatch.occupations`, `jobwatch.occupations.loaders`.

### [tests/occupations/test_plan.py](../../tests/occupations/test_plan.py)

Symbols: `policy` (L12), `hyps` (L17), `test_queries_and_hash_are_stable_deduplicated_and_capped` (L21), `test_overlay_keeps_settings_and_uses_home_without_mutating_base` (L32), `test_remote_searches_and_extra_locations` (L44), `test_query_cleanup_and_whole_word_recall_only_widens` (L53), `test_plan_storage_is_private_and_per_person` (L63), `test_defaults_and_flag_separation` (L75), `test_invalid_settings_refused` (L86).

Local imports: `jobwatch`, `jobwatch.occupations`, `jobwatch.occupations.plan`, `pipeline.agentic.discovery`.

### [tests/occupations/test_relevance.py](../../tests/occupations/test_relevance.py)

Symbols: `Embedder` (L17), `env` (L25), `add` (L39), `test_related_duties_and_verbatim_embedding_quote` (L49), `test_no_without_verifiable_quote_is_uncertain_and_prompt_has_no_personal_facts` (L57), `test_verified_no_and_unavailable_model` (L72), `test_real_counted_role_extraction_uses_only_public_ad_and_field_titles` (L83), `test_passages_are_bounded_overlapping_windows` (L102), `test_screen_stores_once_shadow_does_not_archive_and_on_reuses_judgment` (L108), `test_partial_ads_and_missing_refresh_cost_nothing` (L127), `test_screen_failure_defers_without_archiving_and_respects_limit` (L138), `test_rule_prefilter_uses_confirmed_policy_by_default_and_no_model` (L151), `test_structured_duplicate_guards` (L163), `test_duplicate_archives_newer_cross_source_only_and_ready_survives` (L171).

Local imports: `jobwatch`, `jobwatch.candidate.policy`, `jobwatch.occupations.embeddings`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.discovery`, `pipeline.agentic.runtime`, `pipeline.schemas`.

### [tests/outcomes/outkit.py](../../tests/outcomes/outkit.py)

Symbols: `envelope` (L13), `FakeMcp` (L19), `FakeLLM` (L46), `sse` (L60).

### [tests/outcomes/test_out_callback.py](../../tests/outcomes/test_out_callback.py)

Symbols: `grid_hdi` (L13), `test_prior_only` (L28), `test_posterior_2_of_10` (L36), `test_sampled_hdi_is_deterministic` (L43), `test_callback_stats_per_arm_and_digest` (L47), `test_saved_then_rejected_without_applying_is_not_a_trial` (L72), `test_render_without_applications` (L84).

Local imports: `jobwatch`, `jobwatch.commands.state`, `jobwatch.digest`, `jobwatch.outcomes.callback`.

### [tests/outcomes/test_out_sync.py](../../tests/outcomes/test_out_sync.py)

Symbols: `synthetic_mail` (L24), `env` (L44), `run` (L53), `test_scan_proposes_and_dedupes` (L57), `test_naive_timestamps_are_read_as_utc_and_do_not_crash_the_scan` (L84), `test_approve_reject_on_the_board` (L94), `test_never_hired_db_check_and_code` (L114), `test_expiry_after_7_days` (L125), `test_dry_run_writes_nothing_and_calls_no_llm` (L134), `test_no_applications_no_search` (L145), `test_queries_are_scoped_to_company_and_ats_since_applied` (L153), `test_company_terms` (L164), `test_classify_rules` (L181), `test_conflicting_body_is_ambiguous` (L185), `_Session` (L190), `test_mcp_client_read_only_allowlist` (L212), `test_scan_holds_no_write_transaction_over_network_calls` (L226), `test_mcp_loopback_urls_accepted` (L260), `test_mcp_non_loopback_urls_rejected` (L271), `test_friend_without_google_never_reads_owner_mailboxes` (L276).

Local imports: `jobwatch`, `jobwatch.commands.state`, `jobwatch.outcomes.classify`, `jobwatch.outcomes.mcp`, `jobwatch.outcomes.sync`, `jobwatch.settings`, `jobwatch.web.actions`.

### [tests/outcomes/test_readiness.py](../../tests/outcomes/test_readiness.py)

Symbols: `db` (L6), `test_no_outcomes_is_untrained_not_prior_prediction` (L12), `test_pending_not_failure_and_draft_rejected_not_trial` (L17), `test_historical_callback_preserved_after_rejection` (L24).

Local imports: `jobwatch.outcomes.readiness`.

### [tests/outcomes/test_response_time.py](../../tests/outcomes/test_response_time.py)

Symbols: `history` (L5), `test_missing_history_is_insufficient_and_never_predictive` (L11), `test_pending_is_censored_and_preapplication_events_are_ignored` (L16), `test_thirty_timed_replies_permit_only_later_investigation` (L24).

Local imports: `jobwatch.outcomes.readiness`.

### [tests/preferences/test_core.py](../../tests/preferences/test_core.py)

Symbols: `alternative` (L13), `store` (L19), `test_gets_do_not_migrate` (L22), `test_immutable_owner_explicit_idempotent` (L27), `test_reject_bad_alternatives` (L45), `populate` (L51), `test_train_only_missing_and_posting_split` (L61), `good_summary` (L77), `test_finite_per_parameter_gates_and_holdout` (L83), `test_stale_and_synthetic_cannot_predict` (L93), `test_synthetic_cannot_mix_with_owner` (L104), `test_prediction_arithmetic_in_memory_fixture_only` (L109).

Local imports: `jobwatch.preferences`, `jobwatch.preferences.features`, `jobwatch.preferences.model`.

### [tests/preferences/test_experience_v4.py](../../tests/preferences/test_experience_v4.py)

Symbols: `approved` (L12), `alternative` (L18), `test_verified_overall_experience_uses_exact_approved_tenure` (L35), `test_canonical_jd_alias_is_the_same_verified_ad_source` (L48), `test_specialist_or_mixed_experience_cannot_use_overall_tenure` (L58), `test_unverified_scope_or_inexact_dates_stay_missing` (L69), `test_unknown_other_role_dates_cannot_be_treated_as_zero_tenure` (L74), `test_truncated_exact_quote_cannot_hide_specialist_source_tail` (L86), `test_wrapped_specialist_source_tail_is_not_a_new_condition` (L92), `test_general_source_quote_cannot_hide_specialist_frozen_requirement` (L99).

Local imports: `jobwatch.preferences.features`, `pipeline.agentic.contracts`.

### [tests/preferences/test_features_v4.py](../../tests/preferences/test_features_v4.py)

Symbols: `evaluation` (L15), `make_alt` (L19), `test_v4_neutral_and_held_is_never_eligible` (L34), `test_arbitrary_bounded_alternatives_preserve_three_default` (L48), `test_hourly_salary_and_frozen_provider_age` (L57), `test_conversion_requires_exact_source_hours_and_verified_ad` (L72), `test_explicit_positive_negative_ad_facts` (L90), `test_exact_approved_tenure_merges_overlaps_and_pins_present` (L99), `test_ambiguous_hours_cannot_convert_pay` (L123), `test_ambiguous_flexibility_stays_missing` (L133), `test_salary_conversion_does_not_use_ranged_or_office_hours` (L143), `test_explicit_flexibility_refusal_is_observed_zero` (L153).

Local imports: `jobwatch.preferences`, `jobwatch.preferences.experience`, `jobwatch.preferences.features`, `pipeline.agentic.contracts`.

### [tests/preferences/test_local_r.py](../../tests/preferences/test_local_r.py)

Symbols: `test_real_four_chain_synthetic_fit` (L11).

Local imports: `jobwatch.preferences`, `jobwatch.preferences.features`.

### [tests/preferences/test_migration.py](../../tests/preferences/test_migration.py)

Symbols: `historical` (L11), `test_migration_preserves_originals_selected_none_and_split` (L27), `test_migration_refuses_changed_or_unverifiable_provenance` (L46), `test_migration_skips_unverifiable_historical_profile_and_absent_jobs` (L55), `test_migration_never_promotes_unanswered_or_synthetic_labels` (L64), `test_migration_checks_owner_before_any_access` (L72), `test_migration_skips_missing_old_approved_hash` (L78), `test_migration_recovers_interruption_without_reanswering` (L96), `test_multiple_version_upgrades_do_not_duplicate_historical_labels` (L110), `test_changed_current_pool_during_migration_cannot_copy_stale_choice` (L123), `test_held_migration_preserves_explicit_noneligible_status` (L139), `test_migration_never_combines_cross_context_postings_across_splits` (L163).

Local imports: `jobwatch`, `jobwatch.preferences`, `jobwatch.preferences.features`, `jobwatch.preferences.migration`.

### [tests/preferences/test_profile_neutral.py](../../tests/preferences/test_profile_neutral.py)

Symbols: `test_new_target_policies_have_no_unconfirmed_personal_exclusions` (L15), `test_historical_policy_payload_keeps_its_digest_and_parses_across_people` (L24), `test_cold_start_tastes_and_family_intercepts_are_neutral` (L35), `test_alternative_validation_does_not_reapply_unapproved_legacy_preferences` (L45), `historical_store` (L53), `test_historical_choices_stay_readable_explicitly_stale_and_unmodified` (L68), `test_a_stale_unanswered_set_cannot_acquire_a_new_owner_response` (L82), `test_fit_payload_preserves_canonical_families_and_has_no_directional_prior` (L89), `test_historical_fit_is_stale_without_rewriting_its_posterior_or_owner_labels` (L103), `test_read_only_insights_refuse_stale_synthetic_choices_without_predicting_or_fitting` (L119), `test_confirmed_preference_only_change_stales_choices_and_fit_without_rewriting` (L136).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.preference_service`, `jobwatch.preferences.features`, `jobwatch.preferences.model`, `jobwatch.preferences.store`, `pipeline.agentic.model_insights`.

### [tests/preferences/test_utilities_v4.py](../../tests/preferences/test_utilities_v4.py)

Symbols: `posterior` (L11), `Stub` (L19), `test_arbitrary_utility_intervals_do_not_invent_choice_probabilities` (L26), `test_utilities_fail_closed_without_valid_genuine_fit` (L44), `test_utilities_reject_fit_provenance` (L53), `test_utilities_reject_invalid_posterior_and_transform` (L63), `test_explicit_migration_split_provenance_and_overlap` (L69).

Local imports: `jobwatch.preferences`, `jobwatch.preferences.features`, `jobwatch.preferences.model`.

### [tests/ranking_support.py](../../tests/ranking_support.py)

Symbols: `make_evaluation` (L12), `policy_stub` (L51), `relevance_stub` (L56).

Local imports: `pipeline.agentic.contracts`, `pipeline.schemas`.

### [tests/realapp.py](../../tests/realapp.py)

Symbols: `_pdf` (L48), `_fake_run_role` (L53), `_serve_form` (L73), `_uvicorn` (L98), `_free_port` (L110), `_seed` (L117), `RealApplication` (L134), `real_application` (L160), `main` (L234).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.config`, `jobwatch.web.browser_session`, `pipeline.agentic`, `pipeline.agentic.api`.

### [tests/test_accounts.py](../../tests/test_accounts.py)

Symbols: `test_connected_sites_reads_cookie_names_only` (L8).

Local imports: `jobwatch.web.accounts_routes`.

### [tests/test_acp_agent.py](../../tests/test_acp_agent.py)

Symbols: `FakeClient` (L18), `_setup` (L32), `_prompt` (L48), `test_initialize_session_prompt_updates` (L52), `test_permission_round_trip_approves_and_rejects` (L70), `test_cancelled_permission_stays_pending_then_new_prompt_rejects` (L89), `test_session_cancel_sets_the_turn_flag` (L105).

Local imports: `pipeline.agentic`, `pipeline.agentic.runtime`.

### [tests/test_adtext.py](../../tests/test_adtext.py)

Symbols: `fx` (L24), `Net` (L29), `net` (L44), `no_net` (L53), `ref_for` (L128), `routes_for` (L133), `world` (L140), `test_inner_html_balances_nested_divs_and_skips_scripts` (L162), `test_smartrecruiters_sections_job_description_first_company_last` (L173), `test_linkedin_parser_reads_the_markup_div_only` (L183), `test_jora_parser_reads_the_description_container` (L192), `test_careers_vic_parser_reads_the_description_field` (L199), `test_oracle_parser_joins_fields_and_handles_empty_answers` (L205), `test_jsonld_parser_handles_escaped_html_plain_text_and_graphs` (L221), `test_host_ok` (L257), `test_host_ok_refuses_ip_and_local_names_even_when_allowed` (L261), `test_redirect_is_followed_by_hand_and_stays_on_site` (L266), `test_redirect_to_another_site_is_never_requested` (L273), `test_redirect_loop_gives_up` (L281), `test_each_source_fetches_one_url_and_returns_the_ad` (L289), `test_blocked_statuses_raise_blocked` (L299), `test_gone_ad_returns_empty` (L307), `test_challenge_login_and_empty_pages_return_empty` (L325), `test_redirect_off_site_returns_empty_for_every_source` (L330), `test_wrong_host_or_shape_is_refused_without_a_request` (L356), `test_oracle_source_id_must_name_an_oraclecloud_host` (L366), `test_smartrecruiters_source_id_is_validated` (L371), `test_indeed_rows_are_never_fetched` (L376), `test_linkedin_id_comes_from_raw_then_source_id_then_url` (L383), `test_linkedin_requests_the_clean_url_not_the_stored_one` (L393), `test_jora_requests_the_path_without_the_search_tracking_query` (L400), `test_identity_id_in_final_url_or_a_title_word` (L408), `test_page_for_another_job_is_rejected` (L422), `test_short_body_is_rejected` (L432), `test_text_is_capped` (L439), `test_ensure_text_fetches_saves_and_returns_full` (L448), `test_ensure_text_order_ad_text_then_long_description_then_fetch` (L460), `test_teaser_only_source_stays_teaser` (L471), `test_allow_fetch_false_never_requests` (L480), `test_ensure_text_wrong_host_url_gives_teaser_and_no_request` (L486), `test_ensure_text_gone_ad_is_not_saved` (L494), `test_ensure_text_raises_blocked_and_saves_nothing` (L503), `test_ensure_text_challenge_page_is_not_saved` (L512), `test_fetcher_double_is_called_with_source_id_for_every_fetchable_source` (L520), `test_seek_keeps_its_label_and_double_convention` (L537), `test_double_returning_nothing_or_less_than_the_teaser_is_not_saved` (L544), `test_ensure_text_accepts_rows_that_already_carry_url_and_raw_json` (L552), `test_fetch_host_keys` (L567), `test_host_ok_refuses_backslash_control_whitespace_and_userinfo` (L591), `test_redirect_with_a_backslash_host_is_never_requested` (L595), `test_fetch_jsonld_requests_only_the_stored_url_and_only_on_the_employers_hosts` (L602), `test_fetch_jsonld_on_the_recorded_host_never_follows_a_page_supplied_url` (L613), `_Handler` (L628), `_Server` (L681), `local` (L686), `test_do_get_reads_a_normal_page_and_redirects_without_a_body` (L694), `test_do_get_refuses_an_oversize_or_decompression_bomb_response` (L704), `test_do_get_gives_up_on_a_slow_drip_at_the_total_deadline` (L713), `test_do_get_bounds_a_header_phase_drip_on_the_requests_path` (L721), `test_requests_path_uses_a_connect_and_read_timeout_pair` (L729), `test_do_get_refuses_a_non_text_body` (L740), `test_default_caps_are_3mb_and_30s` (L745), `cut` (L750), `test_classify_full_partial_teaser` (L755), `test_classify_takes_the_whole_ad_from_raw_json_when_the_collector_kept_it` (L768), `test_ensure_text_does_not_call_a_cut_description_the_full_ad` (L787), `test_ensure_text_fetches_the_page_for_a_cut_description_and_replaces_it` (L795), `test_a_gone_page_leaves_a_cut_description_partial` (L807), `test_cut_description_uses_raw_before_any_request` (L815), `test_each_new_fetcher_reads_what_comes_after_the_cut` (L825), `test_successfactors_url_may_start_with_a_site_code` (L834), `test_pulse_matches_the_link_id_and_ignores_other_jobs` (L842), `test_pulse_source_id_is_validated` (L851), `test_successfactors_filled_page_is_reported_as_gone` (L855), `test_challenge_page_is_reported_as_a_wall` (L861), `test_a_real_ad_page_that_mentions_sign_in_is_not_a_wall` (L871), `test_seek_id_is_validated_before_any_request` (L877), `_seek_page` (L883), `test_fetch_seek_goes_through_the_capped_reader` (L891), `test_fetch_seek_still_stops_the_run_on_block_statuses` (L899), `test_fetch_seek_gone_empty_wall_and_redirects` (L905), `test_lever_ads_are_full_when_raw_json_holds_the_whole_ad` (L919), `test_a_lever_ad_with_a_mid_length_description_is_read_from_the_whole_raw_text` (L932), `test_local_text_reads_raw_json_for_a_mid_length_lever_description` (L955), `test_would_request_knows_a_refused_row_without_asking_anyone` (L965), `test_wants_fetch_is_false_for_a_refused_row_and_force_skips_the_log` (L978), `test_a_legacy_jsonld_row_needs_a_registry_host` (L991).

Local imports: `jobwatch`, `jobwatch.dedupe`, `jobwatch.models`.

### [tests/test_agentic_acceptance.py](../../tests/test_agentic_acceptance.py)

Symbols: `synthetic_db` (L21), `fake_verify` (L58), `audit` (L64), `test_acceptance_counts_only_current_agentic_ready_verified_real_package` (L69), `test_acceptance_excludes_synthetic_and_non_ready_packages` (L77), `test_acceptance_rejects_tampered_pdf_bytes_even_if_manifest_claims_verified` (L87), `test_acceptance_ignores_legacy_draft_rows` (L95), `test_acceptance_requires_all_pdf_claim_and_review_verification_flags` (L103), `test_acceptance_is_read_only` (L110).

Local imports: `pipeline.agentic.contracts`.

### [tests/test_agentic_contracts.py](../../tests/test_agentic_contracts.py)

Symbols: `citation` (L33), `key` (L37), `test_citation_quote_is_private_and_lookup_requires_exact_source_match` (L42), `test_requirement_importance_is_frozen_by_complete_requirement_identity` (L56), `test_requirement_set_rejects_duplicate_ids_and_unsupported_inference` (L66), `test_citation_validation_rejects_unknown_ids_and_mutated_hashes` (L74), `test_citation_validation_revalidates_copied_model_and_authenticates_source_hash` (L82), `test_run_identity_is_stable_and_binds_each_input_component` (L94), `test_public_models_ignore_unknown_fields` (L103), `test_dimension_rejects_bool_nonfinite_and_out_of_range_scores` (L108), `test_evaluation_uses_separate_holistic_score_and_complete_match_coverage` (L114), `test_evaluation_requires_gap_risk_and_mitigation_for_high_importance` (L125), `_evaluation_base` (L135), `test_review_must_bind_exact_draft_and_required_criteria` (L148), `test_draft_hash_covers_actual_payload_and_nested_mutation_changes_digest` (L159), `test_draft_hash_error_has_no_cause_or_context_after_non_json_mutation` (L168), `test_agentic_screening_answer_requires_citations_and_hash_binds_them` (L183), `test_gate_decision_has_bounded_safe_route_without_permission_semantics` (L199), `test_agentic_error_is_stable_alias` (L207), `test_draft_rejects_non_json_and_over_limit_content` (L212), `test_manifest_is_only_verified_hash_metadata_and_has_no_paths` (L219), `test_reservations_charge_full_maximum_until_trusted_settlement` (L229), `test_checkpoint_json_refuses_duplicate_keys_without_leaking_payload` (L244), `test_checkpoint_rejects_boolean_version_and_evaluation_prevalidator_hides_private_keys` (L254), `test_checkpoint_round_trip_keeps_ambiguous_charge_and_rejects_bad_totals` (L274).

Local imports: `pipeline.agentic.contracts`.

### [tests/test_agentic_draft.py](../../tests/test_agentic_draft.py)

Symbols: `_evaluation` (L20), `_proposal` (L42), `_bundle` (L60), `test_drafter_review_and_pdf_package_are_verified` (L67), `test_drafter_rejects_unsupported_claims_before_package_creation` (L107), `test_reviewer_gets_fresh_draft_hash_and_revision_is_bounded` (L129), `test_draft_refuses_missing_or_changed_snapshot_before_model` (L160), `test_independent_reviewer_cannot_choose_its_own_passing_criteria` (L170), `test_real_deepagent_writer_reads_checks_then_submits` (L183), `test_snapshot_readers_preserve_full_sources_and_refuse_unknown_names` (L224), `test_screening_answer_is_never_taken_by_position_when_its_question_is_missing` (L256), `_failure_captures` (L276), `_written` (L284), `test_private_failure_capture_is_off_unless_opted_in` (L288), `test_opted_in_private_failure_capture_is_owner_only` (L295).

Local imports: `jobwatch.candidate.evidence`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.draft`, `pipeline.agentic.review`, `pipeline.agentic.runtime`, `pipeline.schemas`.

### [tests/test_agentic_draft_limits.py](../../tests/test_agentic_draft_limits.py)

Symbols: `test_atomic_daily_and_batch_caps_and_boundary` (L19), `test_legacy_ready_drafts_count_without_double_counting` (L40), `test_wait_preserves_checkpoint_and_only_excludes_explicit_wait` (L54), `test_unknown_started_cost_is_never_refunded_or_paused` (L74), `test_zero_cap_still_evaluates_and_never_drafts` (L89), `test_cap_change_reuses_evaluation_and_ready_without_new_admission` (L103), `test_invocation_wall_deadline_still_limits_virtual_clock` (L122), `test_invalid_caps_fail_closed` (L132), `test_next_day_resume_retains_paid_budget_and_does_not_repeat_evaluation` (L137), `test_only_safe_predraft_waits_resume_with_failure_count_intact` (L165), `test_virtual_clock_never_renews_current_invocation` (L183), `test_existing_batch_honors_zero_current_invocation_seconds` (L204).

Local imports: `jobwatch.llm`, `pipeline.agentic.contracts`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`, `pipeline.agentic.service`, `pipeline.agentic.store`, `pipeline.schemas`.

### [tests/test_agentic_evaluate.py](../../tests/test_agentic_evaluate.py)

Symbols: `FakeModel` (L18), `build_case` (L29), `budget` (L75), `test_layout_only_quote_change_restores_exact_source_before_freezing` (L79), `test_layout_conversion_never_repairs_wording_identity_or_ambiguous_quotes` (L96), `test_two_actual_agent_passes_keep_candidate_out_of_full_jd_context` (L104), `test_seventeen_requirements_are_searched_in_two_batches_within_role_turn_cap` (L123), `test_distinct_ads_and_candidates_produce_real_variable_results` (L163), `test_paid_model_accounting_analysis_label_uses_canonical_family_before_gate` (L171), `test_unknown_family_is_not_silently_promoted_to_an_owner_target` (L186), `test_neutral_jd_family_vocabulary_does_not_imply_personal_exclusion` (L195), `test_job_ad_preferences_and_research_cannot_prove_candidate_qualifications` (L207), `test_frozen_requirements_full_coverage_and_citations_fail_closed` (L223), `test_hash_or_profile_change_is_rejected_before_model_call` (L238), `test_public_research_tool_choice_has_no_candidate_query_surface` (L251), `test_public_research_unavailable_is_honest_and_does_not_abort_evidence_assessment` (L269), `test_all_extracted_requirements_are_covered_with_frozen_importance` (L279), `test_uncertain_jd_facts_remain_visible_in_report` (L298), `test_job_requirement_cannot_cite_candidate_source` (L305), `test_descriptive_report_headings_preserve_complete_validated_report` (L313), `test_report_heading_normalization_never_drops_or_fabricates_sections` (L322), `test_contradictory_match_gets_one_bounded_schema_correction` (L329), `test_repeated_contradictory_match_cannot_expand_correction_budget` (L341), `test_essential_not_applicable_gets_existing_bounded_correction` (L350), `test_repeated_essential_not_applicable_stops_after_one_correction` (L359), `test_jd_research_precedes_frozen_facts_without_candidate_data` (L368), `test_jd_research_unavailable_does_not_abort` (L404), `test_research_budget_mismatch_rejected_before_jd_call` (L416), `test_archetype_cannot_invent_a_personal_exclusion` (L426).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.candidate.policy`, `pipeline.agentic.contracts`, `pipeline.agentic.evaluator`, `pipeline.agentic.gate`, `pipeline.agentic.matching`, `pipeline.agentic.research`, `pipeline.agentic.runtime`.

### [tests/test_agentic_evaluator_citations.py](../../tests/test_agentic_evaluator_citations.py)

Symbols: `test_case_punctuation_and_bullets_resolve_to_the_ads_text` (L7), `test_ellipsis_quote_uses_its_longest_part` (L11), `test_invented_wording_still_fails` (L15).

Local imports: `pipeline.agentic.evaluator`.

### [tests/test_agentic_forms.py](../../tests/test_agentic_forms.py)

Symbols: `_evaluation` (L16), `test_form_map_only_uses_cited_screening_answers_and_marks_unknown_owner_fields` (L32), `test_form_map_rejects_answer_not_supported_by_its_quote` (L56), `test_form_map_marks_missing_answers_as_owner_to_answer` (L69), `test_no_questions_does_not_create_a_fake_owner_hold` (L80).

Local imports: `jobwatch.candidate.evidence`, `pipeline.agentic.contracts`, `pipeline.agentic.forms`, `pipeline.schemas`.

### [tests/test_agentic_gate.py](../../tests/test_agentic_gate.py)

Symbols: `policy` (L27), `evaluation` (L32), `test_valid_verified_entry_program_is_routed_to_draft` (L58), `test_score_threshold_is_inclusive_at_four` (L63), `test_incomplete_capture_holds_before_other_rules` (L71), `test_ad_hash_mismatch_holds` (L76), `test_expected_run_key_mismatch_holds` (L81), `test_sponsor_availability_is_not_sponsor_only` (L87), `test_sponsored_applicants_only_is_blocked` (L102), `test_melbourne_hybrid_passes_but_interstate_onsite_contradiction_archives` (L115), `test_seniority_and_minimum_years_hard_gate` (L129), `test_full_time_program_exception_and_unstated_hours_hold` (L138), `test_excluded_family_and_uncertain_legitimacy` (L166), `test_long_ad_tail_with_rights_block_is_checked` (L178), `rebound` (L195), `test_model_cannot_assert_away_unknown_or_contradictory_seniority_hours` (L215), `test_entry_compatible_hours_range_is_not_mistaken_for_fulltime` (L221), `test_preferred_experience_does_not_override_entry_level` (L226), `test_negated_entry_wording_is_not_positive_evidence` (L240), `test_unrelated_negation_preserves_positive_entry_evidence` (L253), `unverified_blocker` (L258), `test_unverified_employer_blocker_holds_even_with_high_score` (L272), `test_unverified_blocker_does_not_mask_confirmed_policy_exclusion` (L285), `test_ad_quote_cannot_pass_as_candidate_proof_at_gate` (L292), `test_remote_location_requires_access_from_candidate_location` (L307), `test_high_score_without_any_candidate_match_cannot_draft` (L316), `test_cited_verified_metro_locality_can_pass_without_word_melbourne` (L333), `test_unproven_or_conflicting_location_cannot_pass_on_model_label` (L348), `test_intern_title_confirms_claimed_program_without_substring_or_duties_false_positive` (L363), `test_check_timing_preserves_unknowns_and_existing_admission_rules` (L378), `test_melbourne_suburb_named_in_a_sentence_or_list_counts` (L403), `test_regional_victoria_is_in_scope` (L418), `test_suburb_of_a_queensland_city_is_not_a_victorian_place` (L424), `test_program_where_you_nominate_your_office_is_in_scope` (L430), `test_unknown_family_is_read_from_the_archetype` (L444), `test_ad_inviting_visa_holders_is_not_a_citizenship_requirement` (L451), `test_only_graduate_and_vacation_roles_bypass_full_time` (L466), `test_graduate_and_vacation_roles_draft_from_3_5` (L471), `test_general_work_rights_excludes_citizenship_pr_and_clearance` (L494), `test_logistics_requirements_never_hold_a_job` (L509), `test_commute_home_follows_the_current_person_not_the_first_one_cached` (L515).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `jobwatch.reader`, `pipeline.agentic.contracts`, `pipeline.agentic.location`, `pipeline.schemas`.

### [tests/test_agentic_gate_policy.py](../../tests/test_agentic_gate_policy.py)

Symbols: `retarget` (L26), `outcome` (L38), `test_nsw_person_is_not_archived_for_a_sydney_job` (L43), `test_nsw_person_archives_a_melbourne_job` (L49), `test_stored_outside_label_is_ignored` (L54), `test_interstate_onsite_rule_follows_the_persons_regions` (L59), `test_interstate_ad_cited_at_the_interstate_office` (L69), `test_no_location_policy_never_blocks_on_location` (L76), `test_unknown_location_with_regions_holds` (L81), `test_missing_location_evidence_with_regions_holds` (L87), `test_nominate_your_office_program_keeps_unresolved_location_open` (L92), `test_non_australia_only_ads_are_archived` (L98), `test_commute_limit_comes_only_from_the_policy` (L104), `test_remote_ad_is_not_archived_on_distance` (L115), `test_remote_ad_must_establish_australia` (L129), `_rule` (L144), `test_exclusions_are_rules` (L170), `test_unemployment_does_not_override_exclusion` (L176), `test_a_family_rule_holds_an_ad_the_evaluator_could_not_place` (L183), `test_allowed_families_and_live_exclusions_are_not_consulted_on_the_policy_path` (L189), `test_policy_path_reads_no_profile_files_or_victoria_constants` (L197), `test_wrong_input_types_raise_the_fixed_code` (L207), `test_company_defaults_to_empty_and_none_policy_remains_neutral` (L214), `rights` (L224), `stated` (L228), `job` (L233), `with_blocker` (L237), `test_no_hours_limit_reads_neither_an_employment_label_nor_a_live_profile_limit` (L256), `test_actual_hours_are_compared_to_the_confirmed_limit` (L268), `test_material_missing_hours_stay_unknown_even_for_a_wanted_program` (L278), `test_confirmed_levels_are_distinct_from_required_years` (L294), `test_years_wording_has_no_shared_junior_ceiling` (L301), `test_material_requirement_gaps_still_hold_independently_of_high_scores` (L307), `test_citizen_or_pr_requirement_preserves_known_and_unknown_statuses` (L322), `test_permanent_residency_never_establishes_citizenship` (L335), `test_an_unsupported_model_rights_label_does_not_become_a_fact` (L341), `test_actual_clearance_requirements_hold_unknowns_and_respect_confirmed_absence` (L352), `test_clearance_terms_without_a_requirement_add_no_personal_blocker` (L365), `test_clearance_and_citizenship_demands_are_independent` (L370), `test_explicit_legacy_configuration_cannot_reactivate_donor_rules` (L378).

Local imports: `jobwatch.candidate.contracts`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.gate`.

### [tests/test_agentic_graph.py](../../tests/test_agentic_graph.py)

Symbols: `test_run_agentic_job_disabled_by_default` (L10), `test_agentic_batch_run_empty` (L17).

Local imports: `pipeline.agentic.service`, `pipeline.schemas`.

### [tests/test_agentic_liveness.py](../../tests/test_agentic_liveness.py)

Symbols: `reader` (L11), `test_active_observation_binds_full_current_source_without_candidate_data` (L13), `test_nonlive_pages_never_supply_evaluation_text` (L22), `test_unverified_identity_or_fallback_cannot_pass_gate` (L30), `test_observation_rejects_modified_ad_bytes` (L34), `test_seek_public_mirror_preserves_saved_identity_and_actual_source` (L39), `test_seek_mirror_never_accepts_other_job_query_host_port_scheme_or_application` (L62), `test_latest_observation_absent_table_is_unknown` (L70), `test_current_observation_requires_fresh_exact_source` (L79), `test_unexpected_transport_failure_is_unknown_without_error_details` (L88), `test_fresh_observation_expires_at_closing_day_boundary_without_refetch` (L95), `workday_fetcher` (L111), `test_workday_explicit_active_record_verifies_without_browser` (L124), `test_workday_unverified_record_cannot_become_active` (L137), `test_workday_explicit_unavailable_cannot_fall_back_to_stale_browser` (L145), `test_workday_active_flags_do_not_override_visible_expired_deadline` (L150), `test_wrong_workday_tenant_cannot_close_requested_job` (L157), `test_workday_structured_deadline_expires_cached_observation` (L165), `test_page_furniture_that_changes_between_reads_does_not_change_the_ad` (L179), `test_http_posting_url_is_read_over_https` (L187).

Local imports: `jobwatch.candidate.contracts`, `jobwatch.interview_ad`, `pipeline.agentic.liveness`.

### [tests/test_agentic_matching.py](../../tests/test_agentic_matching.py)

Symbols: `test_qwen_query_instructions_and_budget_use_one_explicit_route` (L21), `test_invalid_vectors_fail_without_retry_and_retain_charge` (L44), `matching_case` (L56), `test_unlabeled_comparison_never_claims_quality` (L65), `test_reviewed_comparison_counts_archived_suitable_jobs_and_missing_usage` (L75), `test_comparison_rejects_group_leakage_and_snapshot_mismatch` (L87), `test_owner_approved_paid_combos_use_only_the_configured_gateway` (L99), `test_configured_combo_names_preserve_denied_route_boundaries` (L111), `test_chat_combo_exception_does_not_authorise_embeddings` (L117), `test_batch_search_matches_individual_searches_and_reads_shared_records_once` (L123), `test_invalid_batch_search_is_rejected_before_any_evidence_access` (L150), `test_model_catalog_labels_paid_bare_combo_without_losing_other_options` (L162).

Local imports: `jobwatch`, `jobwatch.candidate.evidence`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.evaluation`, `pipeline.agentic.execution`, `pipeline.agentic.gateway`, `pipeline.agentic.matching`, `pipeline.agentic.runtime`.

### [tests/test_agentic_mcp.py](../../tests/test_agentic_mcp.py)

Symbols: `stub_server` (L42), `stub_config` (L49), `choice` (L62), `transport_llm` (L66), `prepare_person` (L79), `test_mcp_is_off_by_default` (L90), `test_broken_and_malformed_servers_degrade_without_raising` (L97), `test_stub_tools_are_namespaced_and_write_tools_are_gated` (L111), `test_read_tool_result_reaches_the_model` (L123), `test_write_tool_pauses_and_never_runs` (L140).

Local imports: `jobwatch`, `jobwatch.llm`, `pipeline.agentic.chat`, `pipeline.agentic.mcp_client`.

### [tests/test_agentic_policy_wiring.py](../../tests/test_agentic_policy_wiring.py)

Symbols: `with_flag` (L25), `key_for` (L33), `evaluate` (L40), `table_exists` (L47), `test_profile_is_default_and_legacy_spelling_is_an_equivalent_alias` (L51), `test_flag_must_be_legacy_or_profile` (L63), `test_every_confirmed_policy_change_enters_the_run_key_and_aliases_do_not` (L72), `test_profile_mode_gate_uses_the_confirmed_policy` (L92), `test_legacy_spelling_applies_the_confirmed_policy_and_records_its_decision` (L106), `test_missing_confirmed_policy_stays_neutral_and_writes_no_policy_decision` (L117), `test_changed_confirmed_exclusion_gets_a_new_run_and_preserves_the_old_decision` (L127), `test_a_confirmed_exclusion_cannot_be_disabled_by_a_mode_alias` (L153), `test_gate_current_is_the_only_live_gate_call` (L163), `test_gate_current_derives_commute_and_company_from_the_posting` (L199), `test_public_classifier_probabilities_never_establish_personal_knockouts` (L225), `test_personal_classifier_signals_stay_advisory_for_all_confirmed_profiles` (L232), `test_commute_comes_from_the_policy_home` (L250), `test_the_run_hands_the_evaluator_the_policy_commute` (L264), `test_decision_log_is_idempotent_and_per_run_key` (L278).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.policy`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.location`, `pipeline.agentic.persistence`, `pipeline.schemas`.

### [tests/test_agentic_reconciliation.py](../../tests/test_agentic_reconciliation.py)

Symbols: `key` (L13), `manifest` (L18), `world` (L26), `test_real_schema_reuses_application_and_idempotent_run_scoped_draft` (L43), `test_interrupted_ledger_flush_recovers_same_package_without_duplicate_rows` (L62), `test_wrong_manifest_input_or_stale_worker_cannot_publish` (L88), `test_changed_manifest_for_same_run_and_corrupt_artifact_fail_closed` (L104), `test_late_outbox_recovery_cannot_rewind_a_newer_owner_outcome` (L115), `test_reindex_refuses_pending_outbox_update_to_an_existing_row` (L144).

Local imports: `jobwatch`, `pipeline.agentic.contracts`, `pipeline.agentic.persistence`, `pipeline.agentic.store`.

### [tests/test_agentic_research.py](../../tests/test_agentic_research.py)

Symbols: `test_local_searx_uses_fixed_endpoint_bounded_public_results_and_cache` (L9), `test_local_searx_unavailable_is_bounded_and_fixed_code` (L39), `test_search_stream_cannot_consume_the_whole_job_deadline` (L54), `test_pinned_fetch_address_retries_share_one_timeout` (L72), `test_public_page_extracts_readable_bounded_context_without_scripts` (L90), `test_pinned_connector_reads_real_http_parser_and_refuses_error_status` (L103), `test_service_research_only_receives_public_job_identity_and_shared_budget` (L133), `test_research_fetch_converts_wall_clock_budget_to_monotonic_deadline` (L150), `test_research_intent_builds_query_from_immutable_public_context` (L173), `test_model_cannot_supply_arbitrary_research_query_or_url` (L193), `test_research_query_budget_is_shared_and_unavailable_provider_stays_unavailable` (L202), `test_safe_fetcher_uses_pinned_addresses_with_original_tls_hostname_and_no_redirects` (L218), `test_safe_fetcher_rejects_mixed_public_and_private_dns_answers` (L231), `test_provider_result_ids_are_deterministic_and_pages_are_not_registry_instructions` (L240), `test_interview_intents_use_only_public_snapshot_and_existing_query_allowance` (L261), `test_raw_public_document_preserves_whole_payload_without_research_text_cap` (L284), `test_raw_document_rejects_invalid_urls_before_network` (L300), `test_raw_document_keeps_network_size_and_deadline_guards` (L315), `test_pinned_document_rejects_premature_content_length_eof` (L322), `test_public_document_preserves_mime_and_checks_metadata` (L348), `test_safe_fetcher_preserves_status_without_remote_content` (L360).

Local imports: `pipeline.agentic`, `pipeline.agentic.research`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [tests/test_agentic_runtime.py](../../tests/test_agentic_runtime.py)

Symbols: `Args` (L12), `Terminal` (L17), `FakeModel` (L22), `budget` (L33), `test_model_selects_multiple_real_tools_until_typed_terminal` (L38), `test_invalid_tool_arguments_fail_closed_without_calling_handler` (L61), `test_batch_budget_two_thread_race_never_oversubscribes` (L72), `test_batch_admission_caps_active_jobs_at_two` (L87), `test_checkpoint_restore_retains_unknown_dispatch_maximum_and_deadline` (L97), `test_persistence_callback_runs_before_transport_and_failure_blocks_dispatch` (L107), `test_model_can_choose_different_tool_sequence` (L122), `test_429_opens_batch_circuit_and_no_credential_retry` (L134), `test_missing_boolean_or_oversized_usage_does_not_refund` (L146), `test_transport_and_handler_exceptions_have_no_raw_context_or_private_payload` (L155), `test_chat_once_without_explicit_test_key_never_loads_keyfiles` (L167), `test_authentication_failure_does_not_retry_keys_or_leak_response` (L176), `test_gateway_failure_pauses_other_jobs_in_same_batch` (L188), `test_a_call_cut_off_by_the_run_clock_is_a_deadline_not_an_outage` (L199), `test_invalid_checkpoint_restore_does_not_leak_the_batch_slot` (L213).

Local imports: `jobwatch`, `jobwatch.llm`, `pipeline.agentic.runtime`.

### [tests/test_agentic_service.py](../../tests/test_agentic_service.py)

Symbols: `SyntheticGateway` (L28), `world` (L118), `test_native_api_prepares_existing_pipeline_package` (L161), `test_complete_real_pipeline_varied_jobs_pdf_ledger_and_idempotency` (L259), `test_interruption_resumes_saved_candidate_evaluation_and_package` (L298), `test_board_projection_refuses_corrupt_verified_pdf` (L324), `test_snapshot_is_read_only_and_detects_changed_inputs` (L334), `test_failure_and_shared_token_limit_preserve_checkpoints_and_no_leases` (L345), `test_timer_selection_refreshes_missing_ready_checks_without_starving_pending` (L356), `test_cli_inventory_and_execution_share_bound_snapshot` (L374), `test_snapshot_change_between_inventory_and_batch_is_refused` (L389), `test_real_config_and_legacy_pipeline_settings_select_same_runtime` (L400), `test_resumed_batch_summary_preserves_and_reports_original_budget` (L414), `test_manual_draft_uses_selected_runtime_and_flag_off_keeps_legacy_gate` (L442), `test_gateway_credential_selection_is_explicit_and_never_falls_back` (L466), `_public_observation` (L482), `test_liveness_stops_before_any_model_or_credential` (L497), `test_liveness_changed_whole_ad_is_saved_and_held_without_models` (L508), `test_cached_ready_rechecked_without_models_or_credentials` (L524), `test_late_public_observation_cannot_overwrite_new_capture` (L556), `test_late_public_observation_cannot_overwrite_new_claim` (L568), `test_expired_package_recovers_without_models_or_new_draft_admission` (L586), `test_timer_refreshes_only_missing_stale_or_source_mismatched_ready` (L608), `test_blocker_gate_revision_invalidates_old_decision_identity` (L634), `test_location_reference_change_invalidates_decision_not_candidate` (L645), `test_real_deepagents_research_checkpoints_on_file_database` (L657), `_chat_llm` (L696), `test_gated_call_with_unbindable_args_does_not_brick_the_thread` (L709), `test_pending_approval_that_became_unbindable_is_refused_on_the_next_message` (L723), `test_model_that_keeps_emitting_unbindable_calls_fails_the_turn_after_three_refusals` (L743), `test_human_decision_on_an_approval_that_became_unbindable_is_refused` (L756), `test_transient_profile_error_does_not_refuse_a_valid_pending_approval` (L777), `test_approved_auxiliary_call_with_extra_model_args_still_runs` (L801), `test_failed_started_activity_row_does_not_leak_the_lease` (L819), `test_store_failure_in_the_finish_still_releases_lease_and_batch_slot` (L834), `test_failed_first_checkpoint_does_not_leak_the_batch_slot` (L853), `test_one_crashing_job_does_not_abort_the_batch` (L863), `test_posting_the_model_keeps_answering_invalidly_stops_jumping_the_queue` (L878), `_ready_fill` (L905), `test_an_approved_chat_submit_queues_exactly_the_reviewed_fill` (L919), `test_ad_text_claiming_approval_still_needs_the_owner_and_an_approval_replays_once` (L941), `test_a_chat_submit_whose_fill_changed_after_the_request_is_refused` (L962), `test_a_chat_submit_without_a_reviewed_fill_is_refused_not_offered` (L983), `test_collection_never_drafts_documents` (L996), `_reset_profile` (L1011), `_seed` (L1016), `_finished` (L1024), `AgenticStoreEnsure` (L1030), `_stub_batch` (L1035), `test_no_discovery_without_confirmed_profile` (L1042), `test_adopted_profile_alone_authorises_no_discovery` (L1052), `test_daily_assessment_cap_from_scope` (L1063), `test_daily_token_ceiling_defers_the_rest` (L1079), `test_deferred_job_is_evaluated_next_day` (L1097), `test_daily_allowance_does_not_shrink_persisted_batch_ceiling` (L1116), `test_no_empty_batch_row_when_nothing_is_selected` (L1143), `test_a_spent_day_does_no_collection` (L1161), `_onboarding_llm` (L1184), `_approve_through` (L1196), `_settled` (L1208), `onboarding` (L1221), `test_profile_confirm_needs_human_approval_bound_to_digests` (L1243), `_profile_chat` (L1264), `test_authenticated_chat_confirms_the_profile_shown_in_the_conversation` (L1287), `test_profile_chat_requires_the_current_review_before_yes` (L1323), `test_profile_chat_correction_is_a_message_and_never_confirmation` (L1358), `test_profile_chat_retires_a_legacy_per_answer_approval` (L1384), `test_profile_chat_reissues_a_preexisting_confirmation_without_a_review` (L1426), `test_native_question_can_receive_an_authenticated_chat_answer` (L1462), `test_profile_confirm_refused_if_the_draft_changed_after_the_request` (L1487), `test_model_text_is_not_approval` (L1505), `test_profile_confirm_for_an_unknown_draft_is_refused_not_offered` (L1528), `test_onboarding_tools_run_as_the_person_and_record_their_words` (L1536), `test_profile_confirmation_reports_an_empty_scope_as_incomplete` (L1571), `test_profile_reread_keeps_answers_and_adds_document_facts` (L1590), `_tool_texts` (L1619), `test_profile_answer_accepts_the_persons_words_from_an_earlier_turn` (L1623), `test_profile_tools_refuse_words_the_person_did_not_say` (L1643), `test_profile_tools_refuse_a_span_the_person_negated` (L1672), `test_recording_the_persons_words_updates_only_the_unconfirmed_draft` (L1705), `test_profile_tools_use_the_last_human_message_on_a_resumed_turn` (L1738), `test_only_one_profile_parse_may_start_per_turn_and_it_is_reserved` (L1762), `test_the_agent_api_refuses_to_bind_a_non_loopback_address` (L1784), `_typed_reply_setup` (L1803), `test_a_typed_yes_while_submit_is_pending_never_approves` (L1815), `test_a_typed_change_while_submit_is_pending_reaches_the_model` (L1830), `test_a_typed_reply_with_a_question_and_an_approval_pending_answers_the_question_only` (L1841).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.llm`, `jobwatch.models`, `jobwatch.web`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`, `pipeline.agentic.contracts`, `pipeline.agentic.identity`, `pipeline.agentic.liveness`, `pipeline.agentic.persistence`, `pipeline.agentic.review`, `pipeline.agentic.runtime`, `pipeline.agentic.service`, `pipeline.agentic.store`, `pipeline.nodes`, `pipeline.schemas`.

### [tests/test_agentic_store.py](../../tests/test_agentic_store.py)

Symbols: `key` (L11), `empty` (L16), `reserve` (L24), `Harness` (L36), `test_two_connections_fence_live_claims_and_expired_generations` (L48), `test_claim_rejects_boolean_generation_even_when_equal_to_one` (L67), `test_claim_copy_must_match_database_lease_fence` (L76), `test_checkpoint_cas_and_operation_replay_keep_authoritative_batch_totals` (L85), `test_changed_input_uses_posting_wide_monotonic_generation` (L109), `test_changed_input_uses_posting_wide_monotonic_generation` (L116), `test_two_jobs_share_atomic_batch_ceiling_and_keep_history_on_changed_input` (L123), `test_reservation_settlement_failure_research_and_snapshots_are_monotone` (L150), `test_expiry_malformed_stored_data_and_external_transaction_are_safe` (L180), `test_worker_research_checkpoint_preserves_claim_fence_before_search` (L204).

Local imports: `pipeline.agentic.contracts`, `pipeline.agentic.research`, `pipeline.agentic.runtime`, `pipeline.agentic.service`, `pipeline.agentic.store`.

### [tests/test_ask_cards.py](../../tests/test_ask_cards.py)

Symbols: `test_card_click_saves_and_job_answers_are_derived` (L20).

Local imports: `jobwatch.apply`, `jobwatch.web`.

### [tests/test_auth.py](../../tests/test_auth.py)

Symbols: `client` (L10), `test_auth` (L29), `test_api_paths_get_json_401_not_login_redirect` (L52).

Local imports: `jobwatch`, `jobwatch.web.auth_routes`.

### [tests/test_autonomous_evaluation.py](../../tests/test_autonomous_evaluation.py)

Symbols: `transport` (L14), `native_choices` (L33), `run_case` (L37), `test_native_assessment_three_calls_skills_and_idempotency` (L46), `test_changed_inputs_cannot_reuse_result` (L73), `test_partial_resume_rebuilds_access_without_completed_paid_replay` (L95), `test_response_journal_survives_failure_before_tool_checkpoint` (L115), `test_skip_does_not_dispatch_any_paid_model` (L133), `test_invalid_matching_fails_closed` (L146), `test_canonical_gate_holds_missing_evidence_despite_high_score` (L173), `test_configured_turn_limit_survives_resume` (L183), `test_unlimited_does_not_convert_six_call_target_to_a_cap` (L194), `test_native_json_text_cannot_trigger_protocol_fallback` (L206), `test_default_off_and_configuration_validation` (L213), `test_batch_retrieval_and_uncertainties_survive_cached_read` (L223), `test_numeric_token_details_omit_arbitrary_provider_metadata` (L237), `test_evidence_and_candidate_identity_mismatch_refused_before_paid_calls` (L246), `test_incomplete_native_requirements_get_schema_feedback_without_protocol_fallback` (L255).

Local imports: `jobwatch`, `jobwatch.candidate.policy`, `jobwatch.llm`, `pipeline.agentic.autonomous`, `pipeline.agentic.gate`, `pipeline.agentic.matching`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [tests/test_baseline.py](../../tests/test_baseline.py)

Symbols: `test_tags_are_the_six_contract_tags` (L31), `test_tag_rules` (L60), `test_tags_come_back_in_contract_order` (L64), `test_gate_sources_are_the_reconciled_gate_files` (L72), `_patched_copy` (L82), `test_gate_version_changes_by_itself_when_a_gate_source_changes` (L89), `test_a_changed_data_file_or_policy_module_changes_the_gate_version` (L102), `test_a_missing_policy_module_is_left_out` (L107), `test_pre_revision_gate_version_is_a_digest` (L114), `_keys` (L118), `test_duplicate_adverts_share_a_group` (L123), `test_related_employer_cases_share_a_group` (L128), `test_grouping_is_transitive` (L133), `test_group_id_ignores_input_order_and_fits_the_comparison_limit` (L139), `test_blank_employer_never_merges_strangers` (L150), `test_dedupe_key_needs_company_and_title_parts` (L155), `test_company_spellings_normalise_to_one_employer_key` (L162), `test_synthetic_case_sets_a_deterministic_group_id` (L168), `test_models_carry_the_contract_fields` (L175), `_dir` (L190), `_code` (L194), `_profile_yaml` (L198), `_evaluated` (L214), `test_freeze_writes_a_private_hash_verified_baseline` (L231), `test_freeze_calls_no_model_and_writes_no_database_row` (L259), `test_large_shared_artifacts_are_stored_once` (L268), `_flip` (L280), `test_tampered_baseline_is_refused` (L286), `test_a_tampered_blob_is_refused` (L303), `test_loading_historical_source_inventory_never_rewrites_frozen_records` (L311), `test_decision_follows_the_frozen_profile_not_later_edits` (L332), `test_commute_is_measured_from_the_frozen_home` (L355), `test_the_pinned_profile_version_is_frozen_with_the_baseline` (L375), `test_the_decision_policy_is_frozen_only_when_the_policy_path_is_active` (L395), `test_the_decision_policy_path_is_inactive_in_this_phase` (L411), `test_decide_frozen_reports_an_unbuildable_snapshot` (L415), `test_a_failed_freeze_leaves_no_visible_baseline` (L423), `test_baselines_are_per_person_and_ids_cannot_escape` (L438), `test_freeze_refuses_without_a_profile_version_or_cases` (L457), `test_unreadable_artifacts_are_skipped_and_counted` (L470), `test_a_case_with_a_blank_ad_hash_is_skipped_and_never_grouped_under_content` (L488), `test_selection_by_posting_ids_and_limit` (L508), `test_limit_is_validated` (L516), `test_posting_ids_are_validated` (L523), `test_git_commit_is_unknown_outside_a_checkout` (L529), `test_git_commit_reads_the_checkout_head` (L533), `test_utcnow_is_iso_seconds_in_utc` (L537), `_first_case` (L543), `_tree_bytes` (L547), `test_label_requires_the_owner_actor` (L552), `test_label_is_private_append_only_and_latest_wins` (L561), `test_write_label_appends_a_prebuilt_owner_label_and_refuses_other_actors` (L576), `test_a_malformed_label_line_is_an_error_not_a_skip` (L608), `test_bad_labels_are_refused` (L629), `test_unknown_case_and_unknown_baseline_are_refused` (L655), `test_labelling_validates_the_baseline_id_before_any_path_is_joined` (L672), `_refuse_bad_ids` (L693), `test_owner_tags_extend_the_deterministic_tags` (L703), `test_effective_tags_are_a_union_in_contract_order_and_latest_labels_is_pure` (L713), `test_owner_label_model_limits` (L734), `test_label_writer_is_not_reachable_from_agent_surfaces` (L744), `test_decide_frozen_goes_through_gate_current` (L753), `test_freeze_stores_the_confirmed_policy_even_for_retained_legacy_configuration` (L782), `test_profile_mode_freeze_measures_the_commute_from_the_policy_home` (L803).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.candidate.evidence`, `jobwatch.candidate.policy`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.baseline`, `pipeline.agentic.contracts`, `pipeline.agentic.gate`, `pipeline.agentic.location`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [tests/test_browser_session.py](../../tests/test_browser_session.py)

Symbols: `local_site` (L15), `manager` (L38), `test_browser_opens_only_on_request_and_streams_owner_controls` (L44), `test_snapshot_stream_remains_available_during_prepare_owner_input_locked` (L63), `test_profile_is_private_and_shared_so_logins_carry_over` (L86), `test_second_person_gets_their_own_profile_and_the_owners_stays_untouched` (L97), `test_subrequests_to_private_network_are_blocked` (L134), `test_production_browser_rejects_private_or_credential_urls` (L148), `test_mixed_public_private_dns_is_refused` (L153), `test_pinned_transport_preserves_multiple_auth_cookies` (L161), `test_owner_login_popup_close_restores_application_and_prepare_target` (L167), `test_preparation_failure_is_visible_and_owner_control_is_released` (L186), `test_unprepared_script_requests_are_blocked_between_fill_steps` (L199), `test_prepared_apply_anchor_navigation_is_allowed_during_automation` (L210), `test_strict_fill_handoff_preserves_manager_websocket_denial` (L219), `submission_site` (L246), `test_review_blocks_delayed_submission_until_owner_final_control` (L276), `test_review_blocks_delayed_get_navigation_without_owner_action` (L314), `test_owner_login_anchor_popup_stays_scoped_and_restores_protected_application` (L328), `test_login_popup_is_adopted_before_target_lookup_finishes` (L347), `test_owner_native_login_submit_does_not_release_application_guard` (L406), `test_owner_captcha_submit_allows_only_challenge_traffic` (L421), `test_owner_submit_is_detected_but_never_pressed_by_jobwatch` (L444), `test_failed_submit_text_is_not_a_confirmation` (L486), `test_confirmation_text_is_recognised` (L493), `test_confirmation_url_only_matches_a_final_confirmation_page` (L503), `test_open_applications_lists_only_the_current_persons_live_browsers` (L508).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.prefill_workflow`, `jobwatch.web.browser_session`.

### [tests/test_candidate_checkpoint_reuse.py](../../tests/test_candidate_checkpoint_reuse.py)

Symbols: `test_separate_jobs_reuse_completed_candidate_assessment_without_repaying` (L12), `test_reusable_candidate_refuses_stale_identity_and_corrupt_artifact` (L30).

Local imports: `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.persistence`, `pipeline.agentic.store`.

### [tests/test_careerops_cv.py](../../tests/test_careerops_cv.py)

Symbols: `_Profile` (L8), `_claim` (L18), `test_partial_fill_matches_career_ops_semantics` (L32), `test_cv_html_merges_one_employer_and_prints_work_rights_once` (L39), `test_ats_check_flags_columns_and_missing_headings` (L48), `test_real_print_is_ats_grade_a` (L53), `test_confirmed_templates_change_section_order_consistently_with_markdown` (L58).

Local imports: `jobwatch.apply.careerops_cv`.

### [tests/test_chat.py](../../tests/test_chat.py)

Symbols: `test_tests_and_other_databases_never_text_the_owner` (L12), `test_notify_saves_then_pushes_and_retries_a_failed_delivery` (L20), `test_answer_sends_history_and_snapshot_to_sonnet` (L36), `test_pipeline_errors_stay_out_of_chat` (L51).

Local imports: `jobwatch`, `jobwatch.web`.

### [tests/test_cli_baseline.py](../../tests/test_cli_baseline.py)

Symbols: `_transcript` (L19), `run` (L23), `_use_world` (L34), `test_cli_end_to_end` (L38), `test_freeze_warns_when_the_gate_source_changed` (L78), `test_list_with_no_baselines` (L91), `test_freeze_opens_the_database_read_only` (L97), `test_cli_errors_print_the_code_and_exit_one` (L113), `test_label_command_refuses_without_a_terminal` (L132), `test_label_help_names_the_judgment_requirement` (L143), `test_label_commands_are_the_only_label_writers` (L151).

Local imports: `jobwatch`, `pipeline.agentic`.

### [tests/test_cli_preferences.py](../../tests/test_cli_preferences.py)

Symbols: `test_migrate_needs_confirm_before_loading_config_or_opening_db` (L7), `test_register_migrate_flag` (L17), `test_explicit_migrate_uses_rw_and_does_not_fit` (L25), `test_explicit_migrate_missing_database_returns_safe_error` (L42).

Local imports: `jobwatch`, `jobwatch.preferences`.

### [tests/test_cli_profile.py](../../tests/test_cli_profile.py)

Symbols: `test_profile_adopt_creates_version_one_for_the_current_person` (L10), `test_profile_adopt_refusal_exits_non_zero_with_the_code` (L23), `_two_people` (L33), `test_run_skips_a_person_without_a_confirmed_profile` (L42), `test_read_skips_a_person_without_a_confirmed_profile` (L55), `test_user_all_splits_the_unit_budget_over_the_people_who_run` (L68), `test_manual_assessment_commands_are_gated` (L84).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.config`, `pipeline`, `pipeline.agentic`.

### [tests/test_cli_user.py](../../tests/test_cli_user.py)

Symbols: `test_user_flag_writes_only_that_users_db` (L4), `test_dry_run_help_matches_behaviour` (L12).

Local imports: `jobwatch`.

### [tests/test_collect_pipeline.py](../../tests/test_collect_pipeline.py)

Symbols: `fresh` (L20), `postings` (L24), `fake` (L36), `cfg` (L56), `test_run_alerts_once_then_dedupes` (L60), `test_run_publishes_fresh_matches_to_the_board` (L75), `test_dry_run_never_consumes_rows_a_live_run_publishes` (L87), `test_observed_dates_seed_first_then_alert` (L99), `test_health_counts_consecutive_failures_and_recovers` (L111), `test_a_collector_crash_keeps_what_it_had_already_collected` (L126), `test_only_and_unknown_collector` (L149), `test_skipped_when_nothing_configured` (L156), `test_digest` (L162).

Local imports: `jobwatch`, `jobwatch.collectors.base`, `jobwatch.digest`, `jobwatch.models`.

### [tests/test_collectors.py](../../tests/test_collectors.py)

Symbols: `emp` (L9), `test_greenhouse_au_gate_and_fields` (L14), `test_greenhouse_error_recorded_not_raised` (L26), `test_lever` (L33), `test_ashby_strips_tracking_and_gates` (L42), `test_workable` (L51), `test_smartrecruiters_detail_only_for_relevant_titles` (L58), `test_smartrecruiters_skips_detail_for_known` (L70), `test_workday_ambiguous_locations_resolved_by_detail` (L77), `test_pageup_feed` (L97), `test_employmenthero` (L108), `test_scouttalent_index_blocks` (L118), `test_scouttalent_ignores_other_tenants_and_robots` (L128), `test_jsonld_pages_follow_links_and_robots` (L136), `test_jsonld_cap` (L156), `test_rss_generic_and_pageup_format` (L165), `test_reddit_streams_and_privacy` (L182), `test_reddit_stops_when_rate_window_spent` (L204), `test_reddit_search_url` (L214), `test_seek_parse_pages_and_backoff` (L219), `test_seek_respects_robots_when_asked` (L236), `test_jobspy_rows_and_args` (L242), `test_jobspy_error_recorded` (L272), `test_limit_and_rotation` (L279), `test_workday_remembers_non_au_details` (L288), `test_jobspy_site_errors_captured` (L299), `test_failed_sites_do_not_count_as_origins` (L311), `test_techone_jobs_without_an_apply_url_get_distinct_urls` (L325), `test_malformed_xml_employer_does_not_kill_the_others` (L334), `test_rss_malformed_pageup_feed_does_not_kill_the_collector` (L342), `test_successfactors_parse_failure_does_not_keep_validators` (L351).

Local imports: `jobwatch.collectors`.

### [tests/test_confirmed_policy_binding.py](../../tests/test_confirmed_policy_binding.py)

Symbols: `test_confirmation_between_policy_capture_and_key_aborts_before_paid_work` (L7), `test_cached_ready_does_not_survive_confirmation_during_public_recheck` (L28).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.contracts`, `pipeline.agentic.persistence`, `pipeline.schemas`.

### [tests/test_connector_chat.py](../../tests/test_connector_chat.py)

Symbols: `world` (L18), `draft` (L40), `review` (L55), `approval` (L61), `test_direct_onboarding_reads_edits_answers_reviews_and_confirms_without_chat` (L66), `test_confirm_requires_explicit_true_and_exact_draft_and_scope` (L94), `test_scope_configuration_change_invalidates_the_review` (L114), `test_auth_account_isolation_and_removed_chat_routes` (L123).

Local imports: `jobwatch`, `jobwatch.candidate`, `pipeline.agentic`.

### [tests/test_connector_discovery.py](../../tests/test_connector_discovery.py)

Symbols: `test_settings_are_typed_and_bound_to_authenticated_person` (L19), `transport` (L40), `test_discovery_status_and_start_use_authenticated_person_and_person_config` (L67), `test_retry_forwards_only_the_selected_incident_and_context` (L82), `test_discovery_routes_require_authentication_and_refuse_identity_or_budget_overrides` (L92), `test_discovery_schema_rejects_missing_or_wrong_typed_retry_values` (L103), `test_discovery_conflicts_and_safe_refusals_keep_fixed_error_codes` (L116).

Local imports: `jobwatch`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.runtime`.

### [tests/test_connector_http.py](../../tests/test_connector_http.py)

Symbols: `client` (L20), `filled` (L25), `test_bearer_required_everywhere` (L31), `test_refuses_to_start_without_a_long_token` (L38), `test_reads_are_for_the_configured_person_only` (L43), `test_job_detail_never_carries_a_digest` (L50), `test_review_shows_the_exact_form_and_keeps_the_digest_apart` (L55), `test_review_not_ready_has_no_digest_and_no_hash` (L64), `test_review_is_not_ready_after_the_owner_edited_the_form` (L71), `test_submit_needs_digest_and_the_hash_of_what_was_shown` (L79), `test_a_changed_answer_changes_the_shown_hash` (L94), `test_unknown_approval_is_refused` (L105), `_revise_card` (L112), `_approve` (L123), `test_revise_card_shows_a_chat_digest_that_is_not_the_binding` (L129), `test_chat_approval_answers_through_the_widget_binding_once` (L135), `test_chat_approval_refuses_wrong_digest_empty_quote_wrong_posting_and_leaves_it_pending` (L145), `test_chat_approval_can_reject_and_needs_the_bearer_and_the_same_person` (L158), `test_chat_approval_never_reaches_submit_and_expired_approvals_are_gone` (L168), `_no_native_browser` (L178), `FakeLive` (L190), `live` (L227), `_review` (L235), `_submit` (L238), `test_review_shows_the_current_live_form_with_original_file_names` (L243), `test_file_names_are_part_of_the_shown_hash` (L253), `test_old_preparations_without_names_show_the_generic_names` (L261), `test_an_edited_form_is_reviewed_again_and_submit_needs_the_fresh_hash` (L265), `test_an_edit_between_review_and_submit_is_refused_and_queues_nothing` (L282), `test_an_unedited_form_needs_no_rebind` (L287), `test_the_live_form_that_cannot_be_read_is_not_ready` (L291), `test_a_refused_submit_records_no_confirmation_of_an_edited_form` (L299), `test_live_read_and_rebind_run_as_the_configured_person_not_the_default` (L311), `test_preparation_requires_literal_consent_and_exact_typed_inputs` (L323).

Local imports: `jobwatch`, `jobwatch.apply`, `pipeline.agentic`, `pipeline.agentic.runtime`.

### [tests/test_connector_oauth.py](../../tests/test_connector_oauth.py)

Symbols: `make_app` (L25), `state` (L31), `http` (L36), `pkce` (L40), `register` (L45), `login` (L52), `token` (L65), `verify` (L70), `issued` (L74), `test_oauth_is_off_by_default` (L81), `test_oauth_needs_a_public_url_and_a_long_passphrase` (L93), `test_oauth_switch_comes_from_the_environment` (L100), `test_metadata_names_the_public_origin` (L109), `test_full_login_register_authorize_exchange_refresh` (L119), `test_wrong_passphrase_issues_no_code_and_deny_is_access_denied` (L133), `test_too_many_wrong_passphrases_end_the_attempt` (L144), `test_wrong_code_verifier_is_refused_and_burns_nothing_useful` (L154), `test_code_is_single_use` (L160), `test_plain_pkce_and_unregistered_redirects_are_refused` (L167), `test_expired_access_token_is_rejected` (L179), `test_expired_refresh_token_is_rejected` (L187), `test_revoked_tokens_are_rejected` (L195), `test_verify_answers_only_to_the_connector_bearer_and_never_echoes_the_token` (L205), `test_an_oauth_token_does_not_open_the_data_plane` (L216), `test_tokens_survive_a_restart_and_are_not_stored_in_clear` (L222), `test_revocation_and_rotation_are_persisted` (L241), `test_a_damaged_state_file_starts_empty_instead_of_failing_or_trusting_it` (L249), `test_a_loose_state_file_is_not_trusted` (L259), `test_expired_tokens_are_not_kept_on_disk` (L267).

Local imports: `pipeline.agentic`, `pipeline.agentic.runtime`.

### [tests/test_connector_realapp.py](../../tests/test_connector_realapp.py)

Symbols: `app` (L20), `get` (L25), `post` (L29), `test_overview_and_detail_show_the_application` (L33), `test_the_fill_stored_the_original_file_names` (L43), `test_review_submit_second_submit_edit_review_old_hash` (L52), `test_edit_before_submit_is_reviewed_confirmed_and_queued_against_the_fresh_hash` (L93).

Local imports: `jobwatch`, `jobwatch.apply`.

### [tests/test_current_runs.py](../../tests/test_current_runs.py)

Symbols: `evaluated` (L12), `test_current_runs_reuses_stored_evaluation_without_a_model` (L20), `test_closed_postings_never_enter_the_preference_pool` (L31), `test_pool_held_is_explicit_and_opt_in` (L39), `test_profile_change_during_snapshot_is_not_reused` (L50), `test_verification_failure_in_a_stored_artifact_is_not_an_alternative` (L63).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.llm`, `jobwatch.preferences`, `pipeline.agentic`.

### [tests/test_db_maintenance.py](../../tests/test_db_maintenance.py)

Symbols: `_posting` (L13), `_application` (L21), `_ids` (L27), `test_prune_keeps_postings_with_applications_or_requirements` (L31), `test_prune_never_raises_on_database_errors` (L42), `test_prune_keeps_recent_and_matched` (L54), `_raw_at` (L67), `test_migrate_crash_mid_migration_leaves_previous_version` (L80), `test_migrate_two_starters_do_not_both_run_it` (L115), `test_migrate_waits_for_a_lock_held_by_another_starter` (L140), `test_migrate_statement_splitter_handles_comments_and_triggers` (L152).

Local imports: `jobwatch`, `jobwatch.models`.

### [tests/test_dedupe.py](../../tests/test_dedupe.py)

Symbols: `P` (L6), `test_url_then_key_dedupe` (L10), `test_key_window` (L33), `test_same_source_distinct_requisitions_are_not_merged` (L41), `test_key_normalisation` (L51), `test_migrations_idempotent_and_wal` (L58).

Local imports: `jobwatch`, `jobwatch.dedupe`, `jobwatch.models`.

### [tests/test_deepagents_runtime.py](../../tests/test_deepagents_runtime.py)

Symbols: `ReadArgs` (L27), `Answer` (L32), `budget` (L38), `role` (L43), `choice` (L50), `transport_llm` (L54), `test_backend_chat_dispatch_synthetic` (L69), `test_chat_receives_owned_upload_references_without_changing_human_words` (L120), `test_native_api_conversation_approval_and_recovery` (L156), `test_recovery_requires_fresh_response_for_later_interrupt` (L293), `test_recovery_before_first_checkpoint_on_existing_thread` (L313), `test_retry_preserves_admission_limits` (L330), `test_mcp_followup_approval_uses_application_identity` (L348), `test_chat_skill_files_are_read_only` (L356), `assert_safe_failure` (L369), `test_one_opted_in_validation_correction_uses_same_budget` (L380), `test_validation_correction_stops_after_second_invalid_response` (L392), `test_opted_in_correction_never_retries_nonvalidation_failures` (L402), `test_one_transient_provider_error_is_retried_once` (L408), `test_validation_correction_cannot_renew_turn_limit` (L418), `test_validation_correction_retains_failed_reservation_when_budget_runs_out` (L424), `test_validation_correction_cannot_renew_deadline` (L431), `test_invalid_tool_is_never_executed_during_correction` (L441), `test_validation_correction_cannot_reset_existing_failure_limit` (L449), `test_correction_is_once_per_role_not_once_per_tool` (L457), `test_correction_does_not_retry_a_clipped_response` (L465), `test_correction_limit_configuration_is_strict` (L473), `test_structured_response_timeout_preserves_job_deadline` (L479), `test_actual_deepagent_compiles_invokes_and_selects_native_tools` (L486), `test_nested_strict_contract_tuple_fields_accept_json_without_scalar_coercion` (L523), `test_default_and_unknown_tools_fail_before_execution` (L542), `test_framework_injected_tool_cannot_reach_model_or_execute` (L550), `test_framework_extra_model_call_is_reserved_and_respects_total_turn_limit` (L573), `test_nonterminal_or_wrong_schema_cannot_become_result` (L599), `test_exhausted_turns_and_tokens_never_make_an_extra_transport` (L605), `test_invocation_budget_deferrals_do_not_accumulate_failed_attempts` (L615), `test_cancelled_invocation_does_not_accumulate_failed_attempts` (L632), `test_invocation_call_limit_is_normal_and_never_dispatches_an_extra_call` (L648), `test_environment_tracing_and_inherited_callbacks_are_isolated` (L665), `test_global_debug_and_legacy_tracing_fail_before_private_input` (L689), `test_429_settles_reservation_and_opens_shared_circuit_without_retry` (L701), `test_third_failed_call_still_settles_before_failed_attempt_limit` (L711), `test_reservation_and_dispatch_are_durable_before_each_transport` (L723), `test_late_gateway_result_is_charged_and_never_executes_tool` (L742), `test_invalid_limits_fail_before_transport` (L764), `test_additional_roles_roundtrip_budget_checkpoint` (L771), `test_upstream_overload_503_waits_and_retries_same_call` (L780), `test_upstream_overload_never_falls_back_to_claude` (L789), `_approved_resume` (L804), `test_retry_refuses_an_approval_resume_after_the_interaction_expired` (L815), `test_retry_of_a_fresh_approval_resume_still_works_and_clears_cancel_flag` (L829), `test_graceful_shutdown_leaves_inflight_run_interrupted_and_retryable` (L842), `test_user_cancel_still_finishes_cancelled` (L871), `test_event_stream_never_ends_without_the_terminal_event` (L899), `test_api_health_remains_available_while_polling_blocks` (L943).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`, `pipeline.agentic.contracts`, `pipeline.agentic.execution`, `pipeline.agentic.mcp_server`, `pipeline.agentic.runtime`.

### [tests/test_delayed_posting_details.py](../../tests/test_delayed_posting_details.py)

Symbols: `item` (L5), `test_delayed_primary_source_details_enrich_the_existing_listing` (L9), `test_another_source_cannot_replace_primary_evidence` (L23).

Local imports: `jobwatch`, `jobwatch.dedupe`, `jobwatch.models`.

### [tests/test_discovery_allowance.py](../../tests/test_discovery_allowance.py)

Symbols: `no_public_screen` (L12), `test_daily_assessment_count_ignores_deferrals_and_refreshes_without_erasing_prior_work` (L16), `test_allowance_refusal_is_deferred_without_counting_held_or_processed_jobs` (L32), `test_refreshed_ad_second_pass_allowance_refusal_defers_current_and_tail` (L47).

Local imports: `jobwatch.llm`, `pipeline.agentic`, `pipeline.schemas`.

### [tests/test_discovery_api.py](../../tests/test_discovery_api.py)

Symbols: `api` (L18), `h` (L25), `test_uncached_discovery_is_read_only_and_never_computes` (L28), `test_plan_and_relevance_are_per_person` (L42), `test_capabilities_advertise_discovery` (L60).

Local imports: `jobwatch`, `jobwatch.candidate.policy`, `jobwatch.occupations.plan`, `pipeline`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.discovery`.

### [tests/test_discovery_deadlines.py](../../tests/test_discovery_deadlines.py)

Symbols: `test_expired_invocation_never_ingests_or_charges` (L12), `test_ingestion_elapsed_time_cannot_renew_assessment_deadline` (L22), `test_unstarted_batch_jobs_stay_uncharged_and_unpaused` (L38), `test_paused_job_is_skipped_while_unrelated_job_is_attempted` (L49), `test_collector_budget_does_not_invent_minimum_time` (L67), `test_collector_http_refuses_requests_after_deadline` (L73), `test_ingestion_does_not_start_a_posting_after_deadline` (L81), `test_browser_fallback_receives_the_remaining_invocation_time` (L88), `test_public_extras_stop_at_shared_deadline_without_renewing_timeout` (L97), `test_daily_allowance_caps_resumed_checkpoint_without_new_spending` (L111), `test_cancellation_releases_job_and_preserves_invocation_posting` (L138).

Local imports: `jobwatch`, `jobwatch.http`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.persistence`, `pipeline.agentic.runtime`, `pipeline.nodes`, `pipeline.schemas`.

### [tests/test_discovery_idempotency.py](../../tests/test_discovery_idempotency.py)

Symbols: `test_retry_replay_returns_admitted_run_after_release_and_profile_change` (L14), `test_normal_start_replay_does_not_require_a_still_confirmed_profile` (L38), `test_discovery_admission_remains_atomic_for_concurrent_identical_requests` (L48), `test_retry_setup_failure_after_release_repauses_only_the_selected_job` (L64).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`.

### [tests/test_discovery_incidents.py](../../tests/test_discovery_incidents.py)

Symbols: `conn` (L18), `live_transport` (L23), `test_first_failure_is_visible_paused_and_deduplicated` (L28), `test_normal_deferrals_and_decisions_are_not_failures` (L45), `test_stopped_job_limits_and_actual_runtime_failures_pause_first_attempt` (L54), `test_actual_job_token_limit_is_distinct_from_remaining_daily_allowance` (L61), `test_run_configuration_failures_are_reported_without_pausing_unrelated_jobs` (L79), `test_delivery_retry_is_separate_and_does_not_duplicate_messages` (L85), `test_no_channel_is_reported_without_send` (L105), `test_other_account_never_uses_owners_install_wide_route` (L116), `test_rows_stored_before_generic_wording_read_as_generic` (L130), `test_notification_sender_claim_prevents_concurrent_duplicate` (L143), `test_explicit_release_is_scoped_single_use_and_preserves_incident` (L152), `test_incident_persists_across_restart_and_person_databases_are_isolated` (L167), `test_service_timeout_reconciles_last_phase_once_and_only_matching_unit` (L179), `test_unknown_phase_and_exception_text_are_never_written` (L195), `test_read_only_status_does_not_create_schema` (L202), `test_twenty_one_incidents_in_one_window_send_one_digest_then_next_window_one_more` (L210), `test_same_reason_for_same_job_is_listed_once_in_a_digest` (L233), `test_failed_digest_handoff_keeps_everything_pending_and_delivers_once` (L245), `test_last_successful_phase_is_not_inferred_from_starting_work` (L260), `test_successful_phase_does_not_leak_from_previous_job_in_the_run` (L267), `test_additive_migration_preserves_old_rows` (L275), `activity_rows` (L284), `test_reconcile_old_failure_pauses_once_and_later_normal_outcome_wins` (L291), `test_reconcile_does_not_repause_a_reported_released_failure` (L307), `test_reconcile_without_activity_is_read_only_and_handoffs_are_bounded` (L315).

Local imports: `jobwatch`, `jobwatch.notifier`, `pipeline.agentic`, `pipeline.agentic.runtime`.

### [tests/test_discovery_operations.py](../../tests/test_discovery_operations.py)

Symbols: `world` (L15), `test_discovery_queue_is_idempotent_person_bound_and_not_a_chat` (L32), `test_explicit_retry_rechecks_inputs_and_releases_only_selected_incident` (L44), `test_queued_retry_rejects_changed_profile_without_releasing_pause` (L80), `test_native_api_worker_executes_discovery_without_chat` (L95).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`.

### [tests/test_discovery_partial.py](../../tests/test_discovery_partial.py)

Symbols: `test_outer_deadline_retains_returned_discovery_summary_and_usage` (L13).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`.

### [tests/test_discovery_resume.py](../../tests/test_discovery_resume.py)

Symbols: `test_unstarted_daily_deferral_can_resume_in_fresh_batch_preserving_prior_spend` (L10).

Local imports: `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.persistence`.

### [tests/test_discovery_run_limits.py](../../tests/test_discovery_run_limits.py)

Symbols: `test_invocation_token_refusal_uses_effective_daily_or_run_reason` (L8), `test_batch_budget_reason_defers_current_and_remaining_tail` (L37), `test_run_deferrals_do_not_count_as_assessments_but_keep_all_token_spend` (L51).

Local imports: `pipeline.agentic`, `pipeline.agentic.execution`, `pipeline.agentic.runtime`.

### [tests/test_discovery_settings.py](../../tests/test_discovery_settings.py)

Symbols: `data_dir` (L17), `_confirmed_profile` (L24), `test_default_is_finite_and_inherits_confirmed_scope` (L45), `test_unlimited_setting_is_person_scoped_and_written_privately` (L53), `test_daily_limit_requires_positive_strict_integer` (L64), `test_settings_schema_forbids_extra_fields` (L69), `test_malformed_existing_setting_fails_closed` (L75), `test_allowance_preserves_finite_daily_and_per_run_guards` (L88), `test_user_override_does_not_rewrite_or_bypass_confirmed_profile_digest` (L94), `test_future_confirmation_scope_uses_current_user_setting` (L107), `test_unlimited_embeddings_skip_daily_check_but_keep_per_run_cap` (L121).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.occupations.embeddings`, `pipeline.agentic`.

### [tests/test_discovery_settings_api.py](../../tests/test_discovery_settings_api.py)

Symbols: `test_native_settings_persist_unlimited_without_accepting_client_identity` (L13), `test_queued_retry_refuses_changed_budget_configuration` (L31).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`.

### [tests/test_discovery_shutdown.py](../../tests/test_discovery_shutdown.py)

Symbols: `test_active_discovery_cancellation_retains_posting_after_registry_closes` (L17), `test_cli_outer_exception_marks_registry_failed` (L61).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`.

### [tests/test_document_revisions.py](../../tests/test_document_revisions.py)

Symbols: `test_revision_changes_run_key_and_is_isolated` (L8).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.service`.

### [tests/test_eval_metrics.py](../../tests/test_eval_metrics.py)

Symbols: `replay_cases` (L9), `owner_labels` (L25), `test_exact_missed_suitable_and_precision_with_frozen_rankings` (L29), `test_ndcg_condenses_unlabelled_ranks_and_ideal_includes_unranked_cases` (L48), `test_metrics_require_their_own_applicable_owner_labels` (L66), `test_partial_replay_censors_comparisons_and_excludes_deferred_cases` (L84), `test_unlabelled_diagnostics_keep_citations_conflicts_unknowns_and_usage_separate` (L103), `test_exclusion_comparison_uses_human_labels_separately_from_mandatory_conflicts` (L131), `test_invalid_or_nonhuman_labels_cannot_unlock_quality_metrics` (L145), `test_zero_ideal_and_pending_outcomes_never_manufacture_ranking_quality` (L156), `test_suitability_fallback_uses_binary_gain_not_grade_three` (L172), `test_nonfinite_usage_is_missing_and_label_notes_never_appear` (L181), `test_precision_at_k_stays_comparable_between_arms_of_different_depth` (L193).

Local imports: `pipeline.agentic.eval_metrics`.

### [tests/test_eval_reports.py](../../tests/test_eval_reports.py)

Symbols: `replay_input` (L13), `test_payload_keeps_hashes_counts_and_metrics_but_omits_all_free_text` (L31), `test_report_writes_are_deterministic_private_and_idempotent` (L49), `test_report_projection_drops_nested_text_and_nonfinite_numeric_fields` (L76), `test_unsafe_provenance_is_rejected_without_echoing_input` (L94), `test_invalid_case_identifiers_are_rejected` (L101), `test_private_directory_symlinks_are_refused_without_traversal` (L109), `test_report_file_symlink_is_refused_and_its_target_untouched` (L126), `test_existing_changed_report_is_a_safe_conflict_and_is_never_overwritten` (L142), `test_report_identity_changes_with_provenance_and_labels_hash` (L155), `test_holdout_reports_export_aggregate_metrics_without_case_review` (L167), `test_optional_fit_exports_only_evaluation_metadata` (L181).

Local imports: `jobwatch.reports.evaluation`, `pipeline.agentic.contracts`, `pipeline.agentic.eval_metrics`.

### [tests/test_evaluate_runs.py](../../tests/test_evaluate_runs.py)

Symbols: `prepared` (L10), `test_offline_reproducible_without_live_profile_or_database_writes` (L16), `test_monitor_never_reads_labels_or_holdout_cases` (L29), `test_bounds_and_paid_budget_reject_before_clients` (L41), `test_other_person_cannot_retrieve_frozen_inputs` (L53), `test_relevance_mode_and_judgment_frozen_before_live_changes` (L60), `test_result_tampering_and_holdout_export_audit` (L83), `test_monitoring_maxima_hold_for_a_library_caller_not_only_the_cli` (L98), `test_replay_limits_fit_partition_and_frozen_identity_are_checked` (L110), `test_a_case_that_cannot_be_replayed_is_deferred_with_a_safe_code` (L135).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.policy`, `jobwatch.occupations.plan`, `pipeline.agentic`, `pipeline.agentic.baseline`, `pipeline.agentic.contracts`.

### [tests/test_evaluation_cli.py](../../tests/test_evaluation_cli.py)

Symbols: `test_cli_freeze_split_replay_monitor_report` (L8), `test_terminal_labels_and_explicit_holdout` (L29), `test_legacy_show_audits_before_any_split_case_reads` (L44).

Local imports: `jobwatch`, `pipeline.agentic`.

### [tests/test_evaluation_data.py](../../tests/test_evaluation_data.py)

Symbols: `test_write_once_grouped_split_and_selected_loading` (L10), `test_context_and_profile_tampering_refused` (L33), `test_holdout_access_is_audited_before_cases` (L44), `test_single_group_has_explicit_split_unavailable` (L54), `test_detected_cross_split_leakage_refused_even_with_valid_checksum` (L60), `test_private_directory_symlink_refused` (L77), `test_config_drift_rejects_staging_before_publication` (L87), `test_freezing_cannot_write_through_a_writable_connection` (L100), `test_a_baseline_frozen_before_phase_7_is_unavailable_not_corrupt` (L120), `test_split_seed_partition_and_person_are_validated` (L138), `test_write_once_refuses_a_divergent_rewrite` (L159).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `pipeline.agentic`, `pipeline.agentic.contracts`.

### [tests/test_evaluation_optional.py](../../tests/test_evaluation_optional.py)

Symbols: `test_paid_replay_uses_actual_canonical_runtime_and_budget` (L9), `test_explicit_fit_insufficient_data_never_starts_sampler` (L27), `test_fit_uses_canonical_gates_and_preserves_original_choices` (L35), `test_frozen_choices_skip_holdout_without_opening_choice_and_keep_originals` (L59).

Local imports: `jobwatch`, `jobwatch.llm`, `jobwatch.preferences`, `jobwatch.preferences.model`, `pipeline.agentic`, `pipeline.agentic.service`.

### [tests/test_evidence_yaml_once.py](../../tests/test_evidence_yaml_once.py)

Symbols: `test_profile_yaml_is_parsed_once_per_extraction` (L4).

Local imports: `jobwatch.candidate`.

### [tests/test_expiry.py](../../tests/test_expiry.py)

Symbols: `_posting` (L9), `_closed_at` (L15), `test_live_check_clears_closed_at` (L19), `test_unreadable_check_keeps_closed_at` (L28), `_relist` (L36), `_due` (L41), `test_a_relisted_closed_ad_stays_closed_until_a_live_check_finds_it_open` (L48).

Local imports: `jobwatch`, `jobwatch.dedupe`, `jobwatch.models`.

### [tests/test_feedback.py](../../tests/test_feedback.py)

Symbols: `conn` (L13), `shortlisted` (L20), `reject` (L26), `test_vocabulary_keeps_taste_eligibility_and_data_quality_distinct` (L33), `test_rejection_replay_and_restore_preserve_human_history` (L43), `test_reject_binds_current_entry_and_replay_binds_exact_payload` (L76), `test_restore_binds_latest_active_rejection_and_never_replays_state` (L96), `test_restore_of_closed_posting_does_not_revive_old_snapshot` (L115), `test_actor_must_be_person` (L127), `test_invalid_lifecycle_inputs_leave_no_event` (L141), `test_append_helper_is_atomic_with_caller_and_person_scoped` (L150), `test_other_domain_events_retain_payload_and_never_commit` (L172), `test_append_validation_is_typed_and_preserves_caller_transaction` (L193), `test_append_accepts_a_canonical_domain_request_hash` (L203), `test_shared_connection_dismissals_never_cross_people` (L217), `test_public_mutation_cannot_commit_caller_transaction` (L238), `test_history_limit_is_bounded` (L248), `test_read_helpers_do_not_create_schema` (L253).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `pipeline.agentic`.

### [tests/test_feedback_api.py](../../tests/test_feedback_api.py)

Symbols: `headers` (L12), `client` (L17), `test_reject_restore_history_scopes_and_immediate_shortlist` (L27), `test_rule_confirmation_stales_evaluations_without_model_calls` (L48), `test_native_selection_persists_pending_identity_retry_and_cancellation` (L62), `test_current_prompt_get_reports_stale_without_writing_or_offering_old_profile_questions` (L91).

Local imports: `jobwatch`, `jobwatch.candidate`, `pipeline.agentic`, `pipeline.agentic.api`.

### [tests/test_feedback_chat.py](../../tests/test_feedback_chat.py)

Symbols: `prepared` (L14), `test_model_rejection_waits_for_exact_human_confirmation` (L32), `test_selected_chat_job_is_durable_preparation_only` (L52), `test_model_generated_question_answer_cannot_become_human_feedback` (L66), `test_chat_exclusion_proposal_with_omitted_defaults_uses_exact_human_binding` (L79).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.runtime`, `pipeline.agentic.service`.

### [tests/test_feedback_migration.py](../../tests/test_feedback_migration.py)

Symbols: `test_feedback_storage_is_available_and_migration_is_repeatable` (L5).

Local imports: `jobwatch`.

### [tests/test_feedback_prompts.py](../../tests/test_feedback_prompts.py)

Symbols: `test_identical_profiles_have_distinct_person_contexts_and_shared_db_sets` (L12), `prompts` (L34), `next_prompt` (L61), `accepted_fit` (L65), `test_information_gain_and_probabilities_match_canonical_prediction` (L76), `test_cold_start_is_deterministic_with_no_invented_differences` (L99), `test_next_comparison_is_unpaid_current_and_reuses_one_open_prompt` (L113), `test_comparison_pick_is_canonical_exact_and_idempotent` (L131), `test_none_is_a_genuine_choice_and_invalid_option_is_not` (L152), `test_stale_comparison_closes_without_recording_a_choice` (L166), `test_pick_crash_recovery_finalizes_an_existing_exact_pick_even_if_now_stale` (L187), `test_set_creation_crash_recovers_the_same_reserved_prompt` (L210), `test_question_answer_preserves_words_without_profile_amendment` (L227), `test_questions_prefer_profile_then_shared_uncertainty_and_cool_down` (L244), `test_weekly_cap_counts_dismissed_prompts_and_settings_can_disable` (L266), `test_prompt_and_choice_visibility_is_person_bound_on_shared_connection` (L283), `test_human_writes_require_the_person` (L300), `test_rejected_jobs_and_previous_sets_are_not_offered` (L306), `test_valid_posterior_is_used_and_malformed_or_wrong_profile_falls_back` (L320), `test_question_can_preserve_four_thousand_human_characters` (L343), `test_stale_question_cannot_become_a_profile_fact_or_feedback` (L356), `test_large_pool_still_uses_only_the_nine_newest_unseen` (L370), `test_malformed_posterior_falls_back_after_canonical_validation` (L380), `test_information_gain_never_uses_more_than_one_thousand_draws` (L391), `test_prompt_reads_and_no_profile_issuance_never_create_schema` (L407), `test_invalid_prompt_configuration_is_refused` (L425), `test_request_ids_cannot_cross_pending_prompt_responses` (L433), `test_real_frozen_pool_and_question_round_trip_without_model_calls` (L449), `test_concurrent_issuance_keeps_one_durable_prompt_and_set` (L471).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.contracts`, `jobwatch.preferences`, `jobwatch.preferences.features`, `jobwatch.preferences.model`, `pipeline.agentic`.

### [tests/test_feedback_shortlist.py](../../tests/test_feedback_shortlist.py)

Symbols: `test_rejection_and_restoration_require_new_current_snapshots` (L6).

Local imports: `pipeline.agentic`.

### [tests/test_fetch_loop.py](../../tests/test_fetch_loop.py)

Symbols: `Gateway` (L34), `world` (L55), `llm_of` (L84), `use` (L88), `review` (L94), `age_fetch_log` (L98), `test_ad_fetch_table_exists_and_follows_its_posting` (L105), `test_dead_ads_are_requested_once_not_on_every_run` (L113), `test_a_failed_ad_is_retried_after_24_hours_and_at_most_three_times` (L133), `test_a_good_fetch_is_stored_in_ad_text_and_never_repeated` (L152), `test_fetch_due_rules` (L164), `test_connection_errors_count_against_the_budget_are_paced_and_stop_the_host` (L177), `test_a_timeout_or_any_exception_is_handled_like_a_failed_fetch` (L196), `test_failures_spend_the_fetch_budget_and_pace_like_a_normal_fetch` (L207), `test_a_block_status_stops_the_host_at_once_but_is_counted_and_paced` (L217), `test_a_good_fetch_resets_the_run_of_failures` (L230), `test_a_200_challenge_page_is_a_failure_and_three_stop_the_host` (L245), `test_ads_the_reader_cannot_fetch_do_not_use_the_budget` (L264), `test_a_cut_description_is_fetched_and_a_cut_one_without_a_fetcher_is_partial` (L274), `test_every_exception_for_one_posting_is_caught` (L288), `test_a_crashing_model_call_for_one_ad_does_not_stop_the_others` (L319), `test_review_pending_stops_starting_work_after_max_seconds` (L335), `test_a_spent_budget_starts_nothing` (L346), `test_no_limit_by_default_for_the_cli` (L355), `test_after_collect_passes_the_configured_budget_down` (L361), `test_after_collect_stops_recall_between_batches_and_skips_the_review` (L377), `test_review_lock_is_exclusive_and_released` (L392), `test_lock_file_sits_next_to_the_database` (L402), `test_a_second_pipeline_hook_skips_quietly_while_the_first_runs` (L406), `_args` (L419), `test_cli_review_and_recall_skip_while_another_run_holds_the_lock` (L425), `_pipeline_world` (L443), `test_pipeline_runs_the_ai_step_last_so_a_timeout_cannot_cost_publish_and_prune` (L453), `test_pipeline_survives_a_crashing_ai_step` (L461), `test_rederive_and_review_pending_agree_on_full_partial_and_teaser` (L475), `test_rederive_holds_an_old_cut_review_that_was_labelled_full` (L497), `job` (L512), `test_a_job_url_named_by_the_page_is_dropped_unless_it_is_on_the_employers_site` (L521), `test_a_job_url_on_the_employers_site_is_kept_and_its_hosts_are_recorded` (L526), `test_a_page_cannot_widen_its_own_recorded_hosts` (L536), `test_listing_page_job_with_a_foreign_url_gets_no_shared_page_url` (L542), `test_the_stored_hosts_gate_the_reader_fetch_for_a_jsonld_row` (L547), `test_detail_links_refuse_backslash_userinfo_odd_ports_and_other_hosts` (L569), `test_postings_a_fetcher_would_refuse_cost_no_slot_pause_or_logged_try` (L576), `test_a_refused_ad_does_not_crowd_real_ads_out_of_the_budget` (L595), `_exhaust_log` (L609), `test_pipeline_runs_keep_the_cap_but_posting_and_refetch_bypass_it` (L614), `test_refetch_bypasses_the_24h_wait_and_the_try_cap_for_pending_ads` (L626), `test_cli_refetch_flag_reaches_review_pending` (L643), `test_cli_rederive_exits_1_without_touching_rows_while_a_review_runs` (L654), `test_review_stats_and_printer_count_partial_like_teaser` (L672), `test_ai_budget_is_what_is_left_of_the_unit_time` (L688), `test_pipeline_hands_the_ai_step_the_remaining_time_and_records_the_run_even_if_it_dies` (L698), `test_after_collect_gives_recall_its_remaining_time_when_recall_accepts_it` (L715), `test_a_jsonld_row_without_its_own_host_list_is_fetched_only_from_registry_hosts` (L729), `test_a_job_url_differing_from_the_careers_host_only_by_www_is_kept` (L754), `test_detail_links_treat_www_as_the_same_site_in_both_directions` (L762), `test_a_hostile_href_loses_only_itself_not_the_employer` (L773), `test_jobs_search_list_uses_the_same_plain_host_check` (L782), `_stuck_indeed` (L797), `test_ads_that_cannot_be_read_again_do_not_use_the_limit` (L803), `test_the_limit_still_stops_after_that_many_ads_that_need_a_model_call` (L818), `_Clock` (L827), `_timed_gateway` (L835), `test_each_attempt_waits_at_most_what_is_left_but_at_least_ten_seconds` (L853), `test_no_deadline_keeps_the_old_180_second_timeout` (L862), `test_no_second_attempt_when_less_than_thirty_seconds_are_left` (L868), `test_a_review_run_hands_every_model_call_its_remaining_budget` (L880), `test_after_collect_passes_the_unit_budget_down_to_the_model_calls` (L896), `test_redo_with_posting_refetches_only_the_named_ads` (L908), `test_a_run_that_crashes_records_the_error_class_and_still_finishes` (L922), `test_a_clean_run_has_no_error_field` (L938), `test_pipeline_gate_skips_every_tier_without_a_confirmed_profile` (L944).

Local imports: `jobwatch`, `jobwatch.collectors`, `jobwatch.dedupe`, `jobwatch.llm`, `jobwatch.models`, `pipeline.agentic`, `pipeline.graph`.

### [tests/test_fieldgen.py](../../tests/test_fieldgen.py)

Symbols: `test_nurse_config` (L9), `test_generated_rules_do_not_read_a_national_title_as_remote` (L21), `test_generated_rules_do_not_invent_seniority_experience_or_remote_constraints` (L34), `test_generated_rules_preserve_only_stated_exclusions_and_remote_preference` (L49).

Local imports: `jobwatch`, `jobwatch.config`, `jobwatch.filters`, `jobwatch.models`.

### [tests/test_filters.py](../../tests/test_filters.py)

Symbols: `rules` (L11), `P` (L15), `test_every_arm_matches` (L38), `test_switched_off_shop_and_hospitality_arms_do_not_match` (L46), `test_an_arm_with_enabled_false_is_not_loaded` (L51), `test_excludes` (L72), `test_team_member_no_longer_matches_now_the_shop_arms_are_off` (L77), `test_location_rules` (L82), `test_it_administrator_exclude_needs_a_word_boundary` (L93), `test_it_administrators_still_excluded` (L98), `test_national_in_a_title_is_not_remote` (L102), `test_vic_patterns_ignore_other_places` (L110), `test_vic_patterns_still_match_victoria` (L115), `test_experience_exclude_and_flag` (L119), `test_flags` (L125), `test_multiple_arms_recorded` (L138), `test_title_relevant` (L143), `test_t9_false_positives_not_matched` (L155), `test_t9_true_positives_still_match` (L163), `test_national_as_a_location_is_remote` (L169), `test_the_vic_location_rule_agrees_with_state_of` (L177).

Local imports: `jobwatch.filters`, `jobwatch.models`.

### [tests/test_followup_cadence.py](../../tests/test_followup_cadence.py)

Symbols: `history` (L8), `test_applied_reminder_boundary_and_no_draft_submission_inference` (L12), `test_sent_followup_restarts_clock_and_two_unanswered_become_cold` (L19), `test_reply_resets_unanswered_streak_without_erasing_history` (L27), `test_interview_status_is_not_evidence_that_interview_happened` (L34), `test_pin_overrides_cold_until_later_send_and_terminal_always_wins` (L41), `test_unknown_or_future_activity_never_produces_fabricated_overdue_state` (L50), `test_followup_after_reply_uses_three_day_cadence` (L56), `test_same_day_reply_and_sent_order_requires_event_time_before_scheduling` (L62).

Local imports: `jobwatch.followups`.

### [tests/test_followup_draft.py](../../tests/test_followup_draft.py)

Symbols: `Writer` (L15), `Reviewer` (L31), `case` (L46), `compose` (L54), `test_real_deepagents_tools_and_independent_hash_bound_review` (L59), `test_invalid_proof_or_review_never_returns_approved_draft` (L73), `test_one_revision_is_reviewed_again_and_bounded` (L79), `test_repeated_revision_holds_instead_of_returning_unreviewed_text` (L87), `test_linkedin_length_limit_is_enforced_before_review` (L92).

Local imports: `jobwatch`, `jobwatch.candidate.evidence`, `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.followup`, `pipeline.agentic.runtime`.

### [tests/test_followup_draft_service.py](../../tests/test_followup_draft_service.py)

Symbols: `setup` (L19), `test_ready_draft_is_private_durable_cached_and_never_sent` (L29), `test_new_owner_history_and_changed_profile_invalidate_old_draft` (L43), `test_terminal_and_not_due_state_refuse_before_any_model_call` (L50), `test_unknown_failed_dispatch_retains_reservation_and_does_not_auto_retry` (L58), `test_profile_change_during_generation_prevents_ready_publication` (L76), `test_explicit_retry_preserves_unknown_charges_and_original_ceiling` (L90), `test_explicit_retry_keeps_failure_limit_and_cannot_dispatch_forever` (L110), `test_expired_attempt_renews_time_but_preserves_budget` (L126), `test_late_worker_cannot_overwrite_explicit_takeover` (L146), `test_stricter_batch_limit_prevents_dispatch` (L168).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.evidence`, `jobwatch.config`, `jobwatch.followup_drafts`, `jobwatch.followup_events`, `pipeline.agentic.contracts`, `pipeline.agentic.runtime`.

### [tests/test_followup_events.py](../../tests/test_followup_events.py)

Symbols: `conn` (L13), `record` (L23), `confirm_application` (L27), `test_missing_confirmation_and_notes` (L31), `test_same_day_reply_then_send_and_send_then_reply` (L39), `test_idempotency_conflict_owner_confirmation_and_ledger_replay` (L49), `test_pin_order_uses_recorded_time_and_terminal_state_suppresses` (L62), `test_reject_future_and_naive_events_and_pre_application_dates` (L76), `test_scheduled_interview_requires_completion_event` (L82), `test_same_day_pin_after_send_remains_active` (L90), `test_exact_time_pre_submission_send_is_rejected` (L97), `test_untrusted_jobwatch_events_and_drafts_never_count_as_sent` (L103), `test_concurrent_repeated_owner_action_has_one_event` (L111), `test_application_date_correction_cannot_move_after_confirmed_communication` (L125).

Local imports: `jobwatch`, `jobwatch.followup_events`.

### [tests/test_gate_holds.py](../../tests/test_gate_holds.py)

Symbols: `facts` (L8), `score` (L17), `confirmed_restricted_rights` (L26), `check` (L35), `test_aps_grade_alone_does_not_prove_a_citizenship_requirement` (L42), `test_without_restriction_quote_is_corroborated_by_rule` (L46), `test_split_full_rights_quote_is_verified` (L51), `test_only_allowlisted_split_words_can_verify` (L61), `test_split_keyword_after_single_letter_article_is_verified` (L73), `test_absent_split_keyword_quote_after_article_stays_unverified` (L79), `test_non_keyword_split_letter_stays_unverified` (L85), `test_unverified_rights_are_not_hidden_by_model_taste_or_shared_caps` (L94), `test_unverified_otherwise_passing_job_stays_review` (L98), `test_full_time_program_does_not_bypass_hold` (L102), `test_citizen_pr_or_graduate_visa_disagreement_stays_review` (L107), `test_absent_quote_cannot_be_corroborated` (L113), `test_present_nonblocking_quote_cannot_use_rule_in_different_sentence` (L118), `test_verified_and_rule_only_archives_keep_precedence` (L127), `test_unknown_rights_are_not_replaced_by_unconfirmed_personal_preferences` (L132), `test_not_real_job_keeps_first_precedence` (L137).

Local imports: `jobwatch.candidate.policy`, `pipeline.nodes.gate`, `pipeline.schemas`.

### [tests/test_google_oauth.py](../../tests/test_google_oauth.py)

Symbols: `env` (L12), `test_consent_url_scopes_no_send` (L19), `test_missing_env_raises` (L28), `test_token_file_0600_with_mock` (L35), `test_state_tamper_rejected` (L49).

Local imports: `jobwatch`.

### [tests/test_interview_ad.py](../../tests/test_interview_ad.py)

Symbols: `Fetcher` (L8), `test_structured_providers_keep_complete_identified_ad` (L20), `test_missing_or_mismatched_content_requires_browser` (L34), `test_closed_record_requires_pasted_jd` (L38), `test_oversize_is_rejected_not_truncated` (L42), `test_unknown_host_never_uses_structured_network` (L46), `test_invalid_url_cannot_change_endpoint` (L52), `test_provider_error_is_fixed_unavailable_not_page_text` (L55), `test_workday_rejects_missing_or_mismatched_role_identity` (L63), `test_escaped_literal_source_text_is_preserved` (L71), `test_oracle_closed_workday_403_and_extra_json` (L79), `test_oracle_empty_result_means_closed` (L87).

Local imports: `jobwatch.interview_ad`, `jobwatch.llm`, `pipeline.agentic.research`.

### [tests/test_interview_browser.py](../../tests/test_interview_browser.py)

Symbols: `Fetcher` (L10), `snapshot` (L17), `test_saved_seek_job_reads_official_mirror_with_chrome_fetch` (L20), `test_seek_alias_scope_excludes_non_public_job_urls` (L47), `test_explicit_past_closing_date_rejects_still_visible_ad` (L60), `test_date_only_closing_day_remains_open_until_melbourne_day_ends` (L65), `test_invalid_or_conflicting_deadlines_hold_instead_of_claiming_active` (L73), `test_future_duplicate_and_unrelated_dates_remain_readable` (L84), `test_uncertain_deadline_cannot_fall_back_to_stale_structured_ad` (L95), `test_real_chromium_rejects_visible_expired_deadline` (L104), `test_unusable_pages_never_become_preparation` (L117), `test_a_real_ad_that_mentions_a_security_check_is_not_a_block_page` (L121), `Request` (L130), `Route` (L132), `test_browser_transport_blocks_nonread_actions_and_exhaustion` (L138), `test_http_fallback_requires_matching_structured_job_and_labels_unconfirmed` (L148), `test_closed_browser_never_falls_through_to_stale_http` (L158), `test_real_chromium_reads_visible_whole_ad_and_excludes_navigation` (L164), `test_acquisition_prefers_structured_record_without_starting_browser` (L172), `test_unavailable_browser_uses_explicitly_unconfirmed_fallback` (L179), `test_visible_closure_outside_ad_root_is_terminal` (L188), `test_readable_ad_with_form_captcha_is_not_a_blocked_page` (L192), `test_real_chromium_checks_status_banner_outside_main` (L196), `test_browser_preserves_upstream_charset` (L200), `test_transport_does_not_relabel_xhr_as_json` (L208), `test_explicit_document_status_is_closed_only_for_missing_or_gone` (L218), `test_missing_subresource_does_not_close_the_posting` (L227), `test_real_browser_404_produces_closed_and_never_http_fallback` (L236), `test_real_chromium_uses_visible_job_heading_not_hidden_other_job` (L246), `test_default_public_browser_bounds_required_large_ats_script` (L256), `test_close_label_with_no_date_states_no_deadline` (L281), `test_same_host_redirect_is_handed_to_the_browser_other_hosts_are_not` (L290), `test_unreadable_backoff_after_three_same_failures` (L306), `test_pageup_redirect_for_a_gone_vacancy_is_closed` (L326), `test_closing_date_with_of_between_day_and_month` (L338), `test_closing_date_with_time_and_melbourne_zone` (L349), `test_closing_date_with_trailing_slogan_jora` (L360).

Local imports: `jobwatch`, `jobwatch.interview_ad`, `jobwatch.interview_browser`, `jobwatch.models`, `pipeline.agentic.research`, `pipeline.agentic.service`, `pipeline.agentic.store`.

### [tests/test_interview_inputs.py](../../tests/test_interview_inputs.py)

Symbols: `conn` (L9), `test_optional_inputs_do_not_create_or_change_application` (L18), `test_inputs_replay_and_retention_preserve_prep_without_application` (L27), `test_stale_tabs_cannot_replace_newer_owner_inputs` (L35), `test_invalid_ids_and_metadata_fail_without_rows` (L42), `test_malformed_private_record_has_fixed_error` (L49), `test_unchecked_model_copy_cannot_bypass_input_limits` (L55), `test_ledger_failure_rolls_back_owner_edit` (L62), `test_separate_connections_reject_stale_revision` (L70), `test_aggregate_limit_and_unknown_fields_cannot_be_persisted` (L82).

Local imports: `jobwatch`, `jobwatch.interview_inputs`, `pipeline.agentic.contracts`.

### [tests/test_interview_prep.py](../../tests/test_interview_prep.py)

Symbols: `proposal` (L17), `Writer` (L46), `Reviewer` (L60), `case` (L75), `prepare` (L81), `test_real_deep_agents_tools_independent_review_and_roundtrip` (L86), `test_failure_never_publishes` (L100), `test_one_bounded_revision` (L106), `test_repeated_revision_fails` (L113), `test_optional_inputs_captured_and_source_changes_rejected` (L118), `test_full_coverage_and_technical_cap` (L128), `test_primary_candidate_proof_and_invite_modality` (L137), `test_deeply_immutable_report` (L155), `test_public_tools_expose_only_fixed_intents_and_preserve_snapshots` (L161), `test_grounded_result_first_answer` (L201), `test_source_metadata_is_bound_to_independent_review` (L217), `test_all_unknown_report_rejected_before_shallow_approval` (L225), `test_primary_answer_required_even_when_questions_present` (L232), `test_each_main_audience_requires_a_grounded_question` (L243), `owner_logistics_payload` (L254), `test_explicit_owner_logistics_answer_accepted` (L272), `test_owner_fact_cannot_ground_experience_answer` (L278), `test_owner_fact_cannot_replace_primary_answer_minimum` (L289).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `jobwatch.candidate.evidence`, `jobwatch.settings`, `pipeline.agentic.contracts`, `pipeline.agentic.interview`, `pipeline.agentic.research`, `pipeline.agentic.runtime`.

### [tests/test_interview_service.py](../../tests/test_interview_service.py)

Symbols: `world` (L19), `writer_for` (L29), `test_ready_prep_without_application_is_durable_and_cached` (L32), `test_changed_owner_inputs_hide_prior_report` (L44), `test_unknown_dispatch_is_not_automatically_retried_and_charge_survives_recovery` (L51), `test_changed_profile_during_generation_prevents_publication` (L72), `test_late_worker_cannot_settle_or_publish_after_takeover` (L85), `test_auto_trigger_requires_interview_current_evaluation_and_no_attempt` (L107), `test_missing_evaluation_does_not_start_automatic_work` (L122), `test_stricter_batch_limit_prevents_dispatch` (L128), `test_queued_request_is_durable_and_only_undispatched_work_recovers` (L135), `test_source_change_before_worker_never_dispatches_unrequested_snapshot` (L147), `test_committed_interview_transition_is_recovered_without_repeating_after_input_change` (L158).

Local imports: `jobwatch`, `jobwatch.apply.paths`, `jobwatch.candidate.evidence`, `jobwatch.config`, `jobwatch.interview_inputs`, `jobwatch.interview_prep`, `pipeline.agentic.contracts`.

### [tests/test_interview_subject_service.py](../../tests/test_interview_subject_service.py)

Symbols: `subject` (L15), `test_subject_uses_existing_runtime_without_tracker_changes` (L17), `test_subject_queue_durable_and_changed_notes_do_not_auto_dispatch` (L32), `test_subject_unknown_call_is_not_retried_and_budget_stays_reserved` (L44), `test_matching_report_requires_current_ad_and_profile` (L58).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `jobwatch.interview_ad`, `jobwatch.interview_inputs`, `jobwatch.interview_prep`, `jobwatch.interview_subjects`, `pipeline.agentic.contracts`.

### [tests/test_interview_subjects.py](../../tests/test_interview_subjects.py)

Symbols: `conn` (L14), `ad` (L22), `test_source_and_report_reference_survive_reindex_without_tracker_rows` (L28), `test_stale_save_across_connections` (L44), `test_duplicate_reuses_original_source_and_preserves_owner_notes` (L58), `test_invalid_ad_does_not_write_or_leak` (L80), `test_invalid_inputs_and_revision_cannot_change_subject` (L88), `test_corrupt_record_fixed_error` (L100), `test_ledger_failure_rolls_back_create_and_save` (L112), `test_supported_acquisitions_preserved` (L124), `test_v10_upgrade_creates_replayable_subject_tables` (L129), `test_missing_subject_and_active_transaction_leave_state_untouched` (L142), `test_legacy_ad_without_expiry_loads_and_reuses_saved_notes` (L152), `test_optional_ad_expiry_round_trips` (L162), `test_invalid_ad_expiry_rejected_without_write` (L168).

Local imports: `jobwatch`, `jobwatch.interview_ad`, `jobwatch.interview_inputs`, `jobwatch.interview_subjects`, `pipeline.agentic.contracts`.

### [tests/test_jev_skills.py](../../tests/test_jev_skills.py)

Symbols: `test_only_career_facts_reach_jev_and_name_is_masked` (L7), `test_claim_check_drops_only_unsupported_lines` (L20), `test_work_rights_requirements_are_not_mapped` (L33).

Local imports: `pipeline.agentic.draft`, `pipeline.agentic.jev_skills`.

### [tests/test_jora.py](../../tests/test_jora.py)

Symbols: `test_parse_cards` (L9), `test_posted_from` (L18), `test_collect_truncates_to_limit` (L25).

Local imports: `jobwatch.collectors`.

### [tests/test_langgraph_entry.py](../../tests/test_langgraph_entry.py)

Symbols: `test_fake_graph_answers_without_a_model` (L4), `test_private_boundary_runs_async_tool_calls_in_person_scope` (L13), `_server_graph` (L29), `test_server_path_submit_interrupts_and_approve_never_runs_it` (L36), `test_server_path_prepare_application_interrupts` (L53).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.langgraph_entry`, `pipeline.agentic.runtime`.

### [tests/test_legacy_too_senior.py](../../tests/test_legacy_too_senior.py)

Symbols: `setup_db` (L14), `snapshot` (L25), `test_roundtrip_and_only_column_changed` (L29), `test_count_guard` (L46), `test_invalid_or_named_excluded` (L57), `test_pipeline_precedence` (L65), `test_concurrent_drift_aborts` (L72), `test_rollback_refuses_drift_and_wrong_database` (L86), `test_trigger_and_existing_backup_refused` (L99), `test_transaction_failure_is_atomic` (L113), `test_cli_dry_run_and_explicit_offline_gate` (L124), `test_aggregate_zero_with_compatibility_and_unrelated_unchanged` (L137).

Local imports: `jobwatch`, `jobwatch.web`, `pipeline`.

### [tests/test_librechat.py](../../tests/test_librechat.py)

Symbols: `client` (L19), `headers` (L41), `turn` (L45), `attached` (L50), `test_standard_files_receive_originals_without_a_frontend_bridge` (L55), `test_zip_and_unreadable_files_do_not_break_normal_chat` (L67), `test_unreadable_file_only_turns_are_received_without_running_contents` (L84), `test_standard_file_larger_than_old_json_cap_is_received` (L108), `test_prior_originals_do_not_consume_the_new_turn_attachment_allowance` (L115), `test_file_urls_and_bad_base64_cannot_fetch_or_enqueue` (L126), `test_artifact_mode_never_emits_jobwatch_card_calls` (L136), `test_native_attachment_references_survive_enqueue_and_worker` (L145), `test_attachment_references_do_not_allow_nontext_or_assistant_turns` (L174), `test_new_attachment_during_pending_approval_is_explicitly_refused` (L185), `test_durable_identity_retry_and_stream` (L195), `test_model_text_and_chat_key_cannot_approve` (L214), `test_questions_use_the_same_protected_resume` (L239), `test_no_client_identity_or_system_instruction_replay` (L249), `test_controls_are_static_and_do_not_embed_credentials` (L263), `test_adapter_is_explicitly_enabled` (L273), `test_inline_tool_and_continuation_do_not_repeat_paid_work` (L283), `test_inline_view_is_emitted_while_native_work_is_running` (L309), `test_reviewed_submit_uses_native_approval_resume_without_stranding_thread` (L330), `test_top_selector_catalog_and_only_saved_model_is_accepted` (L354), `test_model_snapshot_preserves_role_overrides_without_reloading_config` (L372), `test_genui_waits_for_answer_without_mounting_dashboard` (L384), `test_genui_keeps_native_approval_and_question_boundary` (L396), `test_genui_guidance_keeps_routine_questions_in_plain_chat` (L409).

Local imports: `jobwatch`, `jobwatch.candidate`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.chat`, `pipeline.agentic.client_api`, `pipeline.agentic.genui`, `pipeline.agentic.mcp_app`.

### [tests/test_librechat_identity.py](../../tests/test_librechat_identity.py)

Symbols: `setup` (L8), `enroll` (L13), `test_trusted_enrollment_preserves_owner_and_isolates_friends` (L16), `test_concurrent_enrollment_is_idempotent_and_does_not_accept_identity_fields` (L30), `test_standard_endpoint_binds_trusted_client_subject_without_human_scope` (L39), `test_trusted_chat_confirmation_cannot_approve_an_application_submit` (L54).

Local imports: `pipeline.agentic.api`.

### [tests/test_live_legacy_procedure.py](../../tests/test_live_legacy_procedure.py)

Symbols: `test_three_roundtrip_and_durable_backup` (L10), `test_any_changed_data_aborts` (L25), `test_failure_after_update_rolls_back` (L40), `test_directory_fsync_failure_prevents_update` (L50), `test_cli_without_approval_never_opens_writer` (L60), `test_manifest_identity_and_count_guards` (L76), `test_rollback_refuses_unrelated_drift` (L82).

### [tests/test_localities.py](../../tests/test_localities.py)

Symbols: `_p` (L9), `test_vic_unique_suburb_passes` (L14), `test_other_state_named_blocks_locality` (L18), `test_ambiguous_name_alone_is_not_enough` (L23).

Local imports: `jobwatch.filters`, `jobwatch.models`.

### [tests/test_location_policy.py](../../tests/test_location_policy.py)

Symbols: `test_regions_named` (L16), `test_location_verdict` (L26), `test_commute_km_for_uses_victorian_data_only` (L30), `test_commute_km_for_withholds_distance_when_another_state_is_named` (L39), `test_existing_location_reference_hash_is_unchanged` (L45).

Local imports: `pipeline.agentic`, `pipeline.agentic.location`.

### [tests/test_mcp_app.py](../../tests/test_mcp_app.py)

Symbols: `native` (L21), `bearer` (L30), `test_upload_exact_bytes_scope_replay_and_native_cap` (L33), `test_ticket_upload_accepts_native_ten_mib_boundary` (L60), `rpc` (L70), `test_actual_mcp_http_auth_resource_and_app_only_scope` (L80), `test_simple_browser_upload_binds_capability_without_preflight` (L113), `test_panel_follows_canonical_selection_when_child_is_dispatched` (L127), `test_focused_card_kinds_are_fixed_and_reopening_is_read_only` (L157).

Local imports: `pipeline.agentic.api`, `pipeline.agentic.api_store`, `pipeline.agentic.client_api`, `pipeline.agentic.mcp_app`.

### [tests/test_mcp_server.py](../../tests/test_mcp_server.py)

Symbols: `approval` (L25), `test_the_adapter_words_six_operations_and_names_the_rest` (L31), `test_an_operation_it_cannot_word_is_rejected_so_the_thread_stays_usable` (L40), `test_a_turn_that_only_offers_unpresentable_work_does_not_loop_forever` (L59), `test_a_presentable_approval_is_still_handed_to_the_host` (L68), `test_whatever_the_host_returns_decides_the_approval` (L79), `test_a_declined_question_never_becomes_an_answer` (L93), `test_request_state_is_bound_to_this_person_thread_and_operation` (L104), `two_people` (L123), `_call` (L142), `test_read_tools_and_widgets_are_listed_with_the_mcp_apps_fields` (L152), `test_overview_and_detail_return_structured_content_for_this_person_only` (L173), `test_current_canonical_assessment_is_projected_without_changing_application_state` (L190), `test_assessment_activity_never_becomes_a_recommendation_or_application` (L219), `test_stale_or_invalid_canonical_assessment_does_not_fall_back_to_legacy_score` (L249), `test_unauthenticated_request_reads_nothing` (L272), `test_ad_link_must_be_http` (L285), `_interrupt` (L295), `_clear_pending` (L302), `test_revision_hands_off_with_the_binding_only_in_meta` (L308), `test_decide_needs_the_binding_the_person_and_is_single_use` (L320), `test_a_submit_approval_from_the_agent_is_never_put_to_the_widget` (L340), `test_tool_annotations_and_widget_only_visibility` (L351), `reviewed` (L364), `_requests` (L371), `test_submit_requires_the_digest_of_the_reviewed_form` (L380), `test_submit_is_per_person_and_needs_a_reviewed_fill` (L396), `test_a_digest_for_one_person_does_not_submit_for_another` (L403), `_oauth_server` (L421), `test_oauth_is_off_by_default_and_needs_its_config` (L428), `test_oauth_flow_maps_the_user_to_the_configured_person` (L439), `test_consent_denied_and_lockout` (L487).

Local imports: `jobwatch`, `jobwatch.apply`, `pipeline.agentic`, `pipeline.agentic.chat`, `pipeline.agentic.runtime`.

### [tests/test_mcp_shortlist.py](../../tests/test_mcp_shortlist.py)

Symbols: `connector` (L8), `test_exact_membership_order_explanations_and_no_activity_fallback` (L12), `test_changed_inputs_hide_every_old_match` (L25), `test_not_built_is_not_an_activity_list` (L33), `test_prepare_requires_consent_current_identity_and_is_idempotent` (L37), `test_holds_remain_visible_but_cannot_prepare_and_exclusions_never_appear` (L57), `test_connector_loads_each_person_rules_before_opening_their_database` (L79), `test_missing_person_database_returns_not_built_without_creating_it` (L115).

Local imports: `jobwatch`, `jobwatch.config`, `pipeline.agentic`.

### [tests/test_model_choice.py](../../tests/test_model_choice.py)

Symbols: `test_pick_saved_and_returned` (L6).

Local imports: `jobwatch`.

### [tests/test_models.py](../../tests/test_models.py)

Symbols: `test_canonical_url_strips_tracking` (L7), `test_au_gate` (L13), `test_state_of` (L21), `test_foreign_places_sharing_au_names_are_not_australian` (L28), `test_state_of_prefers_explicit_state_and_needs_postcode_context` (L36), `test_work_type_and_salary` (L42), `test_work_type_needs_word_boundaries` (L50), `test_salary_unit_boundaries_and_month` (L59), `test_relative_posted` (L67), `test_posting_defaults_and_truncation` (L74), `test_html_to_text_double_escaped` (L81), `test_a_month_elsewhere_in_the_ad_is_not_a_monthly_salary` (L85), `test_nsw_places_named_after_britain_stay_australian` (L91).

Local imports: `jobwatch.models`.

### [tests/test_native_assessment_service.py](../../tests/test_native_assessment_service.py)

Symbols: `test_native_service_uses_deterministic_candidate_context` (L7), `test_embedding_cache_reuses_person_bound_primary_vectors` (L36), `test_public_classifier_is_counted_and_keeps_unknown_usage_charged` (L75), `test_screening_snapshot_keeps_remote_and_hours` (L91), `test_native_run_identity_binds_prescreen_without_inventory_writes` (L103), `test_cached_native_ready_rechecks_prescreen_after_liveness` (L121).

Local imports: `jobwatch`, `jobwatch.candidate.contracts`, `jobwatch.candidate.policy`, `jobwatch.llm`, `jobwatch.prescreen.engine`, `pipeline.agentic`, `pipeline.agentic.autonomous`, `pipeline.agentic.evaluator`, `pipeline.agentic.runtime`, `pipeline.schemas`.

### [tests/test_native_browser.py](../../tests/test_native_browser.py)

Symbols: `auth` (L21), `native` (L26), `test_live_review_changed_form_and_final_submit` (L52), `test_browser_capability_needs_reviewed_digest_for_submit_and_is_person_bound` (L81), `test_browser_capability_presses_submit_for_the_reviewed_form` (L100), `test_accounts_and_expired_browser_grants_are_isolated` (L116), `test_website_adapter_uses_shared_native_session_not_pages` (L134), `test_unreadable_custom_form_stays_blocked` (L164), `test_expired_browser_requires_explicit_current_package_refill` (L174), `test_browser_capability_refuses_a_wrong_or_stale_digest_and_presses_nothing` (L201).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.browser_remote`, `jobwatch.apply.paths`, `jobwatch.config`, `jobwatch.web.browser_session`, `pipeline.agentic.api`, `pipeline.agentic.client_api`.

### [tests/test_no_job_limits.py](../../tests/test_no_job_limits.py)

Symbols: `job` (L24), `test_unlimited_turns_run_past_the_default_cap_and_finite_turns_still_stop` (L30), `test_a_callers_own_turn_cap_survives_an_unlimited_job` (L43), `test_turn_override_does_not_become_a_failed_attempt_loop` (L48), `test_unlimited_job_tokens_never_raise_token_limit_but_finite_does` (L56), `make_store` (L67), `started` (L74), `test_unlimited_job_time_follows_the_outer_batch_deadline_not_900_seconds` (L82), `test_limits_and_call_waits_reach_the_job_and_none_means_no_cap` (L91), `test_a_finite_call_wait_cuts_the_gateway_timeout_and_none_leaves_the_job_clock` (L98), `test_lifting_a_limit_restarts_a_saved_run_that_carried_the_old_one` (L107), `data_dir` (L132), `test_defaults_are_finite_and_unlimited_round_trips_per_person` (L140), `test_saving_only_the_daily_value_keeps_job_limits_and_old_files_still_read` (L152), `test_job_limits_must_be_positive_integers_or_null` (L164), `test_damaged_file_falls_back_to_finite_job_limits` (L169), `test_native_api_reads_and_writes_job_limits` (L176), `run_batch` (L193), `test_a_finite_job_is_cut_at_the_run_window` (L217), `test_an_unlimited_job_that_started_inside_the_window_may_run_to_the_hard_stop` (L223), `test_the_hard_stop_also_caps_the_window_and_blocks_new_starts_after_it` (L229), `test_a_start_rule_of_zero_starts_a_job_with_a_few_seconds_left` (L236), `test_timing_knobs_are_validated_and_null_means_unbounded` (L242), `gateway` (L252), `test_deepseek_flash_is_allowed_for_assessment_and_free_or_stealth_routes_stay_refused` (L256), `test_cheap_assessment_profile_moves_only_the_evaluator_role` (L269), `test_a_gateway_that_rejects_json_mode_or_reasoning_gets_one_request_without_them` (L285), `test_other_bad_requests_are_not_retried` (L303), `tool_reply` (L315), `sam` (L325), `test_default_profile_keeps_the_json_path_and_sends_no_tools` (L331), `test_native_tools_profile_sends_tools_reads_the_tool_call_and_floors_max_tokens` (L339), `test_native_tools_content_json_is_still_accepted_when_the_model_does_not_call_a_tool` (L361), `test_malformed_native_tool_call_is_a_safe_failure_not_a_crash` (L369), `test_json_mode_off_drops_response_format_but_still_parses_json_text` (L376), `test_profiles_are_per_person_per_model_and_ignore_bad_values` (L384), `test_chat_once_native_tools_returns_the_same_shape_as_the_json_path` (L396).

Local imports: `jobwatch`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.api`, `pipeline.agentic.contracts`, `pipeline.agentic.runtime`, `pipeline.agentic.store`.

### [tests/test_notifier.py](../../tests/test_notifier.py)

Symbols: `conn` (L21), `event` (L26), `test_outbox_retries_with_backoff_then_gives_up` (L30), `test_outbox_stops_after_max_attempts` (L45), `test_same_key_is_sent_once_per_window` (L55), `test_event_filter_and_none_channel` (L65), `test_digest_window_is_per_channel_policy` (L76), `test_deliver_is_one_attempt_and_reports_no_channel` (L87), `test_secret_references_only_and_nothing_secret_is_logged` (L96), `test_command_channel_gets_stdin_and_no_shell` (L122), `test_webhook_posts_json` (L133), `test_settings_alias_is_an_equivalent_ssh_append_channel` (L147), `test_alias_needs_both_settings_and_the_owner` (L168), `test_migration_creates_tables_and_ensure_is_idempotent` (L178), `test_cli_add_list_test_disable` (L195), `test_no_private_assistant_name_in_code_paths` (L221).

Local imports: `jobwatch`, `jobwatch.notifier`.

### [tests/test_onboarding_wrangle.py](../../tests/test_onboarding_wrangle.py)

Symbols: `FakeLLM` (L22), `snap` (L32), `test_friend_wrangle` (L37), `test_friend_cannot_reach_owner` (L59), `test_drafter_gets_only_own_samples` (L109), `test_run_chain_passes_only_own_samples` (L124), `test_legacy_string_work_rights_reads_as_unknown` (L157), `test_build_profile_writes_structured_work_rights` (L165), `test_onboarding_missing_level_stays_unknown` (L177).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.web.auth_routes`.

### [tests/test_openrouter_extras.py](../../tests/test_openrouter_extras.py)

Symbols: `test_jev_holds_injection_and_ranking_uses_only_target_roles` (L16), `test_failure_means_none` (L40), `test_one_jev_call_answers_injection_and_knockouts` (L47), `test_embed_sends_the_key_only_to_the_gateway_it_belongs_to` (L61).

Local imports: `jobwatch`, `jobwatch.openrouter_extras`.

### [tests/test_personal_legacy_extract.py](../../tests/test_personal_legacy_extract.py)

Symbols: `test_new_extraction_retries_noncanonical_family_instead_of_guessing_alias` (L11), `test_new_extraction_normalizes_spelling_but_unknown_stays_unknown` (L26), `test_historical_stored_family_keeps_its_original_representation` (L32).

Local imports: `jobwatch.candidate.contracts`, `jobwatch.llm`, `pipeline.nodes`, `pipeline.schemas`.

### [tests/test_personal_legacy_gate.py](../../tests/test_personal_legacy_gate.py)

Symbols: `facts` (L9), `score` (L16), `test_low_domain_score_and_senior_full_time_are_not_shared_exclusions` (L22), `test_confirmed_exclusion_and_unresolved_fact_keep_distinct_routes` (L33), `test_non_job_is_rejected_before_person_eligibility` (L43).

Local imports: `pipeline.nodes`, `pipeline.schemas`.

### [tests/test_personal_writing_preferences.py](../../tests/test_personal_writing_preferences.py)

Symbols: `approved` (L6), `test_confirmed_options_keep_contrasting_voices_and_templates` (L11), `test_unknown_and_inferred_style_is_neutral_and_not_a_graduate_template` (L23), `test_other_person_and_global_career_examples_are_not_loaded` (L37), `test_style_opinions_only_apply_after_person_selects_them` (L54), `test_free_text_writing_preferences_are_preserved_as_framing_only` (L63), `test_legacy_drafter_and_cleanup_do_not_impose_unconfirmed_style` (L71), `test_legacy_template_selector_uses_confirmed_choice_instead_of_title` (L83), `test_malformed_style_values_cannot_crash_or_select_templates` (L92), `test_pdf_trimming_has_no_unconfirmed_six_skill_or_three_bullet_floor` (L99), `test_symlinked_style_directory_cannot_read_another_person` (L106), `test_legacy_sample_opt_out_prevents_sample_text_in_model_prompt` (L121), `test_archived_reference_library_requires_confirmed_opt_in` (L129), `test_current_examples_override_archived_examples` (L161), `test_archive_library_refuses_traversal_symlinks_and_other_person` (L173), `test_reference_text_and_total_output_are_bounded` (L196).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.render`, `jobwatch.apply.review`, `pipeline.agentic`, `pipeline.agentic.draft`, `pipeline.agentic.letter_rules`, `pipeline.agentic.writing_guide`.

### [tests/test_pipeline.py](../../tests/test_pipeline.py)

Symbols: `facts` (L28), `score` (L38), `Gateway` (L44), `confirmed_candidate` (L78), `world` (L91), `stage` (L151), `test_a_good_job_goes_through_every_node_to_ready_and_nothing_is_submitted` (L156), `test_a_low_score_remains_advisory_and_supported_job_can_be_drafted` (L183), `test_computed_scores_are_preserved_without_unconfirmed_cutoff` (L193), `test_model_not_wanted_is_not_a_confirmed_person_exclusion` (L199), `test_citizenship_quoted_from_the_ad_is_an_absolute_fail` (L205), `test_a_rights_claim_the_ad_does_not_say_goes_to_review_not_to_a_guess` (L217), `test_a_visa_alternative_is_held_until_approved_facts_establish_the_branch` (L228), `test_bad_replies_are_retried_and_the_third_valid_one_is_used` (L236), `test_three_failures_go_to_the_dead_letter_queue_and_can_be_retried` (L246), `test_a_failed_draft_is_retried_three_times_then_dead_lettered` (L263), `test_a_move_outside_the_edges_raises` (L273), `test_the_drafting_cap_waits_and_the_next_run_resumes` (L281), `test_the_daily_drafting_cap_counts_drafts_from_earlier_runs` (L291), `test_node_1_dedupes_by_ad_text_skips_other_states_and_archives_paid_ads` (L304), `test_a_short_teaser_is_not_admitted_until_the_whole_ad_is_there` (L318), `test_no_new_node_starts_after_the_time_limit_and_the_next_run_resumes` (L325), `test_the_timer_hook_is_off_unless_the_owner_switches_it_on` (L337), `SortGateway` (L346), `test_archived_not_target_jobs_get_a_named_kind_without_moving` (L366), `test_a_bad_sort_reply_is_retried_then_left_for_the_next_run` (L394), `test_annotate_only_touches_archived_jobs` (L408), `test_a_slow_ad_page_does_not_crash_the_run` (L417), `test_legacy_mode_prompts_name_no_one_person` (L439).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate.policy`, `jobwatch.dedupe`, `jobwatch.llm`, `jobwatch.models`, `pipeline`, `pipeline.nodes`, `pipeline.schemas`.

### [tests/test_pipeline_ingest_browser.py](../../tests/test_pipeline_ingest_browser.py)

Symbols: `test_seek_ad_text_comes_from_the_browser_when_download_fails` (L6), `test_one_site_cannot_take_the_whole_fetch_budget` (L15).

Local imports: `pipeline.nodes.ingest`.

### [tests/test_preference_service.py](../../tests/test_preference_service.py)

Symbols: `test_current_gate_and_changed_ad_invalidate_choice` (L11), `test_legacy_agentic_rows_are_not_current_evaluations` (L37).

Local imports: `jobwatch`, `jobwatch.llm`, `jobwatch.preference_service`, `jobwatch.preferences`, `pipeline.agentic.service`.

### [tests/test_prescreen.py](../../tests/test_prescreen.py)

Symbols: `accountant` (L17), `nurse` (L26), `conn` (L37), `engine` (L43), `run` (L47), `test_migration_from_empty_creates_tables_and_seeds` (L52), `test_migration_from_the_previous_version_keeps_data_and_is_repeatable` (L61), `test_every_seed_term_compiles_and_a_bad_regex_is_rejected` (L80), `test_reseeding_does_not_undo_a_person_edit` (L89), `test_level_stage` (L107), `test_no_level_in_the_profile_means_no_level_screen` (L114), `test_years_stage` (L119), `test_employment_stage` (L131), `test_work_rights_stage` (L142), `test_location_stage` (L156), `test_off_target_follows_the_profile_exclusions_only` (L172), `test_only_obvious_terms_skip` (L184), `test_a_new_field_needs_only_rows` (L192), `test_profile_is_written_as_rows_and_rewritten_when_it_changes` (L200), `_posting` (L216), `pinned` (L225), `test_a_skip_is_archived_with_a_visible_reason_and_ingest_never_fetches_it` (L231), `test_override_readmits_and_records_an_exception_for_this_person_only` (L248), `test_posting_only_override_keeps_the_term_active` (L262), `test_a_profile_change_makes_old_skips_stale_and_reconsider_readmits` (L273), `test_disabling_a_term_readmits_through_reconsider` (L284), `test_screen_ingested_archives_a_queued_mismatch` (L293), `test_stats_count_hits_per_term` (L305), `test_rules_evaluate_gives_the_reason_and_parsed_fields` (L315), `test_without_a_confirmed_profile_the_legacy_rules_are_unchanged` (L328), `test_an_entry_only_profile_still_reads_junior_roles` (L334), `test_country_wide_and_nested_place_names` (L340), `test_cli_words_rules_test_and_override` (L347).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.filters`, `jobwatch.models`, `jobwatch.prescreen`, `jobwatch.prescreen.engine`, `pipeline`, `pipeline.nodes`.

### [tests/test_profile_api.py](../../tests/test_profile_api.py)

Symbols: `FakeLLM` (L19), `env` (L34), `h` (L53), `upload` (L57), `proposal` (L61), `settled` (L69), `test_full_profile_flow_over_http` (L79), `test_confirm_needs_approve_scope` (L103), `test_other_person_cannot_see_proposal` (L118), `test_upload_size_and_type_limits` (L130), `test_empty_upload_is_refused_at_proposal` (L155), `test_every_intake_code_has_a_mapping` (L162), `test_capabilities_lists_profile` (L169), `test_json_cap_applies_to_patch_too` (L174), `test_one_proposal_in_flight_per_person` (L185), `test_an_adopted_owner_onboards_by_a_proposal_on_the_current_version_over_http` (L226), `test_the_scope_only_routes_are_gone` (L244), `test_proposal_returns_202_then_draft` (L249), `test_confirm_while_parsing_is_409_and_uploads_add_documents` (L263), `test_parse_over_http_refuses_a_non_paid_reader_model_without_a_model_call` (L303), `test_parse_over_http_refuses_a_gateway_that_is_not_the_local_one` (L317), `confirm_profile` (L325), `test_policy_endpoint_without_a_profile` (L339), `test_policy_endpoint_after_confirmation_lists_open_questions` (L344), `test_policy_endpoint_asks_about_an_exclusion_it_cannot_apply` (L356), `test_policy_is_per_person` (L366), `test_policy_endpoint_needs_read_scope_only` (L373), `test_policy_mode_is_canonical_for_both_supported_config_spellings` (L385), `test_policy_reads_write_nothing_and_call_no_model` (L395), `test_the_policy_chat_tool_is_read_only_and_not_gated` (L406).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`, `jobwatch.llm`, `pipeline.agentic`, `pipeline.agentic.api`.

### [tests/test_profile_collectors.py](../../tests/test_profile_collectors.py)

Symbols: `policy` (L13), `scope_plan` (L18), `test_every_confirmed_location_gets_a_bounded_rotated_search` (L23), `test_overlay_clears_inherited_remote_and_unknown_home` (L48), `test_jobspy_missing_home_does_not_invent_a_city` (L58), `workday_ctx` (L66), `test_workday_titles_prioritize_but_never_drop_unknown_listings` (L79), `test_workday_persisted_unknown_listings_still_get_their_detail_turn` (L90), `test_workday_unknown_country_is_not_treated_as_foreign_or_australian` (L101), `test_jora_missing_posting_location_does_not_copy_persons_home` (L110), `test_oracle_keeps_provider_order_and_all_region_evidence` (L115), `test_reddit_approved_scope_replaces_shared_geography_and_queries` (L124), `test_reddit_unknown_location_does_not_invent_remote_australia` (L139), `test_reddit_local_source_cannot_override_explicit_posting_geography` (L147), `test_approved_regions_are_searched_when_home_is_unknown` (L153), `test_remote_search_shares_request_cap_and_rotates_after_local_scope` (L160).

Local imports: `jobwatch.collectors`, `jobwatch.occupations`.

### [tests/test_profile_gate_comparison.py](../../tests/test_profile_gate_comparison.py)

Symbols: `test_historical_rejects_current_confirmed_locations` (L13), `test_weak_career_score_is_comparison_data_not_exclusion` (L24), `test_unverified_location_stays_held_with_confirmed_scope` (L33), `test_explicit_exclusion_still_wins_over_good_scores` (L38), `test_remote_label_cannot_bypass_commute_without_ad_evidence` (L43), `test_recorded_unknown_seniority_does_not_become_the_schema_placeholder` (L49).

Local imports: `jobwatch.candidate.policy`, `pipeline.agentic.gate`.

### [tests/test_profile_location_prefilter.py](../../tests/test_profile_location_prefilter.py)

Symbols: `posting` (L9), `test_location_prefilter_comes_from_the_confirmed_person_without_feature_flags` (L18), `test_remote_and_missing_region_follow_confirmed_preferences` (L28), `test_explicit_remote_location_is_not_lost_when_provider_omits_its_remote_flag` (L43), `test_shared_title_arms_cannot_exclude_a_confirmed_nonaccounting_profile` (L52).

Local imports: `jobwatch.candidate`, `jobwatch.filters`, `jobwatch.models`.

### [tests/test_profile_pin.py](../../tests/test_profile_pin.py)

Symbols: `_profile` (L11), `test_pin_redirects_the_person_readers` (L18), `test_pin_applies_to_a_non_default_person` (L31), `test_pinned_folder_is_read_only_to_code` (L43), `test_pins_nest_and_restore` (L50), `test_pin_is_released_when_the_block_raises` (L63), `test_pin_needs_an_existing_absolute_directory` (L73).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.candidate`.

### [tests/test_ranking.py](../../tests/test_ranking.py)

Symbols: `test_partial_unknown_bounds_and_gap_kinds` (L13), `test_all_weights_and_credit_are_importance_based_not_holistic_score` (L19), `test_historical_status_mapping_keeps_missing_unknown_and_supported_matches` (L30), `test_mandatory_lists_and_order_do_not_depend_on_requirement_order` (L37), `test_no_weight_is_clarification_without_division_by_zero` (L49), `test_label_boundaries_and_mandatory_rules` (L64), `test_held_or_uncertain_career_focus_needs_clarification` (L68), `test_only_actionable_current_gate_results_enter_pool` (L83), `scored` (L87), `ids` (L92), `test_provisional_uses_tier_coverage_upper_similarity_then_numeric_posting_id` (L96), `test_coverage_then_upper_then_similarity_precede_id` (L109), `test_focus_only_breaks_ties_when_requested_and_relevant` (L119), `test_personalised_utilities_reorder_only_within_label_tiers` (L126), `test_incomplete_or_invalid_utilities_make_whole_list_provisional` (L134), `explanation` (L141), `test_explanation_orders_exact_frozen_citations_and_omits_unknowns` (L147), `test_transferable_evidence_requires_exact_link_to_existing_support_not_word_overlap_or_inference` (L156), `test_ad_conditions_are_descriptive_and_location_uses_quote_not_legacy_label` (L176), `test_no_facts_gain_default_focus_and_missing_inputs_stay_questions` (L193), `test_shortlist_entry_preserves_explanation_and_detail_as_json` (L202), `test_explanation_caps_evidence_at_six_in_weight_and_id_order` (L214), `test_missing_years_and_uncertain_legitimacy_remain_visible_questions` (L222), `test_unclear_location_quote_is_not_in_area_even_with_legacy_label` (L231), `test_unknown_match_citations_cannot_link_a_transferable_skill` (L243), `test_empty_ranking_and_invalid_similarity_are_deterministic` (L254), `test_transferable_quote_uses_canonical_profile_projection_whitespace` (L259), `test_unstated_location_stays_question_without_confirmed_region_restrictions` (L286), `test_structured_person_skill_links_using_canonical_projection_field_order` (L298).

Local imports: `jobwatch.candidate.projection`, `pipeline.agentic.contracts`, `pipeline.agentic.ranking`.

### [tests/test_reader.py](../../tests/test_reader.py)

Symbols: `model` (L17), `confirmed_candidate` (L41), `test_good_ad_is_shown_with_a_score_out_of_five` (L55), `test_citizenship_claim_needs_a_real_quote` (L61), `test_rule_backstop_catches_what_the_model_missed` (L74), `test_unrestricted_work_rights_exclude_but_plain_right_to_work_does_not` (L79), `test_equal_opportunity_and_plain_work_rights_do_not_hide` (L94), `test_aps_title_alone_needs_verified_ad_requirements` (L99), `test_unconfirmed_hours_and_model_distance_labels_do_not_exclude_or_cap_score` (L104), `test_other_hide_reasons_and_order` (L113), `test_requirement_rows_follow_the_career_ops_gate` (L127), `test_unread_ad_is_held_not_shown` (L141), `test_failed_reading_is_held_and_sponsored_still_hidden` (L146), `test_sponsored_detection_from_seek_json` (L151), `test_model_output_is_clamped_and_cleaned` (L162), `test_contact_lines_are_removed_from_the_cv_before_it_is_sent` (L169), `test_seek_page_parser_reads_the_ad_body` (L175), `FakeGateway` (L184), `make_llm` (L210), `world` (L215), `test_review_pending_reads_stores_and_caches` (L237), `test_confirmed_settings_change_cache_but_unconfirmed_files_do_not` (L253), `test_sponsored_ad_is_hidden_without_a_model_call` (L271), `test_teaser_only_ad_is_held_and_retried_when_text_arrives` (L280), `test_seek_page_is_fetched_once_and_saved` (L292), `test_blocked_host_stops_fetching_but_still_reads_the_teaser` (L306), `test_model_outage_leaves_ads_pending` (L320), `test_rederive_uses_confirmed_policy_not_unconfirmed_score_threshold` (L327), `test_after_collect_is_off_unless_enabled` (L346), `test_recall_adds_plausible_titles_and_remembers_the_rest` (L352), `test_recall_triage_parses_relevant_strictly` (L368), `test_recall_rejects_are_remembered_and_a_failed_batch_is_retried` (L377), `test_prompt_uses_confirmed_evidence_and_cache_follows_approved_profile` (L388), `test_an_invalid_json_reply_is_retried_once` (L411), `test_a_network_timeout_does_not_kill_the_run` (L419), `test_llm_string_error_payload_is_an_llm_error_not_an_attribute_error` (L434), `test_llm_null_usage_counts_do_not_break_cost` (L441), `test_sort_not_target_stops_at_the_run_deadline` (L452), `test_reader_person_scope_and_rights_differ_between_confirmed_profiles` (L472), `test_reader_confirmed_employer_exclusion_is_enforced_without_model_taste` (L496), `test_automatic_reader_reconsiders_cached_show_after_confirmed_policy_change` (L507), `test_reader_workers_keep_calling_person_identity_and_confirmed_policy` (L532).

Local imports: `jobwatch`, `jobwatch.candidate.policy`, `jobwatch.dedupe`, `jobwatch.llm`, `jobwatch.models`, `jobwatch.settings`.

### [tests/test_reader_rules.py](../../tests/test_reader_rules.py)

Symbols: `synthetic_restricted_rights` (L19), `run` (L28), `test_the_rule_backstop_hides_a_none_stated_answer` (L107), `test_sentences_that_admit_visa_holders_or_only_prefer_do_not_hide` (L160), `test_a_negation_only_cancels_the_requirement_in_its_own_clause` (L165), `test_unrestricted_work_rights_wordings_hide` (L184), `test_unrestricted_not_required_and_plain_right_to_work_show` (L189), `test_a_loosely_quoted_claim_is_still_verified` (L195), `test_short_quotes_with_a_blocking_word_count` (L210), `test_a_claim_with_no_words_in_the_ad_is_held_for_review_not_shown` (L216), `test_an_unverified_claim_is_still_hidden_when_the_rule_finds_the_requirement` (L225), `test_a_model_block_whose_sentence_admits_visa_holders_is_not_trusted` (L231), `with_role` (L241), `test_invalid_hard_rule_fields_fail_closed` (L268), `test_a_missing_real_job_field_is_held` (L275), `test_a_concrete_role_that_hires_continuously_is_held_for_the_owner_not_hidden` (L283), `test_soft_hides_from_unread_text_become_review` (L295), `test_hard_hides_still_come_from_unread_text` (L305), `test_an_unknown_kind_is_treated_as_unread` (L313), `test_requirement_rows_up_to_twelve_critical_and_high_never_dropped_and_sorted` (L318), `test_gaps_up_to_five` (L336), `test_junk_values_in_any_field_never_raise` (L346), `test_infinity_in_json_is_handled_like_any_other_number` (L363), `test_a_failure_inside_the_rules_becomes_a_held_review` (L370), `test_one_poison_answer_does_not_stop_the_batch_and_an_empty_answer_is_never_stored` (L380), `test_ask_rejects_an_answer_that_is_not_an_evaluation` (L393), `test_jora_paid_placement_is_detected_from_the_card_link` (L403), `test_other_sources_that_mark_paid_placement_are_detected` (L409), `test_a_sponsored_jora_ad_is_hidden_without_a_model_call_and_an_organic_one_is_read` (L419), `test_every_contact_form_is_dropped` (L446), `test_a_wrapped_email_is_dropped_whole` (L451), `test_the_whole_preamble_above_the_first_heading_goes_and_the_body_stays` (L456), `test_a_cv_without_headings_loses_its_first_two_lines` (L467), `test_the_profile_file_is_scrubbed_too_and_never_reaches_the_model` (L472), `posting` (L481), `test_ad_text_cannot_close_the_ad_fence_or_forge_a_profile` (L488), `test_a_cv_or_profile_cannot_forge_a_fence_either` (L497), `test_block_g_inputs_reach_the_model` (L506), `test_the_pending_query_carries_the_block_g_columns` (L519), `test_partial_text_is_announced_to_the_model` (L529), `test_prompt_v5_carries_the_owner_decisions` (L535), `_Server` (L550), `servers` (L584), `test_the_llm_client_ignores_proxy_environment_variables` (L598), `test_the_llm_client_does_not_follow_redirects` (L608), `_set` (L618), `test_recall_considers_every_ad_that_is_still_listed_whatever_its_own_date` (L623), `test_recall_judges_senior_and_off_target_titles_by_meaning_not_by_a_word` (L644), `test_recall_stops_before_a_batch_when_max_seconds_has_run_out` (L655), `test_work_rights_after_and_or_with_are_a_condition_not_an_alternative_so_the_ad_hides` (L703), `test_a_visa_or_work_rights_alternative_still_lets_the_ad_through` (L740), `test_backstop_holes_closed` (L762), `test_exempt_checks_and_not_required_wordings_still_show` (L783), `test_more_unrestricted_wordings_hide` (L794), `test_low_fit_from_unread_text_hides_only_a_clear_miss` (L801), `test_ongoing_only_sentence_is_held_for_the_owner` (L818), `test_ongoing_only_sentence_hides_when_the_ad_confirms_the_requirement` (L837), `test_ongoing_only_sentence_stays_held_when_other_roles_are_mentioned_without_the_requirement` (L847), `test_min_years_strings_parse_to_the_leading_integer` (L860), `test_a_min_years_string_with_a_plus_counts_as_senior` (L866), `test_a_min_years_value_that_cannot_be_read_holds_the_ad` (L875), `test_a_year_or_an_absurd_number_is_not_a_hide_but_a_real_one_still_is` (L881), `test_no_min_years_is_not_a_problem` (L889), `_timed` (L895), `test_a_stuffed_ad_does_not_stall_the_rules` (L904), `test_the_two_probe_inputs_hide_and_are_fast` (L911), `test_clause_breaks_are_computed_once_per_segment` (L917), `test_a_fuzzy_match_must_contain_the_blocking_word_of_the_quote` (L926), `_synthetic_world` (L945), `test_the_pending_query_is_fast_on_a_database_the_size_of_the_live_one` (L961), `test_same_title_count_is_zero_without_a_company` (L979), `_review` (L995), `test_unread_and_cut_ads_are_retried_when_a_fetch_becomes_possible` (L1001), `test_more_contact_forms_are_dropped_from_the_cv` (L1033), `test_ordinary_cv_lines_are_kept` (L1044), `test_the_career_ops_profile_is_only_redacted_and_keeps_the_home_area_line` (L1049), `test_load_profile_uses_the_profile_redaction` (L1067), `test_the_fence_cannot_be_forged_whatever_the_spelling` (L1082), `test_defang_leaves_ordinary_text_alone_apart_from_decoding` (L1089), `test_zero_width_and_lookalike_fences_in_the_cv_and_profile_are_neutralised` (L1095), `test_a_visa_alternative_never_cancels_a_clearance_vetting_aps_or_el_requirement` (L1123), `test_visa_holders_as_the_subject_of_a_duty_is_not_an_alternative_so_the_ad_hides` (L1147), `test_a_holder_noun_right_after_the_separator_is_still_an_alternative` (L1166), `test_more_unrestricted_work_rights_wordings_hide` (L1191), `test_plain_right_to_work_and_not_required_wordings_still_show` (L1209), `test_a_generic_quote_cannot_verify_a_rights_claim` (L1226), `test_blocking_quotes_are_recognised` (L1239), `test_generic_or_short_quotes_are_not_blocking` (L1247), `test_a_word_rule_never_overrules_the_models_reading_of_the_same_sentence` (L1251), `test_a_real_quote_still_verifies_and_a_rule_corroborated_short_quote_still_counts` (L1258), `test_a_whitespace_run_does_not_stall_the_rules` (L1275), `test_a_mini_fuzz_of_pathological_texts_stays_fast` (L1285), `test_unicode_spaces_read_as_plain_spaces_in_the_rules` (L1298), `test_the_fence_regex_is_linear_on_a_long_run_of_spaces` (L1304), `test_defang_removes_unicode_tag_characters_and_variation_selectors` (L1313), `test_defang_decodes_entity_layers_until_nothing_changes` (L1321), `test_the_career_ops_profile_goes_through_defang` (L1327), `test_no_career_ops_profile_gives_a_neutral_text_never_the_example_file` (L1334), `test_prompt_settings_come_from_the_persons_files` (L1344), `test_cv_drops_more_handles_birth_dates_and_any_tld` (L1367), `test_tech_names_and_ordinary_words_are_not_contact_data` (L1377), `test_the_profile_masks_mailto_and_any_tld_domains_in_place` (L1381), `_posting_row` (L1387), `test_ask_refuses_to_send_a_profile_that_still_holds_contact_data` (L1394), `test_ask_sends_a_clean_profile_and_an_ad_with_contact_data_is_fine` (L1405), `test_a_leaking_profile_holds_every_ad_with_a_privacy_flag_and_sends_nothing` (L1412), `test_a_phone_with_year_like_groups_is_redacted_but_year_ranges_are_kept` (L1431), `test_missing_approved_rights_hold_instead_of_inventing_a_contradiction` (L1443), `test_rights_policy_stays_with_the_current_person_in_scanner_batteries` (L1451).

Local imports: `jobwatch`, `jobwatch.candidate.policy`, `jobwatch.filters`, `jobwatch.llm`, `jobwatch.models`.

### [tests/test_selection.py](../../tests/test_selection.py)

Symbols: `payload` (L9), `test_selection_retry_outbox_crash_recovery_and_person_isolation` (L17), `test_changed_inputs_cancelled_requests_and_model_writes_never_queue` (L42), `test_selected_only_execution_passes_expected_keys_and_stable_batch` (L56), `test_recovery_accepts_its_own_progress_but_refuses_changed_ranking_context` (L77), `test_completed_selection_republishes_same_result_after_api_crash_without_preparing_again` (L95), `test_cancelled_run_is_reconciled_after_generic_cancel_or_cross_store_crash` (L119), `test_reconciliation_reaches_cancelled_work_behind_interrupted_requests` (L139).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.api_store`.

### [tests/test_shortlist.py](../../tests/test_shortlist.py)

Symbols: `test_shortlist_tables_are_additive_and_migration_is_idempotent` (L11), `test_build_is_current_explained_idempotent_and_unpaid` (L18), `test_changed_inputs_hide_all_stale_entries` (L31), `test_no_confirmed_profile_or_different_person_never_sees_snapshot` (L48), `test_impressions_are_deduplicated_and_are_never_choices` (L56), `test_shadow_relevance_does_not_exclude` (L65), `test_snapshot_change_before_persistence_rolls_back` (L79), `test_clock_expiry_invalidates_without_any_database_write` (L92), `test_only_hypotheses_linked_to_confirmed_focus_get_focus_priority` (L105), `test_valid_complete_utilities_personalise_but_incomplete_ones_do_not` (L115), `test_implementation_change_invalidates_saved_presentation` (L131).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.candidate.policy`, `jobwatch.occupations.plan`, `jobwatch.preference_service`, `jobwatch.preferences`, `pipeline.agentic`.

### [tests/test_shortlist_api.py](../../tests/test_shortlist_api.py)

Symbols: `headers` (L11), `client` (L15), `test_scope_validation_and_missing_profile` (L24), `test_refresh_views_and_detail_are_current_explained_and_idempotent` (L34), `test_change_inside_throttle_window_rebuilds_and_never_returns_stale` (L50), `test_no_database_returns_not_built_without_creating_one` (L60).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.api`.

### [tests/test_shortlist_integration_regressions.py](../../tests/test_shortlist_integration_regressions.py)

Symbols: `test_saved_shortlist_rejects_corrupt_candidate_artifact` (L10), `test_profile_capture_precedes_freshness_fence` (L19), `test_completed_prefix_does_not_starve_new_pending_work` (L34), `test_stored_response_readiness_freshness_tracks_source_events` (L52).

Local imports: `jobwatch`, `jobwatch.candidate`, `jobwatch.outcomes.readiness`, `pipeline.agentic`.

### [tests/test_shortlist_scheduling.py](../../tests/test_shortlist_scheduling.py)

Symbols: `inputs` (L9), `test_only_unchanged_completed_evaluation_with_current_liveness_is_skipped` (L18), `test_retry_reasons_and_changed_policy_are_not_skipped` (L25), `test_spent_budget_still_refreshes_shortlist_without_paid_work` (L34), `test_shortlist_failure_does_not_fail_collection` (L40).

Local imports: `jobwatch`, `pipeline.agentic`, `pipeline.agentic.persistence`.

### [tests/test_shortlist_utilities.py](../../tests/test_shortlist_utilities.py)

Symbols: `test_more_than_one_prediction_batch_covers_the_entire_pool` (L7), `test_any_inconsistent_batch_refuses_the_combined_utilities` (L20), `test_valid_genuine_fit_applies_when_current_pool_exceeds_display_cap` (L44).

Local imports: `jobwatch`, `jobwatch.preferences`, `jobwatch.preferences.features`, `pipeline.agentic`.

### [tests/test_sort_deadline.py](../../tests/test_sort_deadline.py)

Symbols: `clock` (L12), `conn` (L20), `run` (L37), `unchanged` (L42), `test_nearly_expired_timeout_cannot_retry` (L49), `test_exhausted_budget_never_calls` (L65), `test_retry_and_key_fallback_share_remaining_budget` (L73), `test_key_refusal_at_deadline_does_not_try_next_key` (L94), `test_success_at_deadline_is_not_applied` (L107).

Local imports: `jobwatch.llm`, `pipeline.nodes`.

### [tests/test_submit_confirm.py](../../tests/test_submit_confirm.py)

Symbols: `_ready` (L14), `test_a_confirmed_digest_presses_the_recognised_submit_once` (L37), `test_a_stale_or_wrong_confirmation_presses_nothing` (L49), `test_scrolling_to_review_keeps_the_confirmation` (L65), `test_form_state_ignores_hidden_tokens_and_captcha_but_sees_every_selected_option` (L75), `test_digest_needs_a_ready_fill_with_a_final_control` (L90), `test_requests_queue_once_expire_and_settle` (L97), `test_a_pressed_request_without_a_page_verdict_becomes_unsure` (L110), `test_a_pressed_request_is_never_pressed_again_after_a_restart` (L123).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.prefill_workflow`, `jobwatch.web.browser_session`.

### [tests/test_task_state.py](../../tests/test_task_state.py)

Symbols: `_conn` (L12), `_selection` (L16), `_queue` (L23), `test_task_card_keeps_draft_ready_apart_from_submitted` (L27), `test_unsure_outcome_is_stated_and_blocks_any_retry` (L42), `test_stop_cancels_unpressed_work_and_reports_what_it_cannot_undo` (L53), `_posting` (L66), `test_jobs_overview_newest_first_with_card_states_and_counts` (L72).

Local imports: `jobwatch`, `jobwatch.apply`, `pipeline.agentic`.

### [tests/test_tui.py](../../tests/test_tui.py)

Symbols: `FakeBackend` (L28), `ashot` (L146), `shot` (L159), `app` (L178), `_settle` (L197), `test_pending_strip_keys_state_line_and_footer` (L205), `test_reject_with_reason` (L224), `test_hidden_control_characters_are_stripped` (L238), `test_submit_is_not_approved_from_the_main_board` (L242), `test_main_board_wide_and_narrow` (L260), `test_today_detail_and_review` (L278), `test_submit_only_from_review` (L298), `test_review_escape_sends_nothing` (L317), `test_file_picker_chip_upload_and_size_limit` (L332), `test_slash_boards_render` (L373), `test_inbox_decision_and_models_edit` (L398), `test_table_sort_and_filter_keys` (L422), `test_state_empty_feed` (L439), `test_state_failed_step_and_retry_keys` (L453), `test_state_working_shows_step_and_cancel_hint` (L478), `test_state_outcome_unknown_line` (L506), `test_home_is_the_start_screen_and_opens_views` (L527), `test_home_typing_asks_the_agent_and_never_approves` (L556), `test_needs_you_lists_paused_assessments_and_is_not_openable` (L582).

Local imports: `pipeline.agentic`, `pipeline.agentic.tui`, `pipeline.agentic.tui_data`, `pipeline.agentic.tui_screens`.

### [tests/test_tui_backend_auth.py](../../tests/test_tui_backend_auth.py)

Symbols: `test_tui_backend_signs_in_as_its_person_when_web_auth_is_on` (L9).

Local imports: `jobwatch`, `jobwatch.web`, `jobwatch.web.auth_routes`, `pipeline.agentic.tui_data`.

### [tests/test_users.py](../../tests/test_users.py)

Symbols: `test_user_paths` (L6).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.config`.

### [tests/test_wave2.py](../../tests/test_wave2.py)

Symbols: `emp` (L16), `test_sf_title_location_split` (L21), `test_successfactors_feed_gate_and_fields` (L29), `test_successfactors_conditional_get` (L47), `test_oracle_au_gate_preserves_provider_location_order_and_url` (L62), `test_oracle_stops_paging_at_known` (L78), `test_careers_vic_parse_and_grades` (L94), `test_careers_vic_rules_use_grade` (L106), `test_careers_vic_pages_fast_vs_deep_and_stop_at_known` (L123), `test_careers_vic_robots` (L150), `test_phenom_embedded_state_and_widget_paging` (L157), `test_phenom_robots_and_not_phenom` (L172), `test_atlassian_au_only` (L182), `test_jsonld_capital_title_no_follow_and_url_pairing` (L193), `test_jsonld_listing_without_urls_gets_distinct_ids` (L208), `test_registry_arm_map` (L216), `test_tier_all_runs_shared_collector_once` (L226), `test_cli_exit_code_all_failed` (L231), `test_cli_run_exits_1_when_every_collector_errors` (L237), `test_unknown_location_vic_employer_but_title_names_other_state` (L251), `test_wave2_precision_excludes` (L260).

Local imports: `jobwatch`, `jobwatch.collectors`, `jobwatch.filters`, `jobwatch.models`.

### [tests/test_web_access.py](../../tests/test_web_access.py)

Symbols: `home` (L13), `_client` (L21), `test_login_links_to_signup_even_when_closed` (L27), `test_signup_closed_explains_and_hides_code_field` (L34), `test_signup_open_shows_code_field` (L42), `test_set_password_round_trip` (L48), `test_set_password_rejects_bad_names` (L62), `test_set_password_short_or_mismatch_changes_nothing` (L68), `test_invite_writes_replaces_backs_up_and_hides_code` (L76), `test_invite_keeps_newest_three_backups` (L96), `test_invite_needs_settings_env` (L109).

Local imports: `jobwatch`, `jobwatch.web`.

### [tests/web/test_agentic.py](../../tests/web/test_agentic.py)

Symbols: `_client` (L15), `test_board_shows_agent_reason_as_escaped_text` (L50), `test_applications_shows_safe_agentic_hold_and_ready_package` (L57), `test_legacy_database_without_agentic_tables_still_serves_board_and_applications` (L83), `test_answers_page_saves_and_keeps_comments` (L93).

Local imports: `jobwatch`, `jobwatch.config`, `jobwatch.web.answers_routes`, `jobwatch.web.app`, `pipeline`.

### [tests/web/test_agentic_projection.py](../../tests/web/test_agentic_projection.py)

Symbols: `test_quota_hold_keeps_evaluation_visible_without_ready_badge` (L21), `test_real_agentic_score_reason_archetype_drive_board_filters_and_cards` (L35), `test_board_corrupt_package_is_held_and_corrupt_evaluation_never_uses_stale_reader_score` (L68).

Local imports: `jobwatch`, `jobwatch.llm`, `jobwatch.web`, `jobwatch.web.app`, `pipeline.agentic.persistence`, `pipeline.agentic.service`, `pipeline.schemas`.

### [tests/web/test_ai.py](../../tests/web/test_ai.py)

Symbols: `seed` (L22), `review` (L37), `make_config` (L50), `BoardClient` (L58), `make_client` (L66), `client` (L73), `titles` (L108), `body` (L115), `cards_of` (L121), `test_load_rows_attaches_ai_and_state_in_one_query` (L127), `test_score_is_the_ai_fit_when_read_else_the_keyword_score` (L144), `test_unknown_verdict_is_held_back_never_shown` (L156), `test_bad_json_in_a_review_does_not_break_the_board` (L164), `test_default_list_is_good_only` (L174), `test_best_fit_sort_uses_ai_fit_with_newest_first_on_ties` (L182), `test_each_ai_view_lists_only_its_own` (L193), `test_hide_reason_filter` (L200), `test_bad_ai_params_fall_back_safely` (L205), `test_unmatched_jobs_are_waiting_with_scope_all` (L216), `test_filters_roundtrip_and_urls` (L231), `test_csv_has_ai_columns_and_is_formula_safe` (L273), `backfill` (L289), `test_javascript_url_never_becomes_a_link_on_an_ai_row` (L316), `req` (L326), `report` (L332), `review3` (L349), `v3` (L359), `test_score_display_helper` (L400), `test_rows_carry_score5_archetype_and_a_clean_report` (L409), `test_bad_report_json_never_breaks_a_page` (L426), `test_hide_reason_labels_keep_the_old_ones_and_add_the_new` (L448), `test_best_fit_sort_uses_score_with_null_scores_as_fit_over_20` (L471), `test_minscore_filter` (L490), `test_archetype_filter_is_multi_valued_and_never_comma_split` (L509), `test_filters_parse_minscore` (L527), `titles_of_table` (L538), `test_csv_score_archetype_recommendation_and_filters` (L542), `_set_source` (L561), `test_a_show_verdict_from_a_cut_ad_is_listed_as_not_fully_read` (L574), `test_ai_state_is_good_only_for_a_show_read_from_the_full_ad` (L594), `test_a_row_with_no_text_source_is_not_good_in_the_database_either` (L604), `_years_asked` (L614), `test_hold_replaces_apply_and_consider_only_and_never_for_a_good_row` (L624), `staged` (L643), `test_pipeline_bad_json_never_breaks_the_board` (L658), `test_pipeline_not_target_shows_the_sorted_kind` (L670).

Local imports: `jobwatch`, `jobwatch.config`, `jobwatch.web`, `jobwatch.web.app`, `pipeline`.

### [tests/web/test_app_session.py](../../tests/web/test_app_session.py)

Symbols: `board` (L14), `test_an_ended_session_shows_an_error_not_an_empty_page` (L41).

Local imports: `jobwatch`, `jobwatch.config`, `jobwatch.web.app`.

### [tests/web/test_browser_controls.py](../../tests/web/test_browser_controls.py)

Symbols: `test_remote_browser_controls_send_keys_to_the_remote_browser` (L9).

### [tests/web/test_candidate_no_profile.py](../../tests/web/test_candidate_no_profile.py)

Symbols: `test_candidate_page_without_profile_logs_no_error` (L9).

Local imports: `jobwatch.config`, `jobwatch.web.app`.

### [tests/web/test_discovery_allowance_settings.py](../../tests/web/test_discovery_allowance_settings.py)

Symbols: `test_daily_token_allowance_finite_and_unlimited_roundtrip` (L10), `test_invalid_daily_token_allowance_is_visible_and_not_saved` (L36), `test_daily_token_allowance_requires_a_known_mode` (L48), `test_unreadable_saved_allowance_can_be_replaced` (L57), `test_daily_token_allowance_is_bound_to_authenticated_person` (L73), `test_daily_token_allowance_rejects_cross_origin_posts` (L94), `test_job_limits_form_saves_unlimited_and_finite_values_without_touching_the_daily_value` (L101), `test_job_limits_form_refuses_a_bad_limited_value` (L119).

Local imports: `jobwatch`, `jobwatch.web.auth_routes`.

### [tests/web/test_discovery_status.py](../../tests/web/test_discovery_status.py)

Symbols: `test_discovery_failure_is_visible_and_page_uses_safe_codes` (L6), `test_discovery_empty_state_is_not_an_error` (L24), `test_completed_request_shows_budget_deferral_without_claiming_an_assessment` (L29).

Local imports: `jobwatch`, `jobwatch.config`, `pipeline.agentic`.

### [tests/web/test_filters_ids.py](../../tests/web/test_filters_ids.py)

Symbols: `make_rows` (L20), `reference` (L40), `to_filters` (L78), `test_combined_facets_match_the_reference` (L83), `test_pill_counts_equal_the_list_you_get_by_picking_them` (L91), `test_every_predicate_has_its_own_binding` (L109), `test_non_ascii_digits_are_ignored_not_a_500` (L125), `test_ascii_digits_still_parse` (L135), `test_missing_or_out_of_range_ids_are_a_404_page` (L147), `test_post_to_a_missing_job_is_404_not_500` (L157), `test_other_posts_with_bad_ids_do_not_500` (L162), `test_real_job_still_opens_and_is_marked_viewed` (L170), `test_validation_error_for_json_callers_is_json` (L176), `test_validation_error_for_a_browser_is_still_the_html_page` (L182), `test_odd_integers_are_ignored_or_404_never_500` (L198), `test_odd_integer_posts_are_404` (L205).

Local imports: `jobwatch.web`, `jobwatch.web.app`.

### [tests/web/test_followup_drafts.py](../../tests/web/test_followup_drafts.py)

Symbols: `draft_client` (L17), `test_owner_generates_reviews_and_cached_click_does_not_send` (L37), `test_changed_profile_hides_previously_approved_text` (L47), `test_not_due_and_cross_origin_cannot_start_paid_work` (L55), `test_email_and_linkedin_are_distinct_reviewed_snapshots` (L63), `test_invalid_profile_is_readiness_response_without_model_calls` (L76), `test_owner_explicitly_retries_held_draft` (L86).

Local imports: `jobwatch`, `jobwatch.candidate.evidence`, `jobwatch.config`, `jobwatch.web.app`.

### [tests/web/test_followups.py](../../tests/web/test_followups.py)

Symbols: `test_followup_controls_record_confirmed_history_and_preserve_submission` (L7), `test_followup_endpoint_requires_confirmation_and_same_origin` (L21).

Local imports: `jobwatch`.

### [tests/web/test_interview_url_web.py](../../tests/web/test_interview_url_web.py)

Symbols: `test_url_workflow_without_tracker_writes` (L7), `test_matching_report_precedes_network` (L30), `test_closed_url_paste_recovery_and_origin` (L39), `test_saved_description_survives_missing_profile_and_validation_error` (L49).

Local imports: `jobwatch`, `jobwatch.interview_ad`.

### [tests/web/test_interview_web.py](../../tests/web/test_interview_web.py)

Symbols: `prep_client` (L18), `test_generation_download_cache_and_no_application` (L36), `test_notes_revision_escape_staleness_and_origin` (L52), `test_private_readiness_and_not_found` (L64), `test_held_requires_explicit_retry` (L71), `test_explicit_interview_status_checks_eligibility` (L86), `test_owner_outcome_approval_queues_interview` (L98), `test_ineligible_interview_transition_does_not_generate` (L114), `test_report_text_is_escaped_and_poll_is_fragment` (L120), `test_source_link_filter_only_public_https` (L131), `test_interview_transition_saves_queue_before_dispatch` (L142), `test_startup_recovers_durable_queue_once` (L156), `test_startup_recovers_a_friends_durable_queue_as_that_friend` (L174), `test_startup_never_retries_held_unknown_dispatch` (L194), `test_queue_write_failure_is_private_unavailable` (L208), `test_worker_drains_new_owner_queued_snapshot` (L218), `test_worker_does_not_dispatch_unqueued_changed_source` (L236), `test_recovery_scan_cannot_enqueue_changed_sources` (L251), `test_one_persons_active_interview_does_not_block_anothers_same_posting_id` (L269).

Local imports: `jobwatch`, `jobwatch.candidate.evidence`, `jobwatch.config`, `jobwatch.interview_inputs`, `jobwatch.interview_prep`, `jobwatch.web.app`, `jobwatch.web.auth_routes`, `pipeline.agentic.contracts`.

### [tests/web/test_legacy_kinds.py](../../tests/web/test_legacy_kinds.py)

Symbols: `test_pipeline_precedence_over_legacy_kind` (L12), `test_legacy_model_kind_reaches_board_and_filter` (L26), `test_invalid_legacy_kind_stays_truthfully_unsorted` (L51), `test_valid_report_and_existing_hide_reason_take_precedence` (L58), `test_missing_or_invalid_report_kind_uses_valid_legacy_kind` (L67).

Local imports: `jobwatch`, `jobwatch.web`, `pipeline`.

### [tests/web/test_neutral_board_score.py](../../tests/web/test_neutral_board_score.py)

Symbols: `test_entry_flag_does_not_change_fallback_ordering` (L4), `test_question_cards_keep_unknown_or_legacy_rights_neutral` (L9).

Local imports: `jobwatch.web.ask_cards`, `jobwatch.web.queries`.

### [tests/web/test_preferences.py](../../tests/web/test_preferences.py)

Symbols: `setup` (L8), `test_get_is_read_only_and_choice_is_explicit` (L16), `test_cross_origin_and_stale_choice_rejected` (L37), `test_three_fresh_evaluations_required` (L49), `test_inspect_predictions_only_after_explicit_choice` (L55).

Local imports: `jobwatch`, `jobwatch.preferences`, `jobwatch.preferences.features`, `jobwatch.preferences.model`, `jobwatch.web`.

### [tests/web/test_prepare_routes.py](../../tests/web/test_prepare_routes.py)

Symbols: `Browser` (L17), `setup` (L59), `pending_state` (L73), `test_auto_fill_without_agentic_runs_table_is_nothing_ready_and_the_loop_survives_a_bad_tick` (L84), `complete_queued_intake` (L105), `test_viewing_job_and_candidate_pages_never_starts_browser` (L109), `test_open_automatically_prepares_verified_application_and_displays_live_stream` (L118), `test_owner_controls_require_same_origin_and_wait_for_automation` (L128), `test_browser_stream_has_private_headers_and_actual_image_frame` (L141), `test_new_package_invalidates_old_ready_preparation` (L151), `test_owner_intake_accepts_only_current_question_ids_and_restarts_filling` (L162), `test_owner_intake_preserves_multiple_choices_and_boolean_controls` (L179), `test_stale_intake_never_saves_answers_or_starts_filling` (L195), `test_queued_intake_rechecks_binding_before_any_answer_save` (L216), `test_missing_fact_batch_is_validated_before_any_save` (L233), `test_evaluation_displays_actual_evidence_risk_and_mitigation_with_escaping` (L246), `test_current_profile_or_ad_change_holds_preparation` (L262), `test_preparation_requires_fresh_active_source_bound_observation` (L287), `test_held_or_missing_package_cannot_display_old_ready_state` (L310), `test_prepare_post_reaches_specific_route_before_generic_job_action` (L317), `test_candidate_page_computes_local_statistics_without_model_calls` (L324), `ready_state` (L342), `test_board_confirmation_presses_submit_for_the_shown_fill_only` (L350), `test_a_refused_board_confirmation_says_nothing_was_submitted` (L368), `test_no_submit_button_without_a_confirmable_fill` (L377), `_queue` (L384), `_request` (L393), `test_an_approved_chat_request_is_pressed_through_the_live_check_and_recorded` (L401), `test_a_stale_or_expired_chat_request_presses_nothing` (L417), `test_background_work_runs_once_per_person_as_that_person` (L433), `test_a_submit_seen_while_no_prepare_page_is_open_is_still_recorded` (L443), `test_a_refused_board_press_leaves_no_confirmed_event` (L453).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.apply.paths`, `jobwatch.web`, `jobwatch.web.browser_session`, `pipeline.agentic.service`.

### [tests/web/test_web.py](../../tests/web/test_web.py)

Symbols: `seed` (L15), `client` (L28), `test_pages_render` (L49), `test_root_serves_the_app_and_old_pages_redirect_into_it` (L60), `test_unknown_job_is_404` (L72), `test_salary_display_labels_every_pay_period` (L76), `test_host_header_guard` (L86), `test_post_needs_same_origin` (L91), `test_actions_write_through_the_ledger` (L102), `test_csv_is_safe` (L123), `test_security_headers` (L128), `test_draft_files_only_whitelisted_and_inside_root` (L135), `test_saved_search_roundtrip` (L146), `test_cross_site_subrequests_blocked_but_navigation_allowed` (L153), `test_javascript_urls_never_become_links` (L159), `_friend_client` (L168), `test_draft_files_are_served_from_the_signed_in_persons_folder` (L180), `test_draft_worker_runs_as_the_person_who_started_it` (L192), `test_board_times_use_the_persons_timezone` (L228), `test_api_404_is_json_even_without_json_accept` (L246), `test_nav_counts_use_the_sources_page_rule` (L254).

Local imports: `jobwatch`, `jobwatch.apply`, `jobwatch.config`, `jobwatch.web`, `jobwatch.web.app`, `jobwatch.web.auth_routes`, `jobwatch.web.queries`.

## tools (1 files)

### [tools/build_occupation_reference.py](../../tools/build_occupation_reference.py)

Symbols: `sheet` (L18), `family` (L34), `build` (L46).
