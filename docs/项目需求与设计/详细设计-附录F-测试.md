# 详细设计附录 F：测试

总入口见 [详细设计](详细设计.md)。

<a id="section-22"></a>

## 附录 F：测试文件及用例定位目录

列出62个tests/test_*.py文件中的测试函数。该目录表达测试意图；完整运行结果仍以具体运行回执为准。工作台另有workbench/test_workbench.py和test_browser.cjs，不包含在这里的Python生产测试文件计数中。

### F · `test_acceptance.py`

[tests/test_acceptance.py](../../tests/test_acceptance.py)

- `test_contract_complete_review_allows_delivery`
- `test_new_visual_gate_blocks_delivery_without_rewriting_existing_final`
- `test_missing_review_blocks_delivery`
- `test_review_of_another_video_is_rejected`
- `test_omitted_instance_is_not_hidden_by_high_score`
- `test_critical_defect_overrides_high_score`
- `test_failed_review_survives_later_passing_review`
- `test_foreign_speech_cannot_be_left_untranslated`
- `test_source_frame_cannot_substitute_for_output_evidence`
- `test_candidate_hash_tampering_blocks_delivery`
- `test_missing_postprocessing_record_blocks_delivery`
- `test_changed_inventory_invalidates_plan`
- `test_limited_range_video_extracts_full_range_jpeg`
- `test_text_erasure_prompt_keeps_target_copy_out_of_model_stage`
- `test_typesetting_preserves_duration_and_splits_no_english_cleanup`
- `test_reference_composition_limits_repair_to_reviewed_region`
- `test_wan_packet_uses_video_reference_and_silent_five_second_contract`
- `test_wan_edit_packet_uses_source_video_and_reference_layout`
- `test_veo_lite_reference_packet_contains_images_without_source_video`
- `test_initialize_and_tool_discovery`
- `test_visual_mcp_uses_the_same_single_instance_review`
- `test_mcp_does_not_accept_arbitrary_execution`
- `test_notifications_do_not_emit_responses`

### F · `test_advisory_scope_guard.py`

[tests/test_advisory_scope_guard.py](../../tests/test_advisory_scope_guard.py)

- `test_unstructured_observation_scope_does_not_break_production_recall`

### F · `test_atomic_journal.py`

[tests/test_atomic_journal.py](../../tests/test_atomic_journal.py)

- `test_invalid_record_identifies_file_without_exposing_content_or_repairing`
- `test_transient_windows_reader_keeps_old_record_until_replace`
- `test_permanent_denial_leaves_old_journal_and_propagates`

### F · `test_audio.py`

[tests/test_audio.py](../../tests/test_audio.py)

- `test_preserve_mux_keeps_audible_source_after_silent_visual_processing`
- `test_audio_track_containing_silence_is_rejected`
- `test_missing_audio_is_rejected_when_source_has_sound`
- `test_different_soundtrack_cannot_pass_as_retained_music`
- `test_shifted_music_is_rejected_even_when_the_waveform_matches`
- `test_model_audio_can_be_selected_without_reusing_foreign_source_mix`
- `test_missing_model_audio_does_not_fall_back_to_source_or_silence`
- `test_short_model_audio_tail_does_not_shift_the_next_segment`
- `test_prompt_delegates_dialogue_even_when_agent_cannot_hear`
- `test_no_track_source_does_not_authorize_invented_music`
- `test_source_region_restoration_keeps_unedited_banner_and_edited_scene`
- `test_capture_uses_video_end_when_audio_outlasts_picture`
- `test_source_audio_cannot_be_muted_without_authorization`
- `test_audio_analysis_submission_reuses_receipt_instead_of_charging_again`
- `test_native_model_audio_enables_auto_audio_in_actual_packet`
- `test_returned_sound_is_muxed_but_unreviewed_semantics_blocks_delivery`

### F · `test_audio_resume.py`

[tests/test_audio_resume.py](../../tests/test_audio_resume.py)

- `test_asr_reuses_exact_audio_but_invalidates_audio_and_settings`
- `test_tts_unknown_accent_is_rejected_before_provider_submission`
- `test_tts_keeps_documented_voice_delivery_controls`
- `test_real_mixer_reuses_and_preserves_prior_mix_after_revision`

### F · `test_audio_task_retry.py`

[tests/test_audio_task_retry.py](../../tests/test_audio_task_retry.py)

- `test_authorized_429_gets_new_reservation_without_rewriting_old_job`
- `test_two_zero_cost_rounds_are_idempotent_and_do_not_retry_ambiguous_or_paid_failures`

### F · `test_authorized_audio_review.py`

[tests/test_authorized_audio_review.py](../../tests/test_authorized_audio_review.py)

- `test_alternative_requires_grant_before_any_network`
- `test_authorized_route_uses_documented_audio_media_structure`
- `test_grant_cannot_cross_source_language_capability_or_budget`
- `test_grant_tampering_is_rejected`

### F · `test_authorized_eleven_tts.py`

[tests/test_authorized_eleven_tts.py](../../tests/test_authorized_eleven_tts.py)

