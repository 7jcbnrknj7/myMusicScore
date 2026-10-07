from pathlib import Path
from music21 import chord, converter, harmony, instrument, note, pitch, stream, tempo


def read_score(path):
    score = converter.parse(str(path))
    return score


def score_notes(score):
    result = []
    for pi, part in enumerate(score.parts):
        for ni, item in enumerate(part.recurse().notes):
            if isinstance(item, harmony.ChordSymbol):
                continue
            pitches = item.pitches
            # Drum events remain in the score, not the pitched-note editor/synth.
            if not pitches:
                continue
            result.append({"part": pi, "index": ni, "offset": float(item.getOffsetInHierarchy(part)),
                           "duration": float(item.quarterLength), "pitches": [p.midi for p in pitches],
                           "names": [p.nameWithOctave for p in pitches]})
    return result


def describe_score(score):
    return [{"index": i, "name": p.partName or p.getInstrument().instrumentName or f"Part {i + 1}"}
            for i, p in enumerate(score.parts)]


def playback(score):
    marks = score.metronomeMarkBoundaries()
    def seconds_at(offset):
        elapsed = 0.0
        for start, end, mark in marks:
            if offset <= start:
                break
            elapsed += float(mark.durationToSeconds(min(offset, end) - start))
            if offset <= end:
                return elapsed
        return elapsed
    events = score_notes(score)
    for ev in events:
        ev["seconds"] = seconds_at(ev["offset"])
        ev["length"] = max(0.03, seconds_at(ev["offset"] + ev["duration"]) - ev["seconds"])
    return events


def transpose_score(score, semitones, part_index=None):
    selected = score if part_index is None else score.parts[part_index]
    symbols = [(h, harmony.ChordSymbol(h.figure).transpose(semitones))
               for h in selected.recurse().getElementsByClass(harmony.ChordSymbol)]
    for n in selected.recurse().notes:
        pitches = n.pitches
        if any(not 0 <= p.midi + semitones <= 127 for p in pitches):
            raise ValueError("Transposition exceeds MIDI pitch range")
    selected.transpose(semitones, inPlace=True)
    # Stream.transpose changes pitches without refreshing Harmony's root/figure.
    for original, transposed in symbols:
        original.activeSite.replace(original, transposed)
    # Old TAB string/fret annotations cannot be trusted after changing pitch.
    for n in selected.recurse().notes:
        n.articulations = [a for a in n.articulations if a.__class__.__name__ not in ("StringIndication", "FretIndication")]
    return score


def edit_note(score, part_index, index, pitches, duration):
    part = score.parts[part_index]
    target = list(part.recurse().notes)[index]
    if isinstance(target, harmony.ChordSymbol):
        raise ValueError("Edit harmony in MuseScore")
    if not target.pitches:
        raise ValueError("Edit unpitched percussion in MuseScore")
    if len(pitches) != len(target.pitches):
        raise ValueError("Keep the same number of pitches; use MuseScore to add/remove notes")
    for p, value in zip(target.pitches, pitches):
        p.midi = value
    target.quarterLength = duration
    target.articulations = [a for a in target.articulations if a.__class__.__name__ not in ("StringIndication", "FretIndication")]
    return score


def recognize_chords(score, part_index=None):
    selected = list(score.parts) if part_index is None else [score.parts[part_index]]
    count = 0
    for part in selected:
        inst = part.getInstrument()
        program = inst.midiProgram
        name = (part.partName or "").lower()
        if not (isinstance(inst, (instrument.Guitar, instrument.KeyboardInstrument)) or
                program in range(0, 8) or program in range(24, 32) or
                any(x in name for x in ("piano", "guitar", "钢琴", "吉他"))):
            continue
        for old in list(part.recurse().getElementsByClass(harmony.ChordSymbol)):
            old.activeSite.remove(old)
        analyzed = part.chordify()
        previous = None
        for c in analyzed.recurse().getElementsByClass(chord.Chord):
            if len(set(c.pitchClasses)) < 3:
                previous = None
                continue
            try:
                symbol = harmony.chordSymbolFromChord(c)
            except (ValueError, harmony.HarmonyException, pitch.AccidentalException):
                # Some inferred suspended/add chords cannot be parsed by music21.
                # Keep their notes, omit only the unsupported chord annotation.
                previous = None
                continue
            if not symbol.figure or "cannot" in symbol.figure.lower():
                continue
            offset = float(c.getOffsetInHierarchy(analyzed))
            if symbol.figure == previous:
                continue
            symbol.writeAsChord = False
            # Insert into a measure so harmony survives MusicXML export.
            measures = list(part.getElementsByClass(stream.Measure))
            candidates = [m for m in measures if float(m.offset) <= offset]
            if candidates:
                target = candidates[-1]
                target.insert(offset - float(target.offset), symbol)
            else:
                part.insert(offset, symbol)
            previous = symbol.figure
            count += 1
    return count
