# 自动化手牌复盘工程

在本地复盘德州扑克手牌。设置座位、筹码、盲注和下注尺寸后，可以沿实战行动路径查看翻前决策树和手牌策略。双人底池的翻牌、转牌和河牌决策可用独立的翻后求解器分析。

## 本地启动

在 Windows 上安装 Python 3.13，然后在仓库根目录运行以下命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Start-Preflop-Lab.cmd
```

工作台在浏览器中打开，默认地址为 [127.0.0.1:8765](http://127.0.0.1:8765)。翻后求解的命令行和 Python 用法见[翻后求解器文档](postflop_lab/README.md)。