- `test_no_implicit_model_fallback_or_network`
- `test_explicit_matching_grant_is_accepted_and_changed_scope_is_rejected`
- `test_budget_mismatch_is_rejected`
- `test_packet_checks_exact_script_and_price_reservation`
- `test_flash_alternative_requires_exact_model_grant_and_script`

### F · `test_authorized_flash_lite_tts.py`

[tests/test_authorized_flash_lite_tts.py](../../tests/test_authorized_flash_lite_tts.py)

- `test_scoped_authorization_exact_copy_and_provider_schema`

### F · `test_authorized_turbo_tts.py`

[tests/test_authorized_turbo_tts.py](../../tests/test_authorized_turbo_tts.py)

- `test_exact_copy_language_and_character_reservation_are_bound`

### F · `test_batch_production.py`

[tests/test_batch_production.py](../../tests/test_batch_production.py)

- `test_aggregate_reservation_prevents_per_locale_budget_multiplication`
- `test_orphan_reservation_and_removed_pointer_do_not_allow_duplicate_charge`
- `test_unknown_cost_stays_reserved_and_terminal_zero_releases_credit`
- `test_deleted_run_does_not_erase_settled_spend`
- `test_actual_over_estimate_blocks_next_job`
- `test_unregistered_journal_and_concurrent_lock_fail_closed`
- `test_pilot_and_master_change_revoke_batch_release`
- `test_direct_render_checks_batch_before_media_work`
- `test_fast_pilot_uses_current_basic_review_without_claiming_strict_audit`
- `test_model_task_budget_blocks_before_any_provider_call`
- `test_paid_invalid_json_counts_received_charge`
- `test_video_and_audio_analysis_share_the_same_batch_guard`
- `test_restored_run_pointer_is_provenance_not_old_batch_authority`
- `test_authorization_is_not_transferred_to_another_workspace`
- `test_create_batch_aliases_and_lower_reuse_limit`
- `test_nested_and_failed_stages_are_not_added_as_wall_time`
- `test_cli_waiting_states_are_not_reported_as_success`
- `test_synthetic_pipeline_keeps_rendered_bytes_and_resumes_without_encoding`
- `test_stale_explicit_plan_stops_without_silently_selecting_new_route`
- `test_resume_skips_only_render_and_never_skips_quality`

### F · `test_best_available_batch.py`

[tests/test_best_available_batch.py](../../tests/test_best_available_batch.py)

- `test_explicit_output_release_keeps_issues_and_rejects_master_inheritance`
- `test_changed_completed_video_revokes_release`
- `test_missing_or_invalid_completion_cannot_expand`
- `test_other_source_or_changed_evidence_is_rejected`
- `test_strict_child_cannot_inherit_best_available_scope`

### F · `test_captions.py`

[tests/test_captions.py](../../tests/test_captions.py)

- `test_actual_separate_translation_failure_is_rejected`
- `test_missing_caption_classification_cannot_silently_bypass_gate`
- `test_independent_button_does_not_need_to_repeat_narration`
- `test_uncaptioned_speech_requires_explicit_reason`
- `test_unknown_speech_cannot_be_marked_caption_not_applicable`
- `test_fragment_clipping_uses_segment_time_and_preserves_input`
- `test_numeric_and_word_changes_are_not_punctuation_normalization`
- `test_mixer_cannot_read_independent_retranslation`
- `test_real_mix_timing_shortens_display_but_retains_english_erase_window`
- `test_raw_tts_timeline_and_unreviewed_asr_are_rejected`
- `test_new_alignment_can_replace_old_bad_fragments_after_copy_revision`
- `test_alignment_cannot_drop_last_clause_or_use_overlapping_words`
- `test_aligned_av_review_passes_and_english_timing_lag_fails`
- `test_audio_only_sync_pass_does_not_prove_caption_sync`
- `test_changed_video_audio_and_caption_track_cannot_reuse_old_sync_review`
- `test_source_frame_is_not_candidate_caption_evidence`
- `test_real_renderer_capture_and_quality_gate`

### F · `test_codex_visual.py`

[tests/test_codex_visual.py](../../tests/test_codex_visual.py)

- `test_packet_requires_codex_observation_not_ocr_or_automatic_pass`
- `test_result_binds_real_output_and_never_approves_inventory`
- `test_missing_knowledge_or_changed_inputs_are_rejected`
- `test_image_task_rejects_missing_output_and_input_overwrite`

### F · `test_content_routing.py`

[tests/test_content_routing.py](../../tests/test_content_routing.py)

- `test_three_classes_keep_narration_and_dialogue_in_scope`
- `test_missing_type_domain_reasons_or_ineligible_choice_block_new_request`
- `test_caption_density_music_or_unknown_speech_cannot_fake_a_type`
- `test_fact_inference_prevents_role_tag_omission_without_guessing_genre`
- `test_complex_scene_keeps_required_methods_even_with_zero_optional_slots`
- `test_legacy_request_retains_absent_assessment_instead_of_fabricating_history`
- `test_new_fast_request_needs_assessment_and_freezes_snapshot_used_by_followup`
- `test_fast_feedback_and_archive_survive_outside_the_original_plan_location`
- `test_tampered_frozen_body_is_rejected_and_current_catalog_is_not_retroactive`

