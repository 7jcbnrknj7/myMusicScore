# MuScriptor 扒谱与模型

维护分支：`feature/transcription`

本分支从 MusicScore v1 完整集成快照建立，保留共用后台和界面，不是可单独运行的删减应用。

## 维护范围

本地 small/medium/large、远程 MuScriptor、模型缓存与下载进度。

主要文件：transcribe_worker.py、model_download.py、app.py 的模型及转录接口。

## 协作约定

修改限于本功能所需范围；共享接口修改应附回归测试。完成后合并到 main。v1 分支作为原始版本快照保留，不在其中继续开发。其他已知问题及依赖许可见根目录 README.md。

不得提交个人曲谱、录音、分轨文件、模型权重、密钥、本机设置或虚拟环境。
