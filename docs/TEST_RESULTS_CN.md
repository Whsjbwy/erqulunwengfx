# 完整测试结果

日期：2026-11-10；Python 3.11.15，pytest 9.2.0。

实际命令：`python -m pytest -v --tb=short --color=no`。

退出码：0；85 passed in 3.17s。下表由本次真实输出提取。

| 测试（含参数化用例） | 状态 |
| --- | --- |
| `tests/test_collision_checker.py::test_empty_map_accepts_segments[start0-end0]` | PASSED |
| `tests/test_collision_checker.py::test_empty_map_accepts_segments[start1-end1]` | PASSED |
| `tests/test_collision_checker.py::test_empty_map_accepts_segments[start2-end2]` | PASSED |
| `tests/test_collision_checker.py::test_empty_map_accepts_segments[start3-end3]` | PASSED |
| `tests/test_collision_checker.py::test_single_voxel_collision_has_physical_evidence` | PASSED |
| `tests/test_collision_checker.py::test_face_edge_corner_and_zero_length_contacts_collide[start0-end0]` | PASSED |
| `tests/test_collision_checker.py::test_face_edge_corner_and_zero_length_contacts_collide[start1-end1]` | PASSED |
| `tests/test_collision_checker.py::test_face_edge_corner_and_zero_length_contacts_collide[start2-end2]` | PASSED |
| `tests/test_collision_checker.py::test_face_edge_corner_and_zero_length_contacts_collide[start3-end3]` | PASSED |
| `tests/test_collision_checker.py::test_face_edge_corner_and_zero_length_contacts_collide[start4-end4]` | PASSED |
| `tests/test_collision_checker.py::test_face_edge_corner_and_zero_length_contacts_collide[start5-end5]` | PASSED |
| `tests/test_collision_checker.py::test_face_edge_corner_and_zero_length_contacts_collide[start6-end6]` | PASSED |
| `tests/test_collision_checker.py::test_obstacle_endpoint_is_checked[False]` | PASSED |
| `tests/test_collision_checker.py::test_obstacle_endpoint_is_checked[True]` | PASSED |
| `tests/test_collision_checker.py::test_outside_domain_is_invalid[point0]` | PASSED |
| `tests/test_collision_checker.py::test_outside_domain_is_invalid[point1]` | PASSED |
| `tests/test_collision_checker.py::test_outside_domain_is_invalid[point2]` | PASSED |
| `tests/test_collision_checker.py::test_outside_domain_is_invalid[point3]` | PASSED |
| `tests/test_collision_checker.py::test_malformed_paths_have_explicit_status[points0]` | PASSED |
| `tests/test_collision_checker.py::test_malformed_paths_have_explicit_status[points1]` | PASSED |
| `tests/test_collision_checker.py::test_malformed_paths_have_explicit_status[points2]` | PASSED |
| `tests/test_collision_checker.py::test_malformed_paths_have_explicit_status[points3]` | PASSED |
| `tests/test_collision_checker.py::test_malformed_paths_have_explicit_status[points4]` | PASSED |
| `tests/test_collision_checker.py::test_all_invalid_segments_are_counted_once` | PASSED |
| `tests/test_collision_checker.py::test_supercover_includes_all_cells_at_simultaneous_corner_crossing` | PASSED |
| `tests/test_collision_checker.py::test_anisotropic_spacing_and_shifted_origin` | PASSED |
| `tests/test_collision_checker.py::test_plane_tolerance_is_conservative_and_explicit` | PASSED |
| `tests/test_collision_checker.py::test_supercover_matches_independent_slab_oracle_and_reversal` | PASSED |
| `tests/test_collision_checker.py::test_small_diagonal_crossing_cannot_skip_thin_occupied_cell` | PASSED |
| `tests/test_crosscheck.py::test_empty_map_has_no_sampled_collisions` | PASSED |
| `tests/test_crosscheck.py::test_vtk_hit_reports_interior_penetration_and_actual_cell_id` | PASSED |
| `tests/test_crosscheck.py::test_sampling_narrow_obstacle_with_explicitly_fine_spacing` | PASSED |
| `tests/test_crosscheck.py::test_endpoints_and_zero_length_are_queried` | PASSED |
| `tests/test_crosscheck.py::test_outside_samples_are_reported` | PASSED |
| `tests/test_crosscheck.py::test_invalid_sample_spacing_is_rejected[0]` | PASSED |
| `tests/test_crosscheck.py::test_invalid_sample_spacing_is_rejected[-1]` | PASSED |
| `tests/test_crosscheck.py::test_invalid_sample_spacing_is_rejected[nan]` | PASSED |
| `tests/test_crosscheck.py::test_invalid_sample_spacing_is_rejected[inf]` | PASSED |
| `tests/test_crosscheck.py::test_boundary_hit_is_not_counted_as_interior` | PASSED |
| `tests/test_diagnostics.py::test_rejects_colliding_parent_candidate_edges` | PASSED |
| `tests/test_diagnostics.py::test_strict_links_check_interiors_endpoints_and_bounds[first0-second0]` | PASSED |
| `tests/test_diagnostics.py::test_strict_links_check_interiors_endpoints_and_bounds[first1-second1]` | PASSED |
| `tests/test_diagnostics.py::test_strict_links_check_interiors_endpoints_and_bounds[first2-second2]` | PASSED |
| `tests/test_diagnostics.py::test_strict_links_check_interiors_endpoints_and_bounds[first3-second3]` | PASSED |
| `tests/test_diagnostics.py::test_visible_goal_emits_a_recorded_zero_cost_candidate` | PASSED |
| `tests/test_diagnostics.py::test_smoothing_rolls_back_when_the_complete_path_is_invalid` | PASSED |
| `tests/test_diagnostics.py::test_smoothing_rejects_an_already_invalid_input` | PASSED |
| `tests/test_diagnostics.py::test_smoothing_rollback_survives_in_place_backend_changes` | PASSED |
| `tests/test_diagnostics.py::test_context_restores_all_functions_after_an_exception` | PASSED |
| `tests/test_diagnostics.py::test_prepare_copies_only_source_and_changes_one_capacity_value[1]` | PASSED |
| `tests/test_diagnostics.py::test_prepare_copies_only_source_and_changes_one_capacity_value[3]` | PASSED |
| `tests/test_diagnostics.py::test_prepare_copies_only_source_and_changes_one_capacity_value[5]` | PASSED |
| `tests/test_diagnostics.py::test_prepare_never_overwrites_an_existing_directory` | PASSED |
| `tests/test_diagnostics.py::test_prepare_rejects_author_or_repository_subdirectories[source]` | PASSED |
| `tests/test_diagnostics.py::test_prepare_rejects_author_or_repository_subdirectories[repository]` | PASSED |
| `tests/test_diagnostics.py::test_prepare_rejects_unsupported_capacities[0]` | PASSED |
| `tests/test_diagnostics.py::test_prepare_rejects_unsupported_capacities[2]` | PASSED |
| `tests/test_diagnostics.py::test_prepare_rejects_unsupported_capacities[10]` | PASSED |
| `tests/test_map_reader.py::test_read_map_preserves_vtk_cell_order_and_geometry` | PASSED |
| `tests/test_map_reader.py::test_nonzero_vtk_extent_uses_physical_minimum_corner` | PASSED |
| `tests/test_map_reader.py::test_missing_file_is_explicit` | PASSED |
| `tests/test_map_reader.py::test_nonbinary_map_is_rejected[2]` | PASSED |
| `tests/test_map_reader.py::test_nonbinary_map_is_rejected[-1]` | PASSED |
| `tests/test_map_reader.py::test_nonbinary_map_is_rejected[nan]` | PASSED |
| `tests/test_map_reader.py::test_nonbinary_map_is_rejected[inf]` | PASSED |
| `tests/test_map_reader.py::test_missing_cell_field_is_rejected` | PASSED |
| `tests/test_map_reader.py::test_rotated_map_is_rejected` | PASSED |
| `tests/test_map_reader.py::test_nonvolume_map_is_rejected` | PASSED |
| `tests/test_map_reader.py::test_nonpositive_spacing_is_rejected` | PASSED |
| `tests/test_map_reader.py::test_multicomponent_cell_field_is_rejected` | PASSED |
| `tests/test_map_reader.py::test_invalid_map_geometry_is_rejected[occupancy0-origin0-spacing0]` | PASSED |
| `tests/test_map_reader.py::test_invalid_map_geometry_is_rejected[occupancy1-origin1-spacing1]` | PASSED |
| `tests/test_map_reader.py::test_invalid_map_geometry_is_rejected[occupancy2-origin2-spacing2]` | PASSED |
| `tests/test_map_reader.py::test_invalid_map_geometry_is_rejected[occupancy3-origin3-spacing3]` | PASSED |
| `tests/test_map_reader.py::test_invalid_map_geometry_is_rejected[occupancy4-origin4-spacing4]` | PASSED |
| `tests/test_runner.py::test_metric_uses_all_segments` | PASSED |
| `tests/test_runner.py::test_reported_success_is_not_strict_validity` | PASSED |
| `tests/test_runner.py::test_endpoints_must_match_in_either_orientation` | PASSED |
| `tests/test_runner.py::test_worker_times_out_and_reaps_process` | PASSED |
| `tests/test_runner.py::test_postprocessor_error_preserves_completed_raw_path[False]` | PASSED |
| `tests/test_runner.py::test_postprocessor_error_preserves_completed_raw_path[True]` | PASSED |
| `tests/test_runner.py::test_normal_no_path_and_invalid_endpoints_are_distinct` | PASSED |
| `tests/test_runner.py::test_cpu_description_falls_back_to_read_only_registry` | PASSED |
| `tests/test_runner.py::test_author_context_is_repeatable_and_restored` | PASSED |
| `tests/test_runner.py::test_private_protocol_survives_author_output_and_reuses_worker` | PASSED |

编译、Ruff及格式检查结果见[阶段报告](STAGE1_REPORT_CN.md)。完整原始测试输出留在仓库外本地记录目录。