### F · `test_contracts.py`

[tests/test_contracts.py](../../tests/test_contracts.py)

- `test_audio_chat_accepts_documented_openai_response_and_rejects_business_error`
- `test_business_failure_is_not_http_success`
- `test_post_timeout_is_ambiguous_but_read_timeout_is_not`
- `test_missing_task_id_is_ambiguous`
- `test_pending_result_is_not_a_video`
- `test_run_path_traversal_is_rejected`
- `test_zero_clip_limit_is_rejected_instead_of_looping`
- `test_unreviewed_coverage_blocks_planning`
- `test_candidate_expired_scope_and_superseded_are_filtered`
- `test_blind_package_tampering_is_detected`
- `test_same_packet_does_not_charge_twice`
- `test_ambiguous_packet_is_not_automatically_retried`
- `test_budget_blocks_new_paid_request`
- `test_zero_cost_terminal_failure_allows_one_idempotent_explicit_retry`
- `test_ambiguous_or_billed_failure_cannot_use_zero_cost_retry`
- `test_pending_zero_does_not_release_credit_reservation`
- `test_singular_video_and_reference_image_assets_are_uploaded_and_bound`
- `test_estimated_cost_budget_blocks_overspend`

### F · `test_curation.py`

[tests/test_curation.py](../../tests/test_curation.py)

- `test_adoption_proposal_is_retained_but_never_activates`
- `test_unknown_adoption_target_rejected`
- `test_baseline_is_explicit_and_changes_are_incremental`
- `test_duplicates_preserve_all_sources_and_do_not_activate`
- `test_scope_widening_rejected_without_checkpoint_progress`
- `test_private_observations_cannot_be_merged_into_public_candidate`
- `test_private_candidate_is_stored_privately`
- `test_rule_changes_by_engine_rejected_before_candidate_write`
- `test_agent_contract_changes_reject_candidate_without_checkpoint_progress`
- `test_engine_failure_does_not_consume_event_and_releases_lock`
- `test_source_edit_during_reasoning_rejects_result`
- `test_unknown_or_duplicate_sources_rejected`
- `test_activation_fields_are_not_accepted_from_reasoning_engine`
- `test_pending_is_retained_without_repeated_inference_and_without_starvation`
- `test_revision_merge_keeps_prior_evidence_and_version`
- `test_checkpoint_write_failure_can_retry_cached_reasoning_idempotently`
- `test_time_zone_and_once_per_day_gate`
- `test_existing_lock_blocks_concurrent_sweep`
- `test_missing_checkpoint_is_not_silently_rebaselined`
- `test_prepare_and_apply_support_a_different_reasoning_provider`
- `test_cli_reasoning_has_no_media_keys_or_shell_tools`

### F · `test_delivery_folders.py`

[tests/test_delivery_folders.py](../../tests/test_delivery_folders.py)

- `test_named_sources_and_unregistered_legacy_source`
- `test_path_escape_reserved_name_and_case_collision_fail_closed`

### F · `test_delivery_index.py`

[tests/test_delivery_index.py](../../tests/test_delivery_index.py)

- `test_page_escapes_names_keeps_reference_status_and_does_not_copy_video`
- `test_changed_video_missing_file_and_escaping_path_are_not_linked`
- `test_catalog_cannot_relabel_reference_as_delivered`
- `test_invalid_manifest_is_diagnosed_and_html_escaped_without_link`
- `test_valid_delivery_and_empty_new_workspace`

### F · `test_duration_budget.py`

[tests/test_duration_budget.py](../../tests/test_duration_budget.py)

- `test_measured_duration_and_floor_no_minimum_or_locale_multiplier`
- `test_bad_duration_does_not_register_a_budget`
- `test_roles_locales_and_derived_clip_share_original_balance`
- `test_existing_ledger_does_not_reprice_or_clear_unknown_cost`
- `test_probe_failure_leaves_settled_reuse_request_open`
- `test_long_video_limits_and_role_jobs_are_finite_and_clamped_to_ledger`
- `test_long_intake_keeps_required_audio_and_extract_has_no_demo_duration_cap`

### F · `test_evidence_reuse.py`

[tests/test_evidence_reuse.py](../../tests/test_evidence_reuse.py)

- `test_unchanged_layers_skip_decoding_but_never_copy_reviews`
- `test_changed_target_decodes_only_changed_layer_and_matches_uncached_pixels`
- `test_local_pixel_change_reuses_other_pages_only_after_decoding_new_target`
- `test_missing_cached_pages_rebuild_but_corruption_is_rejected`
- `test_region_change_does_not_reuse_wrong_crops`
- `test_transparent_layer_reuse_matches_original_alpha_composition`
- `test_changed_frame_rate_reuses_actual_source_indices_without_dropping_pages`
- `test_partial_cache_miss_decodes_only_missing_frames`
- `test_cache_indexes_do_not_make_new_evidence_depend_on_old_run`
- `test_clock_cache_corruption_is_not_silently_trusted`
- `test_unrelated_code_does_not_invalidate_render_dependencies`
- `test_link_fallback_reports_copy_without_altering_pixels`
- `test_metadata_publication_merges_concurrent_snapshots_and_preserves_previous_on_failure`
- `test_source_changed_during_probe_does_not_publish_clock_cache`
- `test_memory_tiles_are_bounded_copied_and_still_detect_file_tampering`
- `test_render_signature_does_not_make_optional_pillow_mandatory`

