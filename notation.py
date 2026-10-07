"""Derived notation views. MusicXML remains the editable source of truth."""
import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from music21 import chord, clef, harmony, instrument, layout, note, stream, tempo


def kind(part):
    inst = part.getInstrument()
    name = (part.partName or "").lower()
    if isinstance(inst, instrument.Guitar) or inst.midiProgram in range(24, 32) or "guitar" in name or "吉他" in name:
        return "guitar"
    if isinstance(inst, instrument.KeyboardInstrument) or inst.midiProgram in range(0, 8) or "piano" in name or "钢琴" in name:
        return "piano"
    return "other"


def tablature_parts(score, native):
    """Only sounding guitar/bass parts with supported tuning get TAB."""
    from muscriptor.utils.sheets import TAB_PRESETS
    parts = ET.parse(native).getroot().find('Score').findall('Part')
    eligible = []
    for index, (part, xml) in enumerate(zip(score.parts,parts)):
        inst = part.getInstrument()
        plucked = kind(part)=='guitar' or isinstance(inst,instrument.ElectricBass) or inst.midiProgram in range(32,40)
        sounding = any(not isinstance(n,harmony.ChordSymbol) for n in part.recurse().notes)
        strings = len(xml.findall('Instrument/StringData/string'))
        if plucked and sounding and strings in TAB_PRESETS:
            eligible.append(index)
    return eligible


def retain_tab_instruments(native, indices):
    tree = ET.parse(native)
    for index, part in enumerate(tree.getroot().find('Score').findall('Part')):
        if index not in indices:
            inst = part.find('Instrument')
            if inst is not None:
                for data in inst.findall('StringData'):
                    inst.remove(data)
    tree.write(native,encoding='utf-8',xml_declaration=True)


def native_tablature_parts(native):
    from muscriptor.utils.sheets import TAB_PRESETS
    score = ET.parse(native).getroot().find('Score')
    eligible = []
    for index, part in enumerate(score.findall('Part')):
        inst = part.find('Instrument')
        if inst is None:
            continue
        identity = ' '.join(inst.findtext(k,'') for k in ('instrumentId','trackName','longName')).lower()
        plucked = 'guitar' in identity or ('bass' in identity and 'electric' in identity)
        ids = {s.get('id') for s in part.findall('Staff')}
        sounding = any(s.findall('.//Note') for s in score.findall('Staff') if s.get('id') in ids)
        if plucked and sounding and len(inst.findall('StringData/string')) in TAB_PRESETS:
            eligible.append(index)
    return eligible


def prepare_piano_hands(score):
    """Keep existing PartStaff assignments; only split unassigned single staves."""
    for part in list(score.parts):
        if kind(part) != "piano" or isinstance(part, stream.PartStaff):
            continue
        if any(word in (part.partName or "").lower() for word in ("left", "right", "左手", "右手", "rh", "lh")):
            continue
        hands = []
        for right in (True, False):
            hand = stream.PartStaff()
            hand.partName = (part.partName or "Piano") + (" 右手（自动）" if right else " 左手（自动）")
            hand.insert(0, copy.deepcopy(part.getInstrument()))
            for measure in part.makeMeasures().getElementsByClass(stream.Measure):
                bar = copy.deepcopy(measure)
                for item in list(bar.recurse().notes):
                    if isinstance(item, harmony.ChordSymbol):
                        if not right:
                            item.activeSite.remove(item)
                        continue
                    pitches = [p for p in item.pitches if (p.midi >= 60) == right]
                    if not pitches:
                        replacement = note.Rest(quarterLength=item.quarterLength)
                    elif len(pitches) == len(item.pitches):
                        continue
                    else:
                        replacement = chord.Chord(pitches, quarterLength=item.quarterLength)
                        replacement.tie = copy.deepcopy(item.tie)
                    item.activeSite.replace(item, replacement)
                for old in list(bar.recurse().getElementsByClass(clef.Clef)):
                    old.activeSite.remove(old)
                hand.insert(measure.offset, bar)
            hand.insert(0, clef.TrebleClef() if right else clef.BassClef())
            hands.append(hand)
        offset = part.offset
        score.remove(part)
        for hand in hands:
            score.insert(offset, hand)
        score.insert(0, layout.StaffGroup(hands, name=part.partName or "Piano", symbol="brace", barTogether=True))
    return score


