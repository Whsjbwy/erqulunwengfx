# 7B-0证据入口

- `comparison.csv`：固定6任务三方法对照；`baselines.csv`保留18个方法/任务条件并标明旧/新来源。
- `failures.csv`：5条继承LOS失败，新六次未发生失败；没有删除旧失败。
- `execution_ledger.json`、`execution_results.json`、`execution_summary.json`：一次真实六执行的状态、摘要、独立证书和分母。
- `admission/`及三个更早JUnit：19项真实B1验收和保留的开发故障；合成测试不作科研性能样本。
- `decision.json`：ENGINEERING-RESOLVED仅限六个名义诊断任务，不宣称鲁棒性或原创性。
- `figures/`：保存数组的三维轨迹、实际控制和连续净距下界对照，未新积分。
- `direction_review.json`、`output/pdf/stage7b0_directions_cn.pdf`：同源两页候选方向分析，已检查分页和渲染，不授权新模型/算法。
- `local-quality/`：本地真实全量工程证据；最终HEAD Windows CI另从PR Checks下载。

完整新轨迹仅在仓库外`local_only/stage7b0_runs/<job_id>/execution.json.gz`一份；6D-S原始轨迹和地图未复制、覆盖或重跑。旧重复LOS任务仍保留六任务分母，同时报告唯一旧LOS轨迹1/5口径。

数值0表示确实测得（例如本轮前馈差为0）；首次拒绝空值表示完整执行中未发生。未记录信息不能据此填0。新LTV误差为同原生时间参考的偏差，旧LOS几何距离及终止标签保留原语义。`combined_wall_s`是旧规划实测+新执行认证实测的预算核算，不是本轮重新规划的端到端测量。
