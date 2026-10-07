"""Audio Separator runs in its own dependency environment."""
import json
import os
from pathlib import Path
import sys

import imageio_ffmpeg

PRESETS = {'six_stem': 'htdemucs_6s.yaml', 'four_stem': 'htdemucs.yaml',
           'vocals': 'UVR_MDXNET_KARA_2.onnx'}


def main():
    source, output, cache, preset = sys.argv[1:]
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    tools = output / 'tools'
    tools.mkdir(exist_ok=True)
    import shutil
    ffmpeg = tools / 'ffmpeg.exe'
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), ffmpeg)
    os.environ['PATH'] = str(tools) + os.pathsep + os.environ['PATH']
    from audio_separator.separator import Separator
    separator = Separator(model_file_dir=cache, output_dir=str(output), output_format='WAV',
                          use_soundfile=True,
                          demucs_params={'segment_size': 5, 'shifts': 1, 'overlap': .25, 'segments_enabled': True},
                          mdx_params={'hop_length': 1024, 'segment_size': 256, 'overlap': .25, 'batch_size': 1, 'enable_denoise': False})
    print('分轨模型加载或首次下载：' + PRESETS[preset], flush=True)
    separator.load_model(model_filename=PRESETS[preset])
    print('开始分轨', flush=True)
    names = {'Vocals':'vocals', 'Drums':'drums', 'Bass':'bass', 'Other':'other',
             'Guitar':'guitar', 'Piano':'piano', 'Instrumental':'instrumental'}
    files = separator.separate(str(Path(source).resolve()), names)
    manifest = []
    for filename in files:
        path = Path(filename)
        if not path.is_absolute():
            path = output / path
        path = path.resolve()
        if path.parent != output.resolve() or not path.is_file():
            raise RuntimeError('分轨文件路径无效')
        manifest.append(path.name)
    (output / 'tracks.json').write_text(json.dumps(manifest), encoding='utf-8')
    print('分轨完成', flush=True)


if __name__ == '__main__':
    main()