def guitar_view(part):
    melody = copy.deepcopy(part)
    melody.partName = "旋律简谱 + 和弦"
    for item in list(melody.recurse().notes):
        if isinstance(item, harmony.ChordSymbol):
            continue
        if isinstance(item, chord.Chord):
            replacement = note.Note(max(item.pitches, key=lambda p: p.midi))
            replacement.duration = copy.deepcopy(item.duration)
            replacement.tie = copy.deepcopy(item.tie)
            item.activeSite.replace(item, replacement)
    accompaniment = copy.deepcopy(part)
    accompaniment.partName = (part.partName or "Guitar") + " 六线谱"
    for symbol in list(accompaniment.recurse().getElementsByClass(harmony.ChordSymbol)):
        symbol.activeSite.remove(symbol)
    for mark in list(accompaniment.recurse().getElementsByClass(tempo.MetronomeMark)):
        mark.activeSite.remove(mark)
    score = stream.Score()
    score.append(melody)
    score.append(accompaniment)
    score.insert(0, layout.StaffGroup([melody, accompaniment], symbol="bracket", barTogether=True))
    return score


def piano_view(score):
    result = copy.deepcopy(score)
    for part in list(result.parts):
        if kind(part) != "piano":
            result.remove(part)
    return result


def put(parent, tag, value):
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = str(value)
    return child


KEYS = {0: ("C", 0), 1: ("G", 7), 2: ("D", 2), 3: ("A", 9), 4: ("E", 4),
        5: ("B", 11), 6: ("F#", 6), 7: ("C#", 1), -1: ("F", 5), -2: ("Bb", 10),
        -3: ("Eb", 3), -4: ("Ab", 8), -5: ("Db", 1), -6: ("Gb", 6), -7: ("Cb", 11)}
SHARPS = ("1", "#1", "2", "#2", "3", "4", "#4", "5", "#5", "6", "#6", "7")
FLATS = ("1", "b2", "2", "b3", "3", "4", "b5", "5", "b6", "6", "b7", "7")


def number_pitch(pitch, key_signature=0):
    _, root = KEYS.get(key_signature, KEYS[0])
    relative = pitch - (60 + root)
    octave, pc = divmod(relative, 12)
    text = (FLATS if key_signature < 0 else SHARPS)[pc]
    if octave:
        tag = "sup" if octave > 0 else "sub"
        text += f"<{tag}>" + "•" * abs(octave) + f"</{tag}>"
    return text


def number_duration(text, duration_type, dots=0):
    underlines = {"eighth": 1, "16th": 2, "32nd": 3, "64th": 4, "128th": 5}.get(duration_type, 0)
    if underlines:
        text = "<u>" + text + "</u>"
    extension = {"half": " -", "whole": " - - -", "breve": " - - - - - - -"}.get(duration_type, "")
    if text == "0" and extension:
        extension = extension.replace("-", "0")
    return text + extension + " ·" * dots


def text_element(value, y=0):
    element = ET.Element("StaffText")
    put(element, "style", "staff")
    put(element, "autoplace", 0)
    put(element, "fontFace", "Arial")
    put(element, "fontSize", 12)
    ET.SubElement(element, "offset", {"x": "0", "y": str(y)})
    text = ET.SubElement(element, "text")
    wrapper = ET.fromstring("<wrapper>" + value + "</wrapper>")
    text.text = wrapper.text
    for child in wrapper:
        text.append(child)
    return element


