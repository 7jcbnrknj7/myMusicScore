import xml.etree.ElementTree as ET

from music21 import chord, instrument, note, stream
from music import score_notes
from notation import guitar_view, number_pitch, prepare_piano_hands, numbered_native
from test_music import fixture_score


def test_tab_requires_actual_guitar_notes_and_supported_tuning(tmp_path):
    from notation import tablature_parts
    native = tmp_path/'score.mscx'
    def xml(strings):
        native.write_text('<museScore><Score><Part><Instrument><StringData>'+('<string>60</string>'*strings)+'</StringData></Instrument></Part></Score></museScore>')
    score = fixture_score()
    xml(6)
    assert tablature_parts(score,native)==[0]
    xml(11)
    assert tablature_parts(score,native)==[]
    xml(4)
    part = score.parts[0]
    part.partName='Violin'
    part.remove(part.getInstrument())
    part.insert(0,instrument.Violin())
    assert tablature_parts(score,native)==[]
    part.remove(part.getInstrument())
    part.insert(0,instrument.AcousticGuitar())
    for measure in list(part.getElementsByClass(stream.Measure)):
        part.remove(measure)
    xml(6)
    assert tablature_parts(score,native)==[]


def test_guitar_melody_does_not_change_master():
    master = fixture_score()
    before = score_notes(master)
    view = guitar_view(master.parts[0])
    assert [n["pitches"] for n in score_notes(view) if n["part"] == 0] == [[67], [69]]
    assert score_notes(master) == before
    assert [n["pitches"] for n in score_notes(view) if n["part"] == 1] == [[60, 64, 67], [62, 65, 69]]


def test_piano_split_keeps_all_pitches_timing_and_is_idempotent(tmp_path):
    score = stream.Score()
    part = stream.Part()
    part.partName = "Piano"
    part.insert(0, instrument.Piano())
    part.append(chord.Chord([48, 55, 60, 64, 67], quarterLength=2))
    part.append(note.Note(57, quarterLength=2))
    score.append(part)
    def events(s):
        return sorted((e["offset"], e["duration"], p) for e in score_notes(s) for p in e["pitches"])
    before = events(score)
    prepare_piano_hands(score)
    assert len(score.parts) == 2
    assert all(isinstance(p, stream.PartStaff) for p in score.parts)
    assert events(score) == before
    prepare_piano_hands(score)
    assert len(score.parts) == 2
    output = score.write("musicxml", fp=str(tmp_path / "piano.musicxml"))
    from music import read_score
    restored = read_score(output)
    assert len(restored.parts) == 2
    assert events(restored) == before


def test_numbered_pitch_keeps_key_accidentals_octave():
    assert number_pitch(60) == "1"
    assert number_pitch(61) == "#1"
    assert number_pitch(72) == "1<sup>•</sup>"
    assert number_pitch(48) == "1<sub>•</sub>"
    assert number_pitch(67, 1) == "1"
    assert number_pitch(68, -1) == "b3"


def test_native_numbered_preserves_pitches_and_duration_and_mutes_only_view(tmp_path):
    source = tmp_path / "source.mscx"
    source.write_text('<museScore><Score><Part><Staff><StaffType group="pitched"/></Staff></Part>'
                      '<Staff id="1"><Measure><voice><Chord><durationType>16th</durationType>'
                      '<Note><pitch>72</pitch></Note></Chord><Rest><durationType>quarter</durationType>'
                      '</Rest></voice></Measure></Staff></Score></museScore>', encoding="utf-8")
    original = source.read_bytes()
    dest = tmp_path / "view.mscx"
    numbered_native(source, dest, mute=True)
    result = ET.parse(dest)
    assert source.read_bytes() == original
    assert result.findtext(".//Note/pitch") == "72"
    assert result.findtext(".//Chord/durationType") == "16th"
    assert result.findtext(".//Note/play") == "0"
    assert len(result.findall(".//voice/StaffText")) == 4
