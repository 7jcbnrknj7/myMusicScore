import pytest
from music21 import instrument, meter, note, stream
from arrangement import prepare_melody, STYLES

def melody_score():
    score=stream.Score()
    part=stream.Part()
    part.insert(0,instrument.Violin())
    part.insert(0,meter.TimeSignature('4/4'))
    for offset,pitch in enumerate([60,62,64,65,67,65,64,62]*2):
        part.insert(offset,note.Note(pitch,quarterLength=1))
    score.append(part)
    return score

def test_prepare_monophonic_melody(tmp_path):
    info=prepare_melody(melody_score(),0,tmp_path/'input.mid')
    assert info['segmentation']=='A4'
    assert info['bars']==4
    assert len(STYLES)==4

def test_reject_non_four_four_and_short_phrases(tmp_path):
    score=melody_score()
    score.parts[0].remove(score.parts[0].getElementsByClass(meter.TimeSignature)[0])
    score.parts[0].insert(0,meter.TimeSignature('3/4'))
    with pytest.raises(ValueError,match='4/4'):
        prepare_melody(score,0,tmp_path/'bad.mid')
    with pytest.raises(ValueError,match='格式'):
        prepare_melody(melody_score(),0,tmp_path/'bad.mid','A3')

def test_reject_overlapping_melody(tmp_path):
    score=melody_score()
    score.parts[0].insert(0,note.Note(72))
    with pytest.raises(ValueError,match='单声部'):
        prepare_melody(score,0,tmp_path/'bad.mid')