### F · `test_failure_closure.py`

[tests/test_failure_closure.py](../../tests/test_failure_closure.py)

- `test_preproduction_failure_is_idempotent_and_survives_run_deletion`
- `test_changed_failure_creates_new_case_without_overwriting_old`
- `test_missing_tampered_outside_evidence_and_empty_scope_reject`
- `test_existing_candidate_requires_normal_reflect_and_budgets_untouched`

### F · `test_fast_delivery.py`

[tests/test_fast_delivery.py](../../tests/test_fast_delivery.py)

- `test_missing_tail_cannot_pass_even_with_pass_checkbox`
- `test_changed_video_requires_new_observations`
- `test_changed_evidence_invalidates_check`
- `test_missing_motion_review_is_not_metadata_pass`
- `test_minor_finish_passes_but_major_and_missing_playback_do_not`
- `test_finish_score_rejects_bool_nan_and_low_score`
- `test_minor_finish_never_waives_basic_defect`
- `test_native_mapping_rejects_short_clip_and_fps_changes`
- `test_current_frame_graphics_restore_exactly`
- `test_lower_budget_retains_unknown_and_rejects_dispatched_recovery`

### F · `test_feedback.py`

[tests/test_feedback.py](../../tests/test_feedback.py)

- `test_repeating_packet_reuses_task`
- `test_ambiguous_post_cannot_be_resubmitted`
- `test_video_jobs_consume_the_same_budget`
- `test_changed_source_rejected_before_create`
- `test_user_cost_guard_blocks_new_seedance_and_expensive_trials`
- `test_invalid_audio_reply_still_preserves_raw_receipt`
- `test_tts_retranslation_is_blocked_before_paid_creation`
- `test_tts_missing_final_speech_binding_is_blocked_before_creation`
- `test_paid_result_reuse_requires_identical_request_and_assets`
- `test_wan_flash_probe_reserves_actual_price_and_cannot_enable_audio`
- `test_prepared_master_cannot_reuse_another_source_or_target_lettering`
- `test_approved_reference_scope_does_not_leak_to_other_source_or_language`
- `test_overlay_cannot_cover_an_observed_info_icon`
- `test_source_banner_stays_restored_when_picture_ends_before_edit`
- `test_regional_model_composite_preserves_pixels_outside_text`
- `test_seedance_packet_uses_its_15s_contract_instead_of_wan_limit`

### F · `test_finalization.py`

[tests/test_finalization.py](../../tests/test_finalization.py)

- `test_missing_translation_and_changed_evidence_are_rejected`
- `test_subtitled_result_delivered_without_relabeling_quality_or_reuse`
- `test_unplayable_output_is_not_published`
- `test_identical_hardlinked_candidate_and_final_can_be_archived`
- `test_new_request_finalization_keeps_selection_without_claiming_quality`
- `test_required_audio_blocks_subtitle_fallback_but_allows_actual_dubbing_review`

### F · `test_incremental_repair.py`

[tests/test_incremental_repair.py](../../tests/test_incremental_repair.py)

- `test_boundary_edit_recomputes_only_affected_frame_and_matches_fresh`
- `test_changed_parameters_invalidate_active_frames_only`
- `test_poisson_patch_is_explicit_experimental_and_keeps_protected_pixels`
- `test_missing_old_master_recomputes_but_corruption_is_rejected`
- `test_source_restore_and_horizontal_fill_preserve_protected_pixels`
- `test_explicit_frame_boundary_avoids_rounded_container_timestamps`
- `test_engine_and_source_change_invalidate_all_frames`
- `test_changed_donor_invalidates_active_frames_and_index_tamper_blocks`
- `test_expired_exact_checkpoint_rebuilds_without_overwriting_history`

### F · `test_kie_audio_routes.py`

[tests/test_kie_audio_routes.py](../../tests/test_kie_audio_routes.py)

- `test_current_flash_endpoint_keeps_both_actual_media_urls`
- `test_unavailable_old_flash_is_rejected_before_network`
- `test_provider_error_preserves_redacted_body_and_marks_524_unknown`

### F · `test_knowledge_evidence.py`

[tests/test_knowledge_evidence.py](../../tests/test_knowledge_evidence.py)

- `test_new_method_cannot_claim_an_unpackaged_reference`
- `test_named_evidence_is_verified_and_method_is_feature_scoped`
- `test_multi_source_claim_cannot_use_only_one_source`
- `test_required_supplement_is_not_a_silent_optional_file`
- `test_supplement_survives_original_run_and_missing_file_is_detected`
- `test_invalid_content_features_do_not_silently_become_characters`
- `test_inventory_features_are_used_without_copying_source_identity`
- `test_source_reference_does_not_enter_general_method_retrieval`
- `test_actual_method_catalog_has_no_video_scope`
- `test_external_workspace_can_audit_without_runtime_data_or_secrets`

