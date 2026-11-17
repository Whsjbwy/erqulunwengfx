# 7A真实检查与取证说明

## 执行范围

本地Windows、仓库既有Python3.11虚拟环境。科研审计只读历史输入，修改仅限新增7A路径。没有C++变化，没有新增OMPL构建、CTest或科研规划/控制回放实验。既有pytest中的合成模型、积分和控制单元测试正常执行，单独归为工程回归，不计入新的科研轨迹实验。6D-S历史CTest与原生安全验收只作已存来源引用，不能当作7A新测试。

实际执行的提取/绘图命令（仓库根目录）：

```powershell
.venv/Scripts/python.exe -m gsunlight_repro.stage7a.audit --raw-root ../local_only/stage6ds_runs
.venv/Scripts/python.exe -m gsunlight_repro.stage7a.plots --raw-root ../local_only/stage6ds_runs
.venv/Scripts/python.exe -m pytest tests/test_stage7a_audit.py -q
```

最后一条7项通过，0.15s；合成测试只验证审计语义，不能作为AUV实验。提取器实际读取47组input/output/压缩记录并检查保存控制、输出节点和密集样本对应，写出47/15索引与事件。再次提取新7A派生文件不覆盖任何历史阶段结果。

文献矩阵CSV由 `literature_sources.json` 的 `papers` 数组写出；所有描述为自编审查文字，无外部全文或软件源码拷入仓库。`public_evidence`在无私有原始记录的CI中检查其与历史公开台账的分母/标签对应，不重新积分，也不能代替私有原始轨迹认证。

完整工程检查使用：

```powershell
.venv/Scripts/python.exe scripts/stage7a_quality.py --output results/stage7a/local-quality
```

脚本实际运行compileall、全量pytest、Ruff check、Ruff format --check、公开证据检查；每条命令保留退出码和耗时，日志与pytest.xml在新目录。运行结果以该目录的`evidence.json`和原始日志为准，任何失败保留原日志，不用“应该通过”替代。

## 开发错误留痕

第一次提取遇到成功样本“引导已进入桥段但无失败索引”时，错误比较None与整数。已修复为明确的成功/未知/缺席分支，增加成功回归测试；`development_error.json`保留该错误。辅助只读检查还曾用Windows默认GBK读取UTF-8 JSON而报编码错误，显式指定UTF-8后重读成功；对科研数据没有写入。最初Ruff检查报告绘图代码长行，格式化后独立重新检查通过。路径查找中的未命中文件已改为实际文件定位，未作为不存在的源码引用。

网络查阅中的403、DOI跳转失败、机构脚本页、过期签名链接及大PDF超过工具长度限制，按文献矩阵记录；不将它们解释为论文/代码不存在。GitHub代码请求的一次传输失败与不存在路径404仅表示内容未取得，后续用已核实的官方文档，不伪称读到错误请求的源码。

## 最终提交的Windows CI

新增工作流 `.github/workflows/stage7a-windows.yml` 面向指定6D-S目标分支；checkout明确取PR实际HEAD并取得历史，以便验证相对冻结基线只有新增文件。运行相同质量脚本，产物 `stage7a-windows-read-only-evidence` 包含命令、日志、pytest.xml、实际HEAD及平台。CI不访问本地原始大轨迹，不执行新随机搜索或控制回放。

仓库中嵌入最终HEAD自己的ID会产生递归提交，因此最终CI地址、运行/任务/产物ID与HEAD核对结果写入PR描述，并在本地工作区 `local_only/stage7a_quality/final_ci_verification.json` 保存实际取证。公开日志可从PR Checks下载。这一区分避免报告中的前一提交检查被误作最终HEAD通过证明。

交付时检查：Git工作区干净；相对 `43660a5008983ee9bf20a670eaed18463d748e22` 的文件状态全为A；不含依赖源码、大轨迹、额外hash清单；PR开放且未合并；7B未运行。最终实际状态以PR及取证文件为准。
