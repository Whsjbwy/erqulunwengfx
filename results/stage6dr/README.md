# 6D-R精简真实证据索引

- `case_manifest.json`：实际F2调用之前写出的完整确定性名单；69+13+6例，全部状态及给定控制，不筛选。
- `boundary_cases.csv`：69例入口/边界/安全判据，反例被拒绝才算验收通过；inspect不计作传播。
- `legacy13_cases.csv`：原13例实际SI结论，共930接受区间，保留全部预期失败。
- `maps6_cases.csv`：六图2440接受区间，terrain_1完整370步。
- `interval_checks.csv`：3398条真实区间尝试，含源/候选/返回有效性、bounds、冻结完整区间判据、实际SI步数、独立Python比较；本地与原始索引分开。
- `witness_safety.csv`：由六图已保存的独立审核摘要提取，包含到达、连续间隙下界与最终状态，不另存大型轨迹。
- `old_new_compatibility.csv`：原13例和四张原生已完成见证共17个历史输出配对，状态差0；未把旧terrain_1失败当旧成功。
- `original_failure_reproduced.json`：未改6D probe在本轮新构建中真实复现expected1/actual0。
- `measured_counterexamples.json`：从实际已保存的原生输出选取原索引89、±一ULP越界、穿障、面/棱/角贴碰、工作空间逃逸和非有限控制的完整小记录；选取用于解释，不用于改变统计分母。
- `adapter_policy.json`、`build_evidence.json`：实际配置和全部构建命令/退出码，包含第一次配置失败。
- `acceptance_summary.json`：本机模型接口验收汇总，明确最终HEAD CI需单独核验。
- `local-quality/`：本机实际检查命令、精简stdout、534项JUnit及三种分开的门槛。记录为当时工作树检查，`exact_pr_head_ci=false`不是最终云端证明。

完整输入/原生轨迹/进程stdout、stderr、计时保存在Git外`D:\2区论文复现\local_only\stage6dr_runs`，构建日志在`stage6dr_native`；旧网格和大型历史记录仅引用。未生成任何额外文件哈希清单。最终CI的HEAD、运行和artifact链接及实际下载核验写入PR正文，避免回填改变已验HEAD。

本目录只证明确定性模型接口和给定控制安全，不提供规划算法成功率。原54次搜索仍未执行，H1仍未获准。
