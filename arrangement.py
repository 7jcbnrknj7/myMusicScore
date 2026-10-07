"""Validated melody input for the upstream AccoMontage2 worker."""
import math
import re
from pathlib import Path
from music21 import harmony, meter, note, stream, tempo

ROOT = Path(__file__).resolve().parent
REPO = ROOT/'tools/AccoMontage2'
STYLES = {'pop_standard':'标准流行','pop_complex':'复杂流行','dark':'暗色','r&b':'R&B'}
TEXTURE_FILES = ['model_master_final.pt','phrase_data0714.npz','edge_weights_0714.npz',
                 'POP909 4bin quntization/four_beat_song_index.xlsx']


def availability():
    folder = REPO/'chorderator/static'
    missing = [name for name in TEXTURE_FILES if not (folder/name).is_file()]
    return {'installed':(REPO/'chorderator/core.py').is_file(),'texture_ready':not missing,'missing':missing,'styles':STYLES}


def prepare_melody(score, part_index, destination, segmentation=''):
    if not 0<=part_index<len(score.parts):
        raise ValueError('请选择有效的旋律声部')
    part = score.parts[part_index]
    if any(ts.ratioString!='4/4' for ts in part.recurse().getElementsByClass(meter.TimeSignature)):
        raise ValueError('AccoMontage2 编配暂仅支持 4/4 拍')
    events = [n for n in part.recurse().notes if not isinstance(n,harmony.ChordSymbol)]
    if not events:
        raise ValueError('旋律声部没有音符')
    end = 0
    melody = stream.Part()
    for item in sorted(events,key=lambda n:float(n.getOffsetInHierarchy(part))):
        offset = float(item.getOffsetInHierarchy(part))
        if len(item.pitches)!=1 or offset<end-1e-6:
            raise ValueError('请选择单声部旋律；多音或重叠音符请先在 MuseScore 中整理')
        melody.insert(offset,note.Note(item.pitches[0],quarterLength=item.quarterLength))
        end = offset+float(item.quarterLength)
    marks = score.metronomeMarkBoundaries()
    bpm = float(marks[0][2].getQuarterBPM() or 120) if marks else 120
    bpms = {round(float(mark.getQuarterBPM() or bpm),3) for _,_,mark in marks}
    if len(bpms)>1:
        raise ValueError('编配暂不支持变速旋律，请先统一速度')
    bars = math.ceil(end/4)
    if segmentation:
        if not re.fullmatch(r'(?:[A-Z][48])+',segmentation):
            raise ValueError('乐句分段格式应为 A8B8 或 A4B4，每段为 4 或 8 小节')
        padded = sum(int(n) for n in re.findall(r'[A-Z]([48])',segmentation))
        if padded<bars:
            raise ValueError(f'乐句分段不足，旋律至少需要 {bars} 小节')
        if padded-bars>3:
            raise ValueError('乐句分段过长，最多补齐 3 小节尾部休止')
    else:
        padded = math.ceil(bars/4)*4
        remaining = padded
        phrases = []
        while remaining:
            length = 8 if remaining>=8 else 4
            phrases.append('A'+str(length))
            remaining-=length
        segmentation = ''.join(phrases)
    if end<padded*4:
        melody.insert(end,note.Rest(quarterLength=padded*4-end))
    output = stream.Score()
    melody.insert(0,meter.TimeSignature('4/4'))
    melody.insert(0,tempo.MetronomeMark(number=bpm))
    output.append(melody)
    output.write('midi',fp=str(destination))
    return {'segmentation':segmentation,'tempo':bpm,'bars':bars,'padded_bars':padded}
