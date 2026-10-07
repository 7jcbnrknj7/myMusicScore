import pytest
from music21 import chord, harmony, instrument, meter, note, stream, tempo
from music import edit_note, playback, recognize_chords, score_notes, transpose_score


def fixture_score():
    score = stream.Score()
    part = stream.Part()
    part.partName = "Acoustic Guitar"
    part.insert(0, instrument.AcousticGuitar())
    bar = stream.Measure(number=1)
    bar.insert(0, meter.TimeSignature("4/4"))
    bar.insert(0, tempo.MetronomeMark(number=120))
    bar.append(chord.Chord([60, 64, 67], quarterLength=2))
    bar.append(chord.Chord([62, 65, 69], quarterLength=2))
    part.append(bar)
    score.append(part)
    return score


def test_chords_are_written_and_not_played_as_extra_notes(tmp_path):
    score = fixture_score()
    before = len(score_notes(score))
    assert recognize_chords(score) == 2
    assert len(score_notes(score)) == before
    symbols = list(score.recurse().getElementsByClass(harmony.ChordSymbol))
    assert [s.figure for s in symbols] == ["C", "Dm"]
    score.write("musicxml", fp=str(tmp_path / "test.musicxml"))
    assert "<harmony>" in (tmp_path / "test.musicxml").read_text(encoding="utf-8")
    assert recognize_chords(score) == 2
    assert len(list(score.recurse().getElementsByClass(harmony.ChordSymbol))) == 2


def test_transpose_preserves_source_positions_and_harmony():
    score = fixture_score()
    recognize_chords(score)
    transpose_score(score, 2)
    assert score_notes(score)[0]["pitches"] == [62, 66, 69]
    assert score_notes(score)[0]["duration"] == 2
    assert list(score.recurse().getElementsByClass(harmony.ChordSymbol))[0].figure == "D"


def test_transpose_rejects_out_of_range():
    score = fixture_score()
    with pytest.raises(ValueError):
        transpose_score(score, 80)


def test_note_edit_and_tempo_playback():
    score = fixture_score()
    edit_note(score, 0, 0, [60, 63, 67], 2)
    assert score_notes(score)[0]["pitches"] == [60, 63, 67]
    events = playback(score)
    assert events[0]["length"] == pytest.approx(1)
    assert events[1]["seconds"] == pytest.approx(1)


def test_violin_does_not_get_guitar_chord_symbols():
    score = fixture_score()
    part = score.parts[0]
    part.partName = "Violin"
    part.remove(part.getInstrument())
    part.insert(0, instrument.Violin())
    assert recognize_chords(score) == 0


def test_unparseable_chord_does_not_lose_notes(monkeypatch,tmp_path):
    from music21 import pitch
    original = harmony.chordSymbolFromChord
    calls = []
    def recognize(value):
        calls.append(value)
        if len(calls)==1:
            raise pitch.AccidentalException('susaddb- is not a supported accidental type')
        return original(value)
    monkeypatch.setattr(harmony,'chordSymbolFromChord',recognize)
    score = fixture_score()
    before = score_notes(score)
    assert recognize_chords(score)==1
    assert [{k:v for k,v in n.items() if k!='index'} for n in score_notes(score)] == [{k:v for k,v in n.items() if k!='index'} for n in before]
    score.write('musicxml',fp=str(tmp_path/'recovered.musicxml'))


def test_unpitched_events_keep_original_indices_and_survive_transpose():
    score=stream.Score()
    part=stream.Part()
    drum=note.Unpitched()
    part.insert(0,drum)
    part.insert(1,note.Note(60))
    score.append(part)
    assert score_notes(score)[0]['index']==1
    assert len(playback(score))==1
    transpose_score(score,2)
    assert len(list(score.recurse().getElementsByClass(note.Unpitched)))==1
    assert score_notes(score)[0]['pitches']==[62]
    with pytest.raises(ValueError,match='unpitched'):
        edit_note(score,0,0,[],1)