### F · `test_knowledge_lifecycle.py`

[tests/test_knowledge_lifecycle.py](../../tests/test_knowledge_lifecycle.py)

- `test_scoped_advisory_is_separate_and_never_activates`
- `test_generic_candidate_needs_explicit_features`
- `test_distillation_and_original_do_not_repeat_the_same_evidence`
- `test_private_public_copies_are_one_observation`
- `test_partial_adoption_cannot_archive`
- `test_promoted_candidate_source_hash_is_audited`
- `test_mcp_exposes_separate_advisory_queue_and_actual_use`
- `test_closed_candidate_leaves_queue_but_retains_original_and_history`
- `test_stale_review_and_changed_target_block_archive`
- `test_archive_tampering_is_detected_and_portable`
- `test_actual_feedback_survives_run_and_reaches_revision_queue`
- `test_stale_video_unselected_method_and_missing_evidence_reject`
- `test_new_plan_cannot_claim_use_against_an_old_render`
- `test_reviewed_feedback_closes_alert_without_erasing_observation`
- `test_explicit_nonuse_is_not_success_and_new_video_needs_new_feedback`

### F · `test_knowledge_maintenance.py`

[tests/test_knowledge_maintenance.py](../../tests/test_knowledge_maintenance.py)

- `test_compaction_preserves_manifests_and_is_portable_and_idempotent`
- `test_tampering_and_missing_object_fail_closed`
- `test_storage_escape_and_wrong_alias_hash_are_rejected`
- `test_stale_preview_does_not_delete`
- `test_dangling_alias_fails`
- `test_candidate_index_preserves_status_scope_outcome_and_partial_adoption`
- `test_reviewed_synthetic_and_archive_records_are_not_adoptions`

### F · `test_knowledge_routing.py`

[tests/test_knowledge_routing.py](../../tests/test_knowledge_routing.py)

- `test_observed_feature_aliases_reach_conditional_methods_without_changing_inventory`
- `test_required_policies_survive_method_limit_and_scope_still_applies`
- `test_alias_cycles_are_rejected`
- `test_promoted_any_feature_method_keeps_and_conditions_and_supersedes`
- `test_malformed_feature_conditions_fail_closed`
- `test_speaker_synonym_selects_detailed_method_without_inventing_a_scene`
- `test_delivery_modes_and_exact_vs_reviewed_base_locale`
- `test_related_locale_is_discovery_only_and_does_not_cross_sources`

### F · `test_languages.py`

[tests/test_languages.py](../../tests/test_languages.py)

- `test_all_user_aliases_and_display_names_resolve`
- `test_business_aliases_and_explicit_unlisted_locales`
- `test_unknown_names_and_conflicting_dictionary_are_rejected`
- `test_new_request_normalizes_target_and_preserves_original_without_a_real_video`
- `test_existing_workspace_without_dictionary_keeps_language_tags`
- `test_language_policy_does_not_compete_with_production_methods`

### F · `test_local_tts.py`

[tests/test_local_tts.py](../../tests/test_local_tts.py)

- `test_existing_takes_reuse_but_new_or_changed_copy_requires_gemini`
- `test_speed_and_model_changes_cannot_reuse_old_takes`
- `test_tampered_or_missing_output_cannot_reuse_or_regenerate`
- `test_partial_wav_without_receipt_cannot_reuse_or_regenerate`
- `test_language_speed_and_selection_are_validated`
- `test_missing_legacy_voice_assets_do_not_trigger_installation`
- `test_engine_and_phoneme_changes_invalidate_or_reject`

### F · `test_long_audio.py`

[tests/test_long_audio.py](../../tests/test_long_audio.py)

- `test_full_duration_and_late_dropout_are_checked`
- `test_audio_segment_after_old_181_second_boundary_is_available`

### F · `test_maintenance.py`

[tests/test_maintenance.py](../../tests/test_maintenance.py)

- `test_cache_waits_for_delivery_and_is_idempotent`
- `test_reference_and_changed_bytes_are_kept`
- `test_run_relative_reference_is_kept`
- `test_unsettled_job_and_active_work_prevent_cleanup`
- `test_targets_outside_owned_scratch_rejected`
- `test_closure_uses_current_preservation_fingerprint`
- `test_guarded_stage_runs_hook_once_and_keeps_result`
- `test_cleanup_error_is_reported_without_affecting_delivery`
- `test_intermediate_stage_does_not_delete_cache_after_old_delivery`
- `test_changed_delivery_is_not_a_cache_release_signal`
- `test_real_preservation_keeps_independent_package_after_run_retirement`

### F · `test_model_installation_policy.py`

[tests/test_model_installation_policy.py](../../tests/test_model_installation_policy.py)

- `test_retired_asr_cannot_download_or_create_model_directory`
- `test_default_asr_download_is_small_and_complete_assets_are_reused`
- `test_historical_asr_integrity_can_be_read_without_reenabling_installation`
- `test_generic_downloader_rejects_retired_or_unregistered_assets_before_io`
- `test_install_plan_rejects_a_retired_model_added_to_manifest`
- `test_stale_policy_cannot_reenable_retired_installers`
- `test_public_plan_lists_only_current_local_models_without_installing`
- `test_retired_voice_install_has_no_cli_or_python_entry`
- `test_installer_model_override_is_rejected_by_argument_parser`
- `test_setup_rejects_removed_model_parameter_before_running_installer`
- `test_vision_dependencies_do_not_fall_back_to_retired_ocr_installation`

