# 阶段6D真实检查与失败记录

本机完整pytest **529项通过，14.03秒**，0失败。原JUnit位于仓库外`local_only/stage6d_quality/final/pytest.xml`，逐项结果见[final_pytest_cases.csv](../results/stage6d/final_pytest_cases.csv)。开始实验前14项新验收也实际通过，涵盖同几何阈值反例、拐角保持/穿障拒绝、异常恢复、真实冻结执行循环一致性、固定54矩阵和地图输入。另有1项停止门槛回归，保证即使误写见证通过标记，也不能绕过已知模型BLOCKED。

完整编译、Ruff、263个Python文件格式及4个C++文件clang-format检查通过。首轮final检查中，CTest切换目录后不能解析相对DLL PATH，两测试均以`0xc0000135`启动失败；不是模型测试断言失败。原[final_checks.json](../results/stage6d/final_checks.json)如实保留`passed=false`。仅质量脚本改为复用已有绝对PATH环境函数；随后脚本编译/静态检查、冻结CTest2/2、单独诊断CTest1/1全部通过，见[修复后实测](../results/stage6d/post_path_fix_checks.json)。未重复529项pytest或任何科研实验。

冻结两项CTest含模型/连续几何组和官方适配器度量/目标/正向传播验收；新诊断CTest名为`detect_frozen_pitch_contract_gap`，通过意味着检测到已知边界判据缺口，**不意味着模型映射验收成功**。

D0的13次实际原生接口调用全部完成后，因新汇总子目录未创建而写CSV失败。修复后逐个核对保存的请求、输出状态/原因与冻结记录，恢复930接受区间、936传播调用、状态差0；没有重复13次调用。失败`d0.log`与恢复`d0_retry.log`均保留。[开发故障摘要](../results/stage6d/development_failures.json)

首轮新测试曾把`Scene.specification`误写成`spec`，13通过、1失败，修正后14通过；初期新文件还有导入和长行问题，格式化/拆行后解决。一次补丁未匹配格式化后的行，未改文件，随后按现有内容定位。这些早期输出不全有独立完整日志，不虚构其文件。

科研门槛的关键失败是`terrain_1`给定控制的真实SI异常，返回码1；原始输入、stderr、stdout和进程失败记录位于`local_only/stage6d_runs/witnesses/terrain_1`。独立诊断复用相同冻结适配器，实际重现第90区间的pitch子空间拒绝，模型/连续几何却通过。随后只做同一输入的Python完整370区间诊断，不继续第6图或54次规划。[模型门槛失败证据](../results/stage6d/model_mapping_failure.json)

最终只读审计核对全部84个D1条件、64822个保存执行区间的引导、内环、积分、安全和新时钟；没有新增植物模拟或搜索。D0另重新审核历史108份控制结果，缺时钟失败保留。

## 准确最终HEAD Windows CI

新工作流`stage6d-windows.yml`显式检出PR HEAD，执行全量pytest/编译/Ruff/格式、官方OMPL源码构建、冻结适配器构建和2个CTest、新独立诊断构建和故障检测CTest、clang-format、两套13例确定性接口，以及相同terrain反例。CI不运行本地研究轨迹、不开展新随机搜索。

`head-evidence.json`同时保存准确检出/请求HEAD、JUnit、真实构建/CTest日志、原生13例及`model_mapping_gate_passed=false`、`scientific_admission=BLOCKED`。artifact名称为`stage6d-windows-blocked-evidence`。最终运行链接与实际结论在本阶段PR及交付回复核验，完整job日志与下载证明在本地质量目录单份保存；不通过再提交CI结果不断改变待验HEAD。

**绿色CI表示工程检查和已知故障复现成功，科研判断仍为BLOCKED。** Windows云端硬件与本机不同，CI不提供规划性能比较，也不补填未运行的54条记录。
