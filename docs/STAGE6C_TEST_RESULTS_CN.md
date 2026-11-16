# 阶段6C实际质量检查

初轮本机完整pytest **513项通过，12.12秒**；Python编译、Ruff、格式检查、两个原生测试程序、3个C++文件的clang-format检查均退出0。逐命令实际输出见[local_checks.json](../results/stage6c/local_checks.json)，初轮逐测试记录见[pytest_results.csv](../results/stage6c/pytest_results.csv)。原始JUnit/日志保留在仓库外`local_only/stage6c_quality`。

CI目录契约修复后，加入实际调用冻结Runner保护规则的回归测试，最新完整pytest **514项通过，12.60秒**，编译、Ruff和格式检查均退出0。[修复后检查](../results/stage6c/post_ci_fix_checks.json)和[514项逐测试记录](../results/stage6c/pytest_results_ci_fix.csv)另存，未覆盖初轮证据；未新增规划或LOS执行。

新增17项Python验收覆盖参考表示阈值、前缀/目标保持、非法输入、真实穿障尾弦拒绝、固定72矩阵/单因素参数关系、浮点成本平台与真实区间增量拒绝，以及CI生产/读取路径与冻结输出保护的集成契约。后两项来自实际故障。

原生CTest实际2/2通过：冻结模型程序内6组检查，以及新接口的混合度量、目标等号和仅前向传播检查。13例真实SI重放再次得到930接受区间、936实际传播调用和状态最大差0。不是仅测试数学函数，也没有把Release下移除的assert当验收；不是OMPL上游全测试套件。

完整只读审计还重建了46002个最终原生区间、6147个额外首次解区间、22915个C2 LOS区间，以及C1两版本32410个LOS区间。逐步核对冻结引导目标、内环限幅、状态积分、连续安全、目标和时钟门槛，未发现严格安全假阳性。审核没有调用solve或新plant模拟。[审计](../results/stage6c/final_trace_audit.json)

## 真实失败和修复

- 首次临时盘符映射在沙箱中被拒绝，随后在获准构建权限下使用同目录别名。未进行系统级安装。
- 首次C++编译因clang-format调整Win32/PSAPI头文件顺序而失败；完整日志保留，修复依赖顺序后通过。
- 第4个pilot的成本验证器误拒浮点平台，原始时钟未落盘；没有重搜或推算时间，保留预算未知、主要M/S为0。整数区间验证及回归测试修复后，原矩阵继续。[故障说明](STAGE6C_PILOT_AMENDMENT_CN.md)
- 初期Ruff发现长行/导入格式并已修复；一次列名误用、缺失模块路径和补丁定位失配发生在只读审查/编码阶段，未改历史数据。这些早期输出不全有独立完整日志，不虚构其文件；关键构建失败和pilot异常有实际本地记录。

## 最终HEAD Windows CI

[首轮43704256640](https://github.com/Whsjbwy/erqulunwengfx/actions/runs/43704256640)实际失败：Python/静态检查、官方源码构建、6C构建/CTest及clang-format成功，但冻结6B runner拒绝了CI传入的6C结果目录。后续新接口与HEAD证明步骤未执行，不能称整轮通过。[失败摘要](../results/stage6c/windows_ci_failed_attempt.json)与完整本地日志保留。修复将新生成的云端临时结果放在独立`results/stage6b/ci-stage6c-fixtures`子目录，并显式传给6C证据读取器；6B源码/保护规则和所有历史文件均未改。

`.github/workflows/stage6c-windows.yml`显式检出PR HEAD，执行完整Python/静态检查、锁定官方OMPL源码构建、6C适配器构建/CTest、clang-format及两套各13例确定性接口验收。最后运行`scripts/stage6c_ci_evidence.py`，用实际`git rev-parse HEAD`与PR HEAD核对，并保存`head-evidence.json`与JUnit到`stage6c-windows-evidence` artifact。

最终运行链接及实际成功/失败状态在本阶段PR检查与交付回复中核验，不能用6B的历史绿色状态代替。artifact是运行时生成，避免为了把“自身最终提交ID”写回源码而不断改变HEAD。完整云端日志也在本地质量目录留证。

云端windows-latest与本机Windows 11硬件不同；CI验证构建和确定性接口，不替代本机规划时间/成功率。26例确定性接口调用不加入72搜索或21条配对的分母。