### F · `test_model_routing.py`

[tests/test_model_routing.py](../../tests/test_model_routing.py)

- `test_new_plan_and_demo_reject_retired_generation_route_at_argument_parsing`
- `test_retired_video_models_are_rejected_before_network`
- `test_single_video_and_tts_models_are_accepted`
- `test_audio_default_is_flash_and_pro_does_not_silently_fallback`
- `test_retired_task_polling_remains_available`
- `test_retired_asr_size_is_blocked_before_download_or_inference`

### F · `test_multilingual.py`

[tests/test_multilingual.py](../../tests/test_multilingual.py)

- `test_character_voice_review_uses_real_comparison_and_rejects_inconsistent_assignments`
- `test_japanese_comparison_does_not_request_chinese_translation`
- `test_candidate_transcription_sends_only_actual_candidate`
- `test_upload_retry_preserves_failure_and_does_not_repeat_paid_post`
- `test_upload_retry_rejects_ambiguous_paid_model_request`
- `test_audio_request_has_a_specific_supported_model_and_longer_timeout`
- `test_foreground_card_keeps_pixels_while_translated_text_remains_visible`

### F · `test_neutral_reuse.py`

[tests/test_neutral_reuse.py](../../tests/test_neutral_reuse.py)

- `test_reuse_copies_bound_evidence_keeps_target_decisions_and_survives_source_changes`
- `test_different_source_or_timeline_does_not_import`

### F · `test_neutral_visual_gate.py`

[tests/test_neutral_visual_gate.py](../../tests/test_neutral_visual_gate.py)

- `test_failed_and_unreviewed_archives_remain_readable_but_cannot_render`
- `test_boolean_approval_without_review_is_insufficient`
- `test_renderer_stops_before_media_work_for_unapproved_master`
- `test_foreground_failure_and_wrong_video_are_rejected`
- `test_bound_pass_and_tampered_evidence`
- `test_review_evidence_must_survive_archive_closure`
- `test_reviewed_master_and_evidence_are_in_asset_closure`

### F · `test_ocr_cache.py`

[tests/test_ocr_cache.py](../../tests/test_ocr_cache.py)

- `test_compatibility_entry_prepares_codex_without_loading_ocr`
- `test_exact_pixels_reuse_but_one_pixel_difference_does_not`
- `test_track_summary_preserves_gaps_duplicate_positions_and_raw_frames`
- `test_cache_requires_complete_matching_model_source_and_parameters`

### F · `test_ocr_supplement.py`

[tests/test_ocr_supplement.py](../../tests/test_ocr_supplement.py)

- `test_enabled_configuration_cannot_restart_retired_inference`
- `test_historical_evidence_is_read_only_and_never_approval`
- `test_no_history_still_routes_to_codex`

### F · `test_production_recovery.py`

[tests/test_production_recovery.py](../../tests/test_production_recovery.py)

- `test_unreleased_master_resumes_review_instead_of_restarting_source`
- `test_reviewed_master_resumes_planning_without_creating_approval`
- `test_failed_unknown_charge_and_draft_are_visible_but_not_final`
- `test_partial_coverage_stays_at_source`
- `test_early_reflection_returns_resume_guidance_without_inventing_evidence`
- `test_pending_provider_task_resumes_polling_not_translation`
- `test_review_and_delivery_guidance_does_not_start_another_render`
- `test_unplanned_diagnostics_must_rejoin_formal_flow`

### F · `test_project_runtime.py`

[tests/test_project_runtime.py](../../tests/test_project_runtime.py)

- `test_caches_and_media_path_stay_in_project`
- `test_model_download_is_hash_checked_and_existing_model_is_not_overwritten`
- `test_complete_asr_model_can_be_used_without_writing_download_lock`

### F · `test_quality_holds.py`

[tests/test_quality_holds.py](../../tests/test_quality_holds.py)

- `test_rejected_delivery_is_not_shown_as_accepted`
- `test_rejected_package_remains_recoverable_but_not_production_eligible`
- `test_hold_survives_package_removal_and_does_not_block_different_video`
- `test_missing_or_tampered_notice_blocks_instead_of_restoring_old_pass`
- `test_old_approval_cannot_bypass_production_or_delivery`
- `test_record_is_idempotent_independent_and_rejects_changed_event`
- `test_new_candidate_cannot_bypass_a_held_master_in_an_old_plan`
- `test_reuse_eligibility_checks_neutral_assets_separately_from_final_video`

### F · `test_repair_and_compaction.py`

[tests/test_repair_and_compaction.py](../../tests/test_repair_and_compaction.py)

