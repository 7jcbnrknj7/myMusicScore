import wave
import numpy as np


def render_preview(events, output, checkpoint=lambda: None):
    rate = 22050
    duration = max((e['seconds']+e['length'] for e in events),default=0)+.3
    if duration > 1800:
        raise ValueError('合成试听最长支持 30 分钟')
    samples = np.zeros(int(duration*rate)+1,dtype=np.float32)
    for event in events:
        checkpoint()
        start = int(event['seconds']*rate)
        length = max(1,int(event['length']*rate))
        t = np.arange(length,dtype=np.float32)/rate
        envelope = np.minimum(t/.015,1)*np.minimum((length/rate-t)/.04,1)*np.exp(-t*1.5)
        for pitch in event['pitches']:
            frequency = 440*2**((pitch-69)/12)
            signal = (np.sin(2*np.pi*frequency*t)+.2*np.sin(4*np.pi*frequency*t))*envelope*.14
            samples[start:start+length] += signal[:len(samples[start:start+length])]
    peak = np.max(np.abs(samples))
    if peak > .95:
        samples *= .95/peak
    checkpoint()
    temporary = output.with_suffix('.tmp')
    with wave.open(str(temporary),'wb') as handle:
        handle.setparams((1,2,rate,0,'NONE','not compressed'))
        handle.writeframes((samples*32767).astype('<i2').tobytes())
    temporary.replace(output)
