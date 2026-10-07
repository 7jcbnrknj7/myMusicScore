# AI 助手

维护分支：`feature/ai-assistant`

本分支从 MusicScore v1 完整集成快照建立，保留共用后台和界面，不是可单独运行的删减应用。

## 维护范围

OpenAI、DeepSeek 和兼容接口；仅按音符给建议，不替代 MuScriptor。

主要文件：app.py 的 assistant 接口、qt_client.py 的 AI 助手视图。

## 协作约定

修改限于本功能所需范围；共享接口修改应附回归测试。完成后合并到 main。v1 分支作为原始版本快照保留，不在其中继续开发。其他已知问题及依赖许可见根目录 README.md。

不得提交个人曲谱、录音、分轨文件、模型权重、密钥、本机设置或虚拟环境。