- `test_diagnostic_files_do_not_invalidate_render_but_bound_asset_change_is_rejected`
- `test_pixel_reuse_survives_removal_of_origin_without_linking_review_state`
- `test_render_dependency_distinguishes_workspace_knowledge_from_run_media`
- `test_audio_review_receipt_does_not_invalidate_render_but_selected_model_does`
- `test_preflight_covers_source_entry_and_shot_cut_separately`
- `test_donor_cannot_cross_pose_cut`
- `test_interrupted_local_repair_requires_dead_owner_and_does_not_retry_models`
- `test_bounded_learning_keeps_all_explicit_failure_frames`
- `test_prune_requires_matching_preview_and_keeps_current_pictures_and_observations`
- `test_recipe_lossless_output_preserves_unmasked_pixels_and_checkpoint`

### F · `test_repair_selectors.py`

[tests/test_repair_selectors.py](../../tests/test_repair_selectors.py)

- `test_explicit_white_components_and_protection_never_escape_region`
- `test_invalid_selector_and_unknown_settings_reject`
- `test_legacy_lama_recipe_is_rejected_before_model_execution`

### F · `test_repository_check.py`

[tests/test_repository_check.py](../../tests/test_repository_check.py)

- `test_existing_local_report_is_not_a_valid_portable_document_link`
- `test_agent_pointer_must_resolve_inside_the_portable_package`
- `test_retired_body_remains_portable_and_replacement_must_resolve`

### F · `test_request_budget.py`

[tests/test_request_budget.py](../../tests/test_request_budget.py)

- `test_new_runs_and_new_first_request_ids_cannot_replenish`
- `test_derived_clip_inherits_parent_and_cannot_open_another_first_allowance`
- `test_one_host_event_cannot_open_budget_for_another_source`
- `test_reuse_requires_new_user_event_and_reconciliation`
- `test_direct_provider_call_and_repeated_post_are_blocked_before_transport`
- `test_existing_unbound_runs_are_imported_before_new_first_run_can_spend`
- `test_settled_historical_receipts_are_not_rebilled_in_a_new_reuse_request`
- `test_restored_receipts_deduplicate_but_distinct_actual_tasks_do_not`
- `test_missing_journal_after_reservation_and_deleted_run_keep_the_charge`

### F · `test_request_model_authorization.py`

[tests/test_request_model_authorization.py](../../tests/test_request_model_authorization.py)

- `test_alternative_is_blocked_without_the_bound_human_authorization`
- `test_authorization_is_limited_to_one_budget_source_model_and_run`

### F · `test_request_tts.py`

[tests/test_request_tts.py](../../tests/test_request_tts.py)

- `test_request_authorization_and_exact_script_are_required`

### F · `test_resources.py`

[tests/test_resources.py](../../tests/test_resources.py)

- `test_busy_is_recoverable_without_removing_owner_lock`
- `test_low_space_stops_before_work_and_preserves_existing_outputs`
- `test_model_resume_does_not_download_complete_model_again`
- `test_partial_download_has_no_success_receipt_and_can_resume`

### F · `test_reuse_budget.py`

[tests/test_reuse_budget.py](../../tests/test_reuse_budget.py)

- `test_character_voice_override_requires_source_binding_and_stays_bounded`
- `test_new_reuse_defaults_to_40_but_explicit_historical_budget_stays_bound`

### F · `test_revision_budget.py`

[tests/test_revision_budget.py](../../tests/test_revision_budget.py)

- `test_provenance_only_rebinding_does_not_spend_a_picture_revision`
- `test_fourth_distinct_picture_is_still_blocked`
- `test_copy_speech_or_audio_changes_are_not_provenance_rebindings`
- `test_missing_frozen_inventory_is_counted_conservatively`

### F · `test_source_retention.py`

[tests/test_source_retention.py](../../tests/test_source_retention.py)

- `test_new_locale_reuses_extraction_after_old_run_is_removed`
- `test_changed_source_is_not_a_cache_hit`
- `test_optional_ocr_candidates_survive_source_snapshot_without_new_locale_approval`
- `test_corrupt_source_snapshot_does_not_fall_back_silently`
- `test_adaptive_ocr_backlog_survives_source_snapshot`
- `test_existing_inventory_is_never_overwritten`
- `test_changed_extraction_parameters_require_new_extraction`
- `test_source_ocr_and_speech_observations_survive_without_old_target`
- `test_source_ocr_cannot_be_borrowed_from_another_video`
- `test_recorded_extraction_settings_survive_later_config_change`
- `test_delete_defaults_to_preview_and_requires_preservation`
- `test_delete_keeps_observations_source_and_queue`
- `test_mutation_after_preservation_blocks_deletion`
- `test_unsettled_task_and_unknown_billing_block_preservation`
- `test_active_operation_lock_prevents_deletion`
- `test_external_live_reference_blocks_run_deletion`
- `test_original_task_script_is_independent_evidence_after_deletion`
- `test_unknown_cost_report_blocks_deletion`
- `test_missing_permanent_evidence_blocks_deletion`
- `test_stale_preview_cannot_delete_a_preserved_revision`
- `test_delete_target_cannot_be_a_different_directory`

### F · `test_storage.py`

[tests/test_storage.py](../../tests/test_storage.py)

