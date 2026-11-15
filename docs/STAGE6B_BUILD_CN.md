# 阶段6B Windows原生构建与接口验收记录

本机已经从官方发布源码构建OMPL 2.0.2，并成功链接独立AUV适配器。该结果是Windows原生C++证据，不是Linux/WSL运行、Python轮子安装或自编简化SST。本文只记录B0/B1已完成事实，不据此宣称36次搜索、项目全量检查或云端CI已完成。

## 源码、工具与隔离边界

本次依赖与构建目录为工作目录下的`local_only/stage6b_native`，位于Git仓库之外。源码、工具、静态库、临时文件和完整日志保留单份；没有系统级安装或全局PATH修改，没有切换WSL，没有产生额外文件哈希校验清单。构建脚本只为其子进程配置工具PATH、TEMP/TMP，最多使用两个编译worker。

| 组件 | 实际锁定版本/来源 | 本次用途 |
| --- | --- | --- |
| OMPL | 官方tag `2.0.2`，[源码归档](https://github.com/ompl/ompl/archive/refs/tags/2.0.2.tar.gz) | 官方`control::SST`、`control::RRT`及其基础库；本地`packages/ompl-2.0.2` |
| LLVM-MinGW | [20261104 UCRT x86_64发行包](https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/llvm-mingw-20261104-ucrt-x86_64.zip)，配置日志识别Clang `23.1.5` | 同一原生Windows编译器编译依赖、OMPL与适配器 |
| CMake | [3.31.8 Windows x86_64](https://github.com/Kitware/CMake/releases/download/v3.31.8/cmake-3.31.8-windows-x86_64.zip) | 配置、构建、CTest；使用正式`CMP0176=NEW`策略 |
| Ninja | [1.13.2 Windows发行包](https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip) | 构建后端 |
| Boost | [1.89.0 CMake源码包](https://github.com/boostorg/boost/releases/download/boost-1.89.0/boost-1.89.0-cmake.tar.xz) | 同工具链静态依赖与完整所需头文件模块 |
| Eigen | [3.4.0源码包](https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz) | OMPL依赖 |
| nlohmann/json | `v3.12.0`官方单头文件及`LICENSE.MIT` | 本机文件式JSON桥接，不复制进Git源码目录 |

OMPL的本地`LICENSE`已读取，确认为BSD-3-Clause，版权主体为Rice University；[对应官方许可证](https://github.com/ompl/ompl/blob/2.0.2/LICENSE)须与后续再分发要求一并保留。nlohmann/json的本地MIT许可证也已保存并读取。工具链发行包包含不同组件，不能将整个工具链笼统称为OMPL的BSD许可。本任务不公开依赖源码、构建缓存或二进制。

OMPL源树保持官方算法实现；AUV模型、连续认证、JSON接口和目标/代价适配均在独立`native/stage6b`中。CMake使用`find_package(ompl 2.0.2 EXACT CONFIG REQUIRED)`，实际日志找到精确2.0.2版本，链接目标为`ompl::ompl`。没有修改SST/RRT树核。

## 失败记录和最终构建设置

`build_status.json`保存21条实际构建命令，编号00—20，其中6条失败、15条成功；不是首次构建一次通过。所有对应完整日志均保留。

| 编号 | 实际结果 | 错误含义及处理 |
| --- | --- | --- |
| 00 | Boost配置退出1 | CMake生成的编译器路径混入反斜杠，出现非法转义`\l`；编译器和prefix参数改用正斜杠 |
| 01—03 | 配置进程异常终止，退出码3221226505（`0xC0000409`） | 不是算法无解或普通缺头文件错误。诊断涉及Clang规范化后输出中文真实路径、CMake解码/路径解析；单用正斜杠或临时盘符不足以消除问题 |
| 04 | Boost配置退出0 | 使用指向同一D盘目录的临时`Z:`映射、`-no-canonical-prefixes`及官方`CMP0176=NEW`后配置通过；没有复制源码到另一大目录，也没有补丁修改CMake模块 |
| 05 | Boost编译退出1 | `WaitOnAddress`、`WakeByAddressSingle/All`缺少Windows API声明；明确Windows 10及以上目标宏后继续，未禁用线程安全逻辑 |
| 06—09 | Boost、Eigen配置/安装退出0 | C/C++旗标加入`-D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00` |
| 10—11 | OMPL配置通过，编译退出1 | 缺少`boost/math/special_functions/prime.hpp`。仅安装serialization/program_options未覆盖OMPL实际需要的头文件模块 |
| 12—16 | 扩展Boost模块并重新配置依赖，均退出0 | 明确加入math、graph、random、algorithm、range、foreach、dynamic_bitset、numeric/odeint；没有删掉OMPL相关源文件来规避依赖 |
| 17 | 官方OMPL编译/安装退出0，约135.18秒 | 生成并安装`prefix/lib/libompl.a`等官方库和头文件 |
| 18—19 | 适配器配置/编译退出0 | 成功生成`auv6b_runner.exe`和`auv6b_model_tests.exe`；适配器只声明C++语言，配置日志中未使用的C旗标警告不等于C++构建失败 |
| 20 | CTest退出0 | 1/1测试通过，CTest总实际时间0.13秒；该单测试内部执行6组模型/几何检查 |

另有**一次**`--trace-expand`诊断调用，完整输出为`cmake_diagnostic_trace.log`，不在上述21条label命令中，必须单列而不能漏报。该文件保留了中文路径被错误解释及CMake路径处理位置；`build_status.json`没有为这次诊断单独登记退出码，本文不虚填。路径、规范化和解码修复采用组合设置，未进行额外因素实验，不能把其中一个开关单独认定为唯一根因。

最终共同C/C++旗标为：

```text
-no-canonical-prefixes -D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00
```

使用Release、Ninja和两worker。OMPL关闭VAMP、Python bindings、shared library、官方测试和demo构建；不因此声称官方全测试套件通过。AUV适配器启用C++17和必要警告；本机CTest只覆盖自编模型/认证测试，不是完整上游测试。

临时`Z:`只为构建工具提供ASCII路径别名，底层仍为原D盘专属目录。任务结束须撤销该映射；再做增量构建时需恢复同样映射。普通原生运行通过实际D盘可执行文件和其局部依赖PATH进行，不将路径映射等同WSL或系统级安装。

## B1原生接口验收结果

预登记提交`7c77345`先于13例验收；完整原生源码/安全证据提交`5b04e39`先于搜索。实际结果见[逐例CSV](../results/stage6b/interface_cases.csv)、[总账](../results/stage6b/interface_acceptance.json)及[中段穿障证据](../results/stage6b/middle_collision.json)。

- 6A原登记12例及新增中段反例全部符合预期，共13/13通过；包括6个给定控制运动见证和7个拒绝输入/场景。
- 经真实OMPL `SpaceInformation`适配接口累计调用936次propagator，接受930个完整0.1秒区间；拒绝候选与最后接受状态分别记录。
- 相对冻结Python积分，原生位置、角度及速度最大比较差均为0；28个独立RK4核对最大位置差`1.2079226507921703e-13 m`。
- 新增反例两端完整球检查均自由，中点球确实相交，间隙约`-0.0004 m`，整个区间被拒绝。它不能被仅检查两端的办法认证为安全。

这组结果是接口与认证验收，不是SST/RRT搜索成功率；CSV的`purpose`明确区分给定控制与真实规划。到达字段也不能覆盖输入超限、碰撞或非法速度的拒绝原因。

完整命令、退出码、耗时与日志位置以本地`local_only/stage6b_native/build_status.json`为准。日志前缀为`build-00-boost-configure.log`至`build-20-adapter-ctest.log`，另有诊断trace；13例完整请求/结果位于`local_only/stage6b_runs/acceptance`。精简复跑入口见[命令记录](STAGE6B_COMMANDS_CN.md)。
