# 跨平台安装与降级协议

## 正式支持矩阵

- macOS 13+（Intel/Apple Silicon）。
- Windows 10/11（x64/ARM64，PowerShell、CMD、Git Bash及WSL2）。
- Ubuntu 22.04/24.04、Debian 12和Fedora当前稳定版（x64/ARM64）。
- Python 3.10–3.13。

仅对宿主官方在该系统提供的CLI、桌面或IDE界面承诺技能发现与离线核心流程。Alpine/musl、Windows 8.1、WSL1及Python 3.9以下只尽力兼容。

## 智能安装器

以系统当前Python运行，不依赖shell脚本：

```text
python scripts/install_skill.py --host both --scope project --mode auto
python scripts/install_skill.py status --host both --scope project
python scripts/install_skill.py repair --host both --scope project
python scripts/install_skill.py uninstall --host both --scope project
```

`auto`按符号链接→Windows目录junction→受管副本降级。受管副本保存内容哈希，`status/repair`可检测与规范目录的偏离。不要覆盖没有安装清单的用户目录。

## 可复制命令

Bash/Git Bash/WSL：

```bash
python "cq-bibliometric-introduction-review-writing/scripts/review_pipeline.py" doctor --json
```

PowerShell：

```powershell
python ".\cq-bibliometric-introduction-review-writing\scripts\review_pipeline.py" doctor --json
```

CMD：

```bat
python ".\cq-bibliometric-introduction-review-writing\scripts\review_pipeline.py" doctor --json
```

内部调用一律使用 `sys.executable` 与参数数组，不使用 `shell=True`、Bash展开或字符串命令拼接。

## 凭据与可选能力

凭据输入顺序为macOS原生对话框、Windows原生/Tkinter、Linux GUI，最后降级到终端 `getpass`。持久化优先Keychain、Credential Manager或Secret Service/keyring；后端不可用时仅保存当前进程，不写入日志、命令行或项目。

OCR、LibreOffice、GUI、安全凭据库、浏览器或字体不可用时，状态为 `skipped-unavailable`，必须说明原因和恢复命令；不得产生未处理异常或阻断无关模块。

## 路径预检

任务创建前检查Windows保留名、非法字符、大小写冲突、空格/中文路径和240字符长路径风险。严重冲突阻止创建；长路径风险建议使用 `C:\reviews\task`等短根目录。