- `test_delivery_restores_prepared_asset_without_original_run`
- `test_registered_demand_name_is_used_by_export_and_lookup`
- `test_knowledge_survives_expiry_of_both_runs_and_outputs`
- `test_missing_evidence_blocks_retrieval_instead_of_silent_knowledge_loss`
- `test_mutating_run_does_not_mutate_permanent_evidence`
- `test_cross_source_assets_rejected_and_no_partial_catalog_entry`
- `test_archive_idempotence_and_expired_catalog`
- `test_historical_revise_reference_is_not_upgraded_to_delivered`
- `test_bundle_rejects_path_escape_and_restore_overwrite`
- `test_pending_learning_is_idempotent_and_never_activated`
- `test_project_method_rejects_a_private_evidence_dependency`
- `test_published_project_method_works_without_private_or_runtime_files`
- `test_technical_candidate_keeps_its_business_content`
- `test_modified_manifest_is_not_an_available_reuse_package`
- `test_frozen_ancestor_paths_are_not_live_preparation_dependencies`
- `test_context_returns_asset_catalog_separately_from_knowledge`

### F · `test_storage_policy.py`

[tests/test_storage_policy.py](../../tests/test_storage_policy.py)

- `test_user_override_preserves_defaults_and_is_never_delete_mode`
- `test_invalid_or_nonfinite_limits_do_not_write`
- `test_preview_flags_limits_and_retains_locked_unknown_and_unfinished_tasks`
- `test_loose_zip_counts_towards_capacity_not_delivery_count`
- `test_pinned_source_is_protected_even_after_quality_pass`
- `test_catalog_cannot_escape_outputs`
- `test_report_tolerates_file_disappearing_during_scan`
- `test_report_separates_installed_models_from_scratch_without_deleting`

### F · `test_surface.py`

[tests/test_surface.py](../../tests/test_surface.py)

- `test_changed_copy_motion_or_locale_cannot_reuse_old_transparent_layer`
- `test_transparent_layer_preserves_source_pixels_outside_glyph_region`

### F · `test_version_retention.py`

[tests/test_version_retention.py](../../tests/test_version_retention.py)

- `test_preview_then_delete_retains_independent_failure_evidence`
- `test_current_dependency_and_another_run_hash_are_protected`
- `test_missing_evidence_changed_preview_and_unsettled_block`
- `test_no_automatic_failure_inference_or_empty_evidence`
- `test_failed_request_without_task_id_still_has_unknown_cost`
- `test_request_reservation_without_job_file_is_not_lost`
- `test_active_heavy_work_and_missing_archive_block_deletion`
- `test_reference_scan_keeps_cross_run_audio_and_nested_provenance`
- `test_local_comparison_page_ids_do_not_trigger_filesystem_resolution`

### F · `test_visual_audit.py`

[tests/test_visual_audit.py](../../tests/test_visual_audit.py)

- `test_pending_native_evidence_and_boundary_coverage_do_not_change_video`
- `test_per_instance_observation_pass_staleness_and_tampered_evidence`
- `test_changed_copy_invalidates_review_even_when_video_is_unchanged`
- `test_missing_frames_and_fake_na_are_rejected`
- `test_neutral_release_requires_individual_review_and_is_portable`
- `test_pilot_cannot_use_old_quality_pass_without_visual_observations`
- `test_identical_neutral_bytes_in_two_shots_keep_separate_interval_reviews`
- `test_bulk_pass_submission_is_rejected`
- `test_identical_boilerplate_cannot_approve_two_instances`
- `test_new_failed_neutral_observation_revokes_release_without_touching_old_record`
- `test_layer_change_invalidates_final_even_without_reencoding`
- `test_quality_objection_blocks_neutral_release_even_with_complete_observations`
- `test_frame_policy_static_is_bounded_and_motion_is_continuous`
- `test_compact_storage_keeps_identical_native_pages_and_legacy_bundle`
- `test_concise_notes_preserve_explicit_coverage_and_verify_once`
- `test_minimal_failure_revokes_pass_without_fabricated_observations`
- `test_native_gallery_preserves_pixels_and_does_not_approve`
- `test_layer_selection_uses_actual_strip_order_and_returns_cursor`
- `test_multicolumn_gallery_keeps_all_native_pixels_and_frame_ids`
- `test_v3_reuses_identical_pixels_but_new_video_has_no_inherited_review`

### F · `test_workflow_optimization.py`

[tests/test_workflow_optimization.py](../../tests/test_workflow_optimization.py)

- `test_all_masters_are_gated_before_rendering_first_segment`
- `test_segment_cache_reuses_visuals_across_audio_change_but_not_text_change`
- `test_work_packet_preserves_ambiguous_jobs_and_does_not_approve`

### F · `test_workspace_export.py`

[tests/test_workspace_export.py](../../tests/test_workspace_export.py)

- `test_fresh_export_preserves_public_bytes_and_excludes_development_data`
- `test_export_cannot_overwrite_or_nest_into_preserved_data`
- `test_nested_configuration_and_context_survive_init_and_export`
- `test_initialization_cannot_reenter_public_or_production_trees`
- `test_verify_detects_tampered_code_and_allows_new_task_data`
- `test_source_link_cannot_export_private_data`
- `test_storage_report_measures_overlap_without_deleting_independent_copies`

