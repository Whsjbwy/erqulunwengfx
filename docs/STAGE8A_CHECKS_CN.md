# 阶段8A检查与真实命令

工作环境为Windows 11、Python3.11既有虚拟环境，使用CPU。未安装系统工具，未使用GPU、WSL或外部训练。全部路径从命令行或项目ROOT获得，科研代码不硬编码个人目录。

本轮新代码只有门槛/文献/未运行台账校验，没有流场模型和实验执行入口。CSV空测量表示未运行；代码验证通过不代表数学模型、鲁棒性或创新性通过。

本地实际结果：584项pytest全部通过（14.85s，0失败/错误/跳过）；编译、Ruff、格式和公开证据校验的退出码均为0。584包含571项历史回归和13项新增审计测试。Windows Python的`platform`字符串显示`Windows-10-10.0.26200`，这是系统接口报告值，不以此否定用户的Windows11环境。

## 真实执行命令

在仓库根目录执行：

```powershell
git status --short --branch
.venv\Scripts\python.exe -m ruff format src\gsunlight_repro\stage8a tests\test_stage8a_review.py scripts\stage8a_quality.py
.venv\Scripts\python.exe -m gsunlight_repro.stage8a.review --export-tables
.venv\Scripts\python.exe scripts\stage8a_quality.py --output results/stage8a/local-quality
```

导出命令只写新目录，重复运行拒绝覆盖；之后只读验证使用：

```powershell
.venv\Scripts\python.exe -m gsunlight_repro.stage8a.review
```

质量脚本实际依次运行：

```text
python -m compileall -q src tests scripts
python -m pytest -q --junitxml=<新证据目录>/pytest.xml
python -m ruff check .
python -m ruff format --check .
python -m gsunlight_repro.stage8a.review
```

逐条命令、退出码、真实耗时在`results/stage8a/local-quality/commands.json`，原始输出为同目录`.log`，pytest机器记录为`pytest.xml`，环境与被检查的Git身份为`evidence.json`。本地记录的HEAD是运行时的提交身份；若发生于提交前，它不代表新增文件已经位于该提交。最终提交身份由下述Windows CI独立证明。

## Windows最终HEAD证据

`.github/workflows/stage8a-windows.yml`以7B-0为PR目标触发，checkout显式使用PR的head.sha，执行同一个质量脚本；不下载论文、不做网络查新、不运行新的六案例演示或规划。artifact名为`stage8a-windows-review-evidence`，内含最终HEAD、实际环境、完整命令/日志/JUnit。核查时必须比较PR当前head.sha与artifact中的head，不能只看旧绿勾。

最终PR的Checks及Actions链接是权威CI入口，具体run/job/artifact及核对后的HEAD另保存在仓库外`local_only/stage8a_quality/final_ci_verification.json`。该记录不反写已验证的源码HEAD，避免为了添加自引用身份而改变被验证提交。未运行CI或身份不匹配时不得宣称交付完成。

本轮没有修改C++，故没有新的CTest/clang-format运行；历史6D-S通过记录不是8A新模型验收。没有额外生成任何SHA256/MD5文件校验清单，只使用正常Git提交身份。文献访问的HTTP拒绝、元数据核验与代码检索见`results/stage8a/access_log.json`，不伪造出版社响应或模型运行日志。
