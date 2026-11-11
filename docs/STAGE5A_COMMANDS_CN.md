# 第五阶段5A实际命令与独立重复

所有命令在仓库根PowerShell执行，Python3.11，CPU串行，无GPU训练。路径相对仓库，不硬编码个人用户目录。

## 已实际执行的准备与原批量

```powershell
git switch -c pivot/auv-rrt-stage5a repro/gsunlight-stage4a
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src tests scripts

.venv/Scripts/python.exe -u -m gsunlight_repro.stage5a.runner `
  --phase pilot_single --local-dir ../local_only/stage5a --output results/stage5a
.venv/Scripts/python.exe -u -m gsunlight_repro.stage5a.runner `
  --phase pilot --local-dir ../local_only/stage5a --output results/stage5a
.venv/Scripts/python.exe -u -m gsunlight_repro.stage5a.runner `
  --phase development --local-dir ../local_only/stage5a --output results/stage5a
.venv/Scripts/python.exe -m gsunlight_repro.stage5a.analysis `
  --local-dir ../local_only/stage5a --output results/stage5a `
  --select configs/stage5a_selected.json
```

预注册20b7c6d在任何新搜索前推送；核心2096266在功能试验前推送；4ac3ef9保存仅开发集得到的三方法step5和资源门槛。各trial新子进程、普通优先级、同一逻辑CPU掩码4及线程环境1，由runner自动设置。阶段预检同规格seed0只运行一次。

曾执行以下首批命令，5条完成后因重复地图停止，另1条中止。其原configuration、所有记录和日志原样保留，不把它算作完成270次：

```powershell
.venv/Scripts/python.exe -u -m gsunlight_repro.stage5a.runner `
  --phase holdout --local-dir ../local_only/stage5a --output results/stage5a
```

## 已实际执行的修正与恢复

修正原因和停止过程见STAGE5A_MAP_AMENDMENT_CN.md。先比较冻结源代码生成的13张未变地图/端点/见证/顶界，再以目录junction复用135功能+45开发+5完整留出记录，不复制大文件。脚本需本仓库Git历史中的2096266；只适用于本次保留记录，独立从头复现不需它。重复执行时拒绝包含新生成任务的目标目录。

```powershell
.venv/Scripts/python.exe scripts/prepare_stage5a_amendment.py `
  --original ../local_only/stage5a --amended ../local_only/stage5a_amend1 `
  --output results/stage5a

.venv/Scripts/python.exe -u -m gsunlight_repro.stage5a.runner `
  --phase holdout --local-dir ../local_only/stage5a_amend1 --output results/stage5a

.venv/Scripts/python.exe -m gsunlight_repro.stage5a.analysis `
  --local-dir ../local_only/stage5a_amend1 --output results/stage5a --figures
```

b1c61ee在H5_O2首次搜索前推送，地图独立性修正有明确Git记录。恢复命令已实际正常退出0，完整270次留出完成；功能/开发连同复用共450个完成任务，另1次未完成尝试单列。experiment_accounting.json的complete=true已核实。

## 已实际完成的最终审计与检查

```powershell
.venv/Scripts/python.exe -m gsunlight_repro.stage5a.audit `
  --local-dir ../local_only/stage5a_amend1 --output results/stage5a --replay-selected
.venv/Scripts/python.exe -m compileall -q src tests scripts
.venv/Scripts/python.exe -m pytest -v
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
git diff --name-only --diff-filter=M repro/gsunlight-stage4a
git status --short
```

审计只读取原始坐标、历史和截点，额外重放选中路径，不能改变原记录或反过来选更好的输出。

审计实际退出0：450任务、13185条归档路径条目、13633条历史引用、1305个截点通过；380条选中路径按原执行流程重放，结果/指标一致。随后实际重新派生最终CSV/图。修正显示留白后最终本地416 passed in8.62s，编译、Ruff与123文件格式检查成功；完整日志保留仓库外，逐项表在results/stage5a/pytest_results.csv。

## 研究者从头独立重复的方法

使用全新本地目录，例如../local_only/stage5a_independent_repeat及新的输出目录。按pilot_single→pilot→development→holdout顺序运行当前修正版；正式重复使用已发布step5，不根据这次留出结果选参。开发选参规则可另用--select指向全新本地JSON进行验证，不覆盖仓库已发布参数。

新重复无需junction或原始作者资料。所有地图由配置和固定seed生成；程序拒绝覆盖已有试验、复用不同配置或把部分目录当完成结果。真正重做新的独立重复可以有不同墙钟截止展开量，不能承诺不同机器上时间预算结果逐位相同。固定迭代的种子/路径/计数重复性另有单元测试。
