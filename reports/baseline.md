# Eval report: `baseline`

20 scenarios, models: rules, run 2026-11-17T01:05:09

| Metric | Value |
|---|---|
| Fully correct (category + node + column) | **50%** |
| Category accuracy | 75% |
| Root-cause node accuracy | 70% |
| Column accuracy | 80% |
| Valid JSON replies | 100% |
| Mean latency | 0.0 s |
| Tokens (prompt / completion) | None / None |

## By category

| Category | Fully correct |
|---|---|
| out_of_range | 60% |
| null_values | 67% |
| schema_drift | 50% |
| type_mismatch | 33% |
| sql_logic_error | 40% |

## Scenarios

| Scenario | Expected | Diagnosed | OK |
|---|---|---|---|
| drift_artists_renamed | schema_drift @ raw_tracks [artists] | schema_drift @ raw_tracks [artists] | yes |
| drift_energy_renamed | schema_drift @ raw_tracks [energy] | schema_drift @ raw_tracks [energy] | yes |
| drift_tempo_renamed | schema_drift @ raw_tracks [tempo] | sql_logic_error @ stg_tracks [tempo] | no |
| drift_valence_dropped | schema_drift @ raw_tracks [valence] | sql_logic_error @ int_tracks_enriched [valence] | no |
| null_danceability | null_values @ raw_tracks [danceability] | null_values @ raw_tracks [danceability] | yes |
| null_energy_small | null_values @ raw_tracks [energy] | sql_logic_error @ mart_top_artists [energy] | no |
| null_popularity | null_values @ raw_tracks [popularity] | null_values @ raw_tracks [popularity] | yes |
| oor_acousticness_sentinel | out_of_range @ raw_tracks [acousticness] | out_of_range @ raw_tracks [acousticness] | yes |
| oor_energy_percent | out_of_range @ raw_tracks [energy] | out_of_range @ raw_tracks [energy] | yes |
| oor_loudness_sign_flip | out_of_range @ raw_tracks [loudness] | sql_logic_error @ int_tracks_enriched [loudness] | no |
| oor_popularity_overflow | out_of_range @ raw_tracks [popularity] | out_of_range @ raw_tracks [popularity] | yes |
| oor_valence_partial_scale | out_of_range @ raw_tracks [valence] | sql_logic_error @ mart_top_artists [valence] | no |
| sql_abs_loudness | sql_logic_error @ stg_tracks [loudness] | sql_logic_error @ mart_top_artists [loudness] | no |
| sql_energy_rescaled_in_staging | sql_logic_error @ stg_tracks [energy] | sql_logic_error @ stg_tracks [energy] | yes |
| sql_mart_column_typo | sql_logic_error @ mart_top_artists [artist_names] | sql_logic_error @ mart_top_artists [artist_name] | no |
| sql_removed_tempo_filter | sql_logic_error @ stg_tracks [tempo] | sql_logic_error @ stg_tracks [tempo] | yes |
| sql_typo_valence | sql_logic_error @ int_tracks_enriched [valence] | sql_logic_error @ int_tracks_enriched [valance] | no |
| type_duration_suffix | type_mismatch @ raw_tracks [duration_ms] | type_mismatch @ raw_tracks [None] | no |
| type_popularity_text | type_mismatch @ raw_tracks [popularity] | type_mismatch @ raw_tracks [popularity] | yes |
| type_tempo_units | type_mismatch @ raw_tracks [tempo] | type_mismatch @ raw_tracks [None] | no |