def numbered_native(source, destination, indices=None, mute=False):
    tree = ET.parse(source)
    score = tree.getroot().find("Score")
    staffs = score.findall("Staff")
    definitions = [staff for part in score.findall("Part") for staff in part.findall("Staff")]
    selected = set(range(len(staffs))) if indices is None else set(indices)
    put(score, "showInvisible", 0)
    for index, (staff, definition) in enumerate(zip(staffs, definitions)):
        if index not in selected:
            continue
        staff_type = definition.find("StaffType")
        for tag, value in (("invisible", 1), ("clef", 0), ("keysig", 0), ("stemless", 1), ("ledgerlines", 0)):
            put(staff_type, tag, value)
        signature = 0
        for mi, measure in enumerate(staff.findall("Measure")):
            for vi, voice in enumerate(measure.findall("voice")):
                if mi == 0 and vi == 0:
                    signature = int(voice.findtext("KeySig/concertKey", voice.findtext("KeySig/accidental", "0")))
                    if index == min(selected):
                        voice.insert(0, text_element("1=" + KEYS.get(signature, KEYS[0])[0], -7))
                    if len(staffs) == 2 and len(score.findall("Part")) == 1:
                        label = text_element("右手" if index == 0 else "左手", 1)
                        label.find("offset").set("x", "-10")
                        voice.insert(0, label)
                for item in list(voice):
                    if item.tag == "KeySig":
                        signature = int(item.findtext("concertKey", item.findtext("accidental", "0")))
                        if mi:
                            voice.insert(list(voice).index(item), text_element("1=" + KEYS.get(signature, KEYS[0])[0], -7))
                        put(item, "visible", 0)
                    elif item.tag in ("Chord", "Rest"):
                        put(item, "visible", 0)
                        notes = item.findall("Note")
                        rows = [number_pitch(int(n.findtext("pitch", "60")), signature) for n in reversed(notes)] or ["0"]
                        for n in notes:
                            put(n, "visible", 0)
                            if mute:
                                put(n, "play", 0)
                            for acc in n.findall("Accidental"):
                                put(acc, "visible", 0)
                        duration_type = item.findtext("durationType", "quarter")
                        if duration_type == "measure":
                            duration_type = "whole"
                        rows = [number_duration(row, duration_type, int(item.findtext("dots", "0"))) for row in rows]
                        voice.insert(list(voice).index(item), text_element("\n".join(rows), 1 + 3 * vi))
                        extra_lines = {"16th": 1, "32nd": 2, "64th": 3, "128th": 4}.get(duration_type, 0)
                        for ri in range(len(rows)):
                            for line in range(extra_lines):
                                underline = text_element("_", 1.6 + 3 * vi + 1.8 * ri + 0.3 * line)
                                voice.insert(list(voice).index(item), underline)
                    elif item.tag in ("Clef", "Beam"):
                        put(item, "visible", 0)
    tree.write(destination, encoding="utf-8", xml_declaration=True)


def guitar_tab_native(source, destination):
    from muscriptor.utils.sheets import _retype_as_tablature, TAB_PRESETS
    tree = ET.parse(source)
    parts = tree.getroot().find("Score").findall("Part")
    # The first part is a derived melody, the second retains the full guitar.
    second = parts[1]
    strings = len(second.findall("Instrument/StringData/string"))
    if strings != 6:
        raise ValueError("组合吉他谱需要六弦吉他调弦信息")
    _retype_as_tablature(second.find("Staff"), TAB_PRESETS[strings], strings)
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    numbered_native(destination, destination, indices=[0], mute=True)


def export_views(score, folder, binary, run_process):
    log = folder / "notation-export.log"

    def native(name, view):
        xml = folder / (name + ".musicxml")
        view.write("musicxml", fp=str(xml))
        mscx = folder / (name + ".mscx")
        run_process([binary, "-o", str(mscx), str(xml)], log, 180)
        return mscx

    def export(name, mscx):
        for ext in ("pdf", "mscz"):
            target = folder / (name + "." + ext)
            run_process([binary, "-o", str(target), str(mscx)], log, 180)
            if not target.is_file() or not target.stat().st_size:
                raise RuntimeError("谱式导出失败: " + target.name)

    for index, part in enumerate(score.parts):
        if kind(part) == "guitar" and any(not isinstance(n,harmony.ChordSymbol) for n in part.recurse().notes):
            name = f"guitar-{index + 1}-combined"
            mscx = native(name, guitar_view(part))
            second = ET.parse(mscx).getroot().find('Score').findall('Part')[1]
            if len(second.findall('Instrument/StringData/string')) != 6:
                continue
            guitar_tab_native(mscx, mscx)
            export(name, mscx)
    if any(kind(p) == "piano" for p in score.parts):
        mscx = native("piano-staff", piano_view(score))
        export("piano-staff", mscx)
        numbered = folder / "piano-numbered.mscx"
        numbered_native(mscx, numbered)
        export("piano-numbered", numbered)
