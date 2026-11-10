# 第三方组件与方法来源

应用源码和界面为本项目独立编写。HRC 是研究对象名称。提交的应用源码和网页不包含其程序代码、图标、专有数据表或反编译输出；新增固定研究模式读取用户本机安装的数据，在被忽略的 .research-cache 中建立本地缓存。

## 运行依赖

- **phevaluator 0.6.0** — Henry Lee 等，Apache License 2.0。用于七张牌强度计算。项目：[PokerHandEvaluator](https://github.com/HenryRLee/PokerHandEvaluator)。安装版本声明及完整许可证可见 `.venv/Lib/site-packages/phevaluator-0.6.0.dist-info/`；保留的许可证副本见 `licenses/phevaluator-LICENSE.txt`。
- **Python 3.13** — 使用系统已有解释器及 Python 标准库；Python Software Foundation License。应用没有打包 Python 解释器。

开发验证使用 **pytest 9.2.0**（MIT）及其依赖，记录在本地虚拟环境；正常运行应用不需要 pytest。

## 独立实现的方法依据

- Lanctot et al. (2009), [Monte Carlo Sampling for Regret Minimization in Extensive Games](https://mlanctot.info/files/papers/nips09mccfr.pdf)。用于 external-sampling MCCFR 思路。
- [OpenSpiel external_sampling_mccfr.h](https://github.com/google-deepmind/open_spiel/blob/master/open_spiel/algorithms/external_sampling_mccfr.h)。用于检查多人平均策略累计的偏差问题；本项目没有复制其实现，独立采用全支持轨迹采样与权重修正。
- [Poker TDA Rules](https://www.pokertda.com/view-poker-tda-rules/)。用于核对最小加注与短全下重新开放规则。

HRC 公开文档与本机静态证据的对应关系、未知部分见 `research/HRC-FINDINGS.md`。REA 和其他逆向工具属于研究环境，不属于应用运行依赖；版本与来源见主 README。

## 原生研究模式

便携 Zig 0.15.2 用于编译本项目 C++，位于 D:/Tools/REA-Research/zig-native；官方发行包经 SHA-256 校验，编译参数与可执行文件哈希保存在 analysis/hrc-native/build/build.json。工具链未打包进应用。Native 七牌评估为本项目实现，PHEvaluator 另作测试参考。三个翻后桶资源来自用户本机 HRC 安装，仅作本机同模型对照；不复制到 web，也不随项目分发。通用 Brotli 解码辅助器使用本机已安装的 org.brotli 解码库，训练阶段不调用 HRC 求解类。
