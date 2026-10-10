[简体中文](README.md) | [日本語](README.ja.md) | [English](README.en.md)

# MusicScore v1 个人曲谱客户端

Windows 本地应用：MuScriptor 转录、曲谱库、移调、音符编辑、钢琴/吉他和弦标记、试听及 MuseScore 编辑。

本应用基于 [MuScriptor](https://github.com/muscriptor/muscriptor)、[MuseScore](https://github.com/musescore/MuseScore) 和 [AccoMontage2](https://github.com/billyblu2000/AccoMontage2) 构建，原生桌面界面采用 PySide6。当前源码版本为 **v1（1.0.0）**，属于个人使用的实验版本，不代表全部功能稳定。

## v1 状态与已知问题

导入音频后，分轨、扒谱、和弦分析、谱式转换、编辑、历史版本和播放等多功能之间的兼容性曾出现过许多错误。目前已修正已发现的多项问题，包括不支持的和弦名称导致后处理失败、打击乐无固定音高音符导致曲谱打不开、历史版本文字重复，以及长标题布局递归导致闪退。**预计仍有很多错误待修正**；这些修复不表示全部兼容性问题已解决，生成乐谱仍需要人工校对。

**和声编配模块尚不可作为完整可用功能使用。** AccoMontage2 的界面和生成流程已接入，普通和声生成曾跑通，但按指定风格筛选后，仍存在“没有匹配长度素材”的错误。完整伴奏模式还缺少额外模型资源，所以暂时禁用。界面中的风格选项是标准流行、复杂流行、暗色和 R&B；在此问题修复前，不保证所选风格能够成功生成。当前输入检查要求单声部旋律、4/4 拍、固定速度及 4 或 8 小节乐句。失败不会覆盖原始旋律版本。

v1 源码测试通过 56 项；曾验证过本地转录、CUDA 分轨、谱面预览及部分编配流程，但测试数量不等于全场景可用性保证。

## 分支安排

`main` 保存完整集成应用，`v1` 保留本次上传的版本快照。各功能开发分支从同一个 v1 源码起点建立，保留共享依赖，后续通过合并集成，不是彼此独立的精简应用。每个功能分支的 `docs/BRANCH_SCOPE.md` 说明其维护范围。

| 分支 | 主功能 | 主要文件 |
| --- | --- | --- |
| `feature/native-client` | Qt 桌面界面、播放器、录音和启动 | `qt_client.py`、`desktop.py`、启动脚本、`static/icons/` |
| `feature/transcription` | 本地及远程 MuScriptor 扒谱、模型下载 | `transcribe_worker.py`、`model_download.py`、`app.py` 转录接口 |
| `feature/audio-separation` | 音频/视频输入、可选分轨、分轨试听 | `separation_worker.py`、`separator-requirements.txt`、媒体接口 |
| `feature/score-editing` | MuseScore、移调、音符编辑、和弦及派生谱式 | `music.py`、`notation.py`、编辑接口 |
| `feature/library-export` | 我的曲谱、历史版本、回收站及文件导出 | `app.py` 项目与版本接口、`qt_client.py` 对应视图 |
| `feature/ai-assistant` | OpenAI、DeepSeek 等兼容接口的 AI 助手 | `app.py` AI 接口、`qt_client.py` AI 视图 |
| `feature/harmony-arrangement` | AccoMontage2 和声编配，尚未完成 | `arrangement.py`、`arrangement_worker.py`、编配接口与视图 |

本仓库仅包含应用源码、测试、图标及依赖说明。**不上传个人曲谱、录音、分轨音频、导出文件、模型权重、本机设置、密钥、日志或虚拟环境。**

## 从源码准备环境

在 Windows 上安装 Python 3.12、Git 与 MuseScore 4，然后在仓库根目录建立环境：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -r arrangement-requirements.txt
git submodule update --init --depth 1
git -C tools/AccoMontage2 apply ../../patches/accomontage2-chord-pipeline.patch
```

PyTorch 的 GPU 版本需根据显卡和 CUDA 兼容性单独选择；默认依赖安装不保证 CUDA 推理可用。MuseScore 程序和 MuScriptor 模型权重需要另行安装或下载、接受对应许可。AccoMontage2 以固定提交的子模块引用，不将其数据文件和模型复制进本仓库；子模块可能自行包含较大参考数据。补丁修正其纯和声分支遗漏参数的问题，完整伴奏缺失资源和指定风格问题仍未解决。

分轨需另外建立 `.separator-venv`，安装 `separator-requirements.txt`。本机分轨环境共享主环境 CUDA PyTorch 并固定兼容版本，详见下文；干净机器的分轨依赖隔离尚未提供一键安装脚本。源码仓库不是可直接下载运行的打包安装程序。

## 启动

双击桌面或应用目录里的 `MusicScore.lnk`，或运行 `Start.ps1`。客户端使用 PySide6 Qt Widgets 原生桌面控件，不使用 WebView2 或内嵌网页；谱面由 QtPdf 预览，底部固定播放器使用 QtMultimedia。支持最小化、最大化、窗口调整、侧栏收起与录音。重复启动会激活已有窗口。旧网页客户端源码只作为备份保存在 `work/webview-client-legacy.py`，默认入口不再使用它。

关闭窗口后，本机后台服务保留，未完成的转录或下载继续运行；有任务时会提示确认。无需设置开机启动，也不安装 Windows 系统服务。需要彻底关闭后台时，任务完成后运行 `StopService.ps1`。重新打开客户端会自动启动或复用本机服务，不重复加载模型。

默认本机端口为 `8765`；端口已占用时选择后续空闲端口。服务仅监听 `127.0.0.1`，不向局域网开放。Hugging Face 许可页面等外部链接仍在默认浏览器打开。

原使用环境的应用安装在 `G:\codex\MusicScore`。Windows 凭据服务名称仍保留 `ScoreDesk`，避免丢失已有 API 密钥。`CreateShortcut.ps1` 可重新生成启动快捷方式；之后若移动安装目录，需要重新修复运行环境的启动脚本并更新快捷方式。

## 本机路径与导出

设置中的“应用安装目录”显示 MusicScore 实际安装位置，旁边的文件夹按钮可打开该目录。“乐谱导出位置”与它并排，原使用环境默认是 `G:\codex\MusicScore\exports`；可点击文件夹按钮选择其他目录，也可输入完整路径，保存后生效。

点击曲谱上的 MusicXML、MIDI、MSCZ、PDF 或当前谱式的 PDF 入口，文件直接写入默认导出位置，并提示实际路径。目录按曲名、项目 ID 和版本组织。重复导出会添加编号，不覆盖已有文件。曲谱库、原始输入与版本数据仍保存在安装目录的 `library/` 中，改变导出位置不会移动曲谱库。

## 首次设置

1. 在 Hugging Face 登录并接受官方 [medium](https://huggingface.co/MuScriptor/muscriptor-medium) 和 [small](https://huggingface.co/MuScriptor/muscriptor-small) 模型的许可。
2. 在应用设置中填写 Hugging Face read Token，保存后下载 medium 和 small。密钥保存于 Windows 凭据管理器。
3. MuseScore 可执行文件路径通常自动识别。也可以手动选择 `MuseScore4.exe` 的完整路径。

本地权重缓存保存在 `models/`，乐谱及原始输入保存在 `library/`，删除内容移入 Windows 回收站，不再使用本地 `trash/`。未下载成功的模型不会显示为已缓存。本地提供 small、medium 和 large，默认 medium，使用 CUDA float16、batch size 1；GPU 任务串行执行。large 需要在官方模型页面单独接受许可，并在设置中下载；显存占用和运行速度需以本机实际测试为准，显存不足时可切换较小模型。

模型下载在设置和制作状态栏中显示 small、medium、large 的进度。主状态栏显示真实已下载字节数、总大小、百分比和近期速度。获取文件信息时进度条等待，不显示虚构百分比；下载完成才显示 100%。重复点击不会新建同一模型的重复下载任务。重试可复用 Hugging Face 的缓存与断点下载。

401/403 表示 Hugging Face 拒绝访问，并非后台仍在下载。需要登录下载所用 Token 对应的账号，接受该模型许可，并使用有访问权限的有效 Token。

## 远程 API 与 AI 助手

这是两种不同用途的 API：

- **远程 MuScriptor**：small、medium、large 分别填写一个运行该权重的 MuScriptor 官方兼容服务地址。应用调用 `/transcribe/midi`，multipart 字段为 `file` 和可选的 `instruments`，返回标准 MIDI。端点必须已经在远程服务器部署；填写 ChatGPT/DeepSeek 地址不能替代音乐模型。非本机地址要求 HTTPS。
- **AI 助手**：支持 OpenAI、DeepSeek 和 OpenAI 兼容接口，调用 `/chat/completions`。填写服务地址、账号可用的模型 ID 与 API Key。助手根据曲谱音符给建议，不运行 MuScriptor 权重、不假装听过音频，也不自动改写谱面。发送时最多包含 1000 个音符事件。

本应用也提供调用端口：`POST /api/transcribe`，表单字段为 `file`、`mode`（local/remote）、`model`、`instruments`。返回 job/project ID，通过 `/api/status` 查询进度。具体接口见 `/docs`。

## 使用与版本

上传音频或视频时，FFmpeg 自动抽取第一条音频轨为单声道 24kHz WAV，原文件保留。也可导入 MIDI、MusicXML 或 MSCZ。每次编辑生成新版本，失败导出不会替换当前版本。

输入端使用 QtMultimedia 支持麦克风录音、暂停/继续和停止。停止后将录音导入储存栏，可试听、分轨或直接扒谱。麦克风权限由 Windows 系统设置控制，录音失败会提示。Qt 录音不承诺所有音频驱动都能关闭自动增益或系统音效。

## 可选分轨流程

音频或视频导入后，FFmpeg 提取双声道原混音；可以直接选择原混音扒谱，也可以先分轨。分轨采用 nomadkaraoke/python-audio-separator 0.47.0，提供 htdemucs_6s 六轨、htdemucs 四轨及 UVR_MDXNET_KARA_2 人声/伴奏两轨。六轨包含人声、鼓、贝斯、吉他、钢琴和其他乐器，不提供独立小提琴轨，也不保证混音中的木吉他与电吉他完全分开。每个分轨可在底部播放器试听、拖动进度和导出，然后选择该音轨扒谱，再进入 MuseScore 编辑。

分轨程序在 `.separator-venv/` 中运行，模型缓存位于 `models/separator/`，音轨位于对应项目的 `stems/`。为避免 rotary-embedding-torch 版本冲突，分轨依赖与 MuScriptor 分开，CUDA torch 2.11.0+cu128 由主环境共享；ONNX Runtime GPU 固定为与 CUDA 12 相容的 1.23.2。更新分轨环境时不要自动安装 CPU torch 覆盖共享 CUDA 运行库。分轨与扒谱共用串行任务队列，可暂停、继续和取消；第一次使用某种分轨模型会自动下载。原始文件保持不变，回收曲子会连同分轨与项目记录一起移入 Windows 回收站。

底部的“乐谱试听”为音符合成试听，不是原录音，也不是 MuseScore 的完整乐器音色引擎。乐谱编辑、移调、和弦分析、版本切换、AI 助手、模型下载及默认导出路径继续使用现有本地服务。

分轨依赖来源与致谢： https://github.com/nomadkaraoke/python-audio-separator ，以及其上游 Ultimate Vocal Remover / UVR 与 Demucs 作者。代码与模型分别遵循各自许可。

储存栏支持搜索、谱面 PDF 查看、MusicXML/MIDI/MSCZ/PDF 下载、音符修改、移调、重新识别和弦、版本切换和归档。内置播放是基础合成试听；实际乐器音色和完整演奏控制使用 MuseScore。

储存栏每首曲谱右侧有垃圾桶删除按钮，不需要先打开曲谱。删除前确认，原始输入、曲谱、全部版本及项目记录一起移入 Windows 回收站；回收失败时提示错误，不改为永久删除。已导出到其他目录的独立副本不删除。正在转录或编辑的曲谱暂不能删除。

点击 MuseScore 打开当前版本的 `edited.mscz` 副本，在 MuseScore 保存后，点击旁边的同步按钮生成曲谱库新版本。自动编辑使用 MusicXML 交换，复杂奏法及精细布局可能在转换时变化；原始 MSCZ 编辑副本始终保留。移调/改音后不保留旧弦品注释，需在 MuseScore 检查和调整 TAB。

自动和弦基于 piano/guitar 声部同时发声的音符，由 music21 识别并写入 Harmony 标记。它是候选：琶音、缺音和弦、装饰音、复杂爵士和声及扒谱误差可能导致遗漏或错判。小提琴等声部不自动添加吉他和弦标记。

## 吉他与钢琴谱式

- 吉他：生成同页的旋律简谱、和弦名称及六线谱，PDF 与 MSCZ 均可打开。旋律暂取每个音符事件的最高音；这不是旋律声部分离模型，复杂指弹或多声部需要人工校对。六线谱基于 MuseScore 默认六弦调弦，自动弦品不一定是最合适的指法。
- 钢琴：生成双手五线谱和双手简谱，在谱式菜单切换。已有左右手 Staff 数据保持不变；单声部钢琴初次导入以中央 C 分手，标记为自动分配。跨手和交叉声部需在主谱中调整。
- 转换共用主谱 MusicXML，不重新识别音频。移调、改音及同步主谱后重新生成各谱式。原音高、时值和左右手数据保留；不支持从图片或 PDF 反推音符。
- 简谱属于试验转换层，并非 MuseScore 原生完整简谱模式。音高用可见数字文本表示，底层音符保留；支持数字、变音、八度点、休止和常见时值。多声部、连音线、特殊节奏和复杂排版尚未完整验证，不能保证出版社级简谱。小调按其相对大调的 1 标注。
- “打开谱式”打开派生 MSCZ；“MuseScore”打开可同步的主谱编辑副本。编辑主谱后同步再生成谱式，不应直接修改派生数字文本来改变音高。派生吉他旋律在 MuseScore 中静音，避免与六线谱重复演奏。

MuseScore 的简谱原生支持仍有[开发讨论](https://github.com/orgs/musescore/discussions/22698)。正式五线谱与 TAB 始终保留，不因简谱视图而覆盖。

## 验证

运行 `.venv/Scripts/python.exe -m pytest -q`。实际音频转录仍需已获授权的官方模型权重。不存在有效 API 密钥时不调用外部 AI 服务。

依赖项目：[MuScriptor](https://github.com/muscriptor/muscriptor)、[MuseScore](https://github.com/musescore/MuseScore)、[AccoMontage2](https://github.com/billyblu2000/AccoMontage2)、[music21](https://github.com/cuthbertLab/music21)、[Lucide](https://github.com/lucide-icons/lucide) 和 [python-audio-separator](https://github.com/nomadkaraoke/python-audio-separator)。MuScriptor 权重按其 CC BY-NC 4.0 条款使用；依赖代码、参考数据和模型各自遵循上游许可，本仓库不改变这些许可。
