"""One isolated upstream core per task; no global engine state is shared."""
import json
import re
from pathlib import Path
import sys
from arrangement import REPO, availability

def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    if spec['texture'] and not availability()['texture_ready']:
        raise RuntimeError('完整伴奏模型资源缺失：'+', '.join(availability()['missing']))
    sys.path.insert(0,str(REPO))
    import chorderator as cdt
    from chorderator.utils.models.PreProcessor import PreProcessor
    analyze = PreProcessor._PreProcessor__analyze_midi
    lengths = [int(n)*16 for n in re.findall(r'[A-Z]([48])',spec['segmentation'])]
    def exact_phrases(processor):
        # Upstream rounds an exact four-bar ending up to eight bars.
        sequence = [n for phrase in analyze(processor) for n in phrase]
        sequence = (sequence+[0]*sum(lengths))[:sum(lengths)]
        phrases = []
        offset = 0
        for length in lengths:
            phrases.append(sequence[offset:offset+length])
            offset += length
        return phrases
    PreProcessor._PreProcessor__analyze_midi = exact_phrases
    core = cdt.get_chorderator()
    from chorderator.chords.ChordProgression import read_progressions
    from chorderator.utils.models.DP import DP
    progressions = read_progressions('dict')
    core.set_cache(dict=progressions)
    DP.SOLVE_ONLY_WITH_THESE_PROGRESSIONS = [ident for ident,variants in progressions.items()
        if any(p.progression_class.get('new_label')==spec['style'] and p.reliability>=0.8 for p in variants)]
    if not DP.SOLVE_ONLY_WITH_THESE_PROGRESSIONS:
        raise RuntimeError('没有符合所选风格的编配素材')
    core.set_melody(spec['melody'])
    core.set_meta(tonic=spec['tonic'],mode=spec['mode'],meter='4/4')
    core.set_segmentation(spec['segmentation'])
    core.set_output_style(spec['style'])
    core.set_texture_prefilter((spec['rhythm'],spec['voices']))
    core.generate_save(spec['output'],task='chord_and_textured_chord' if spec['texture'] else 'chord',log=True,wav=False)
    log = json.loads((Path(spec['output'])/'chord_gen_log.json').read_text())
    if any(item.get('style')!=spec['style'] for item in log):
        raise RuntimeError('生成结果未满足所选风格，原版本已保留')
    print('AccoMontage2 arrangement complete',flush=True)

if __name__=='__main__':
    main()
