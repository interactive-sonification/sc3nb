~resourcePath = PathName.new("../sc3nb/resources/synthdefs").absolutePath;

SynthDef("s1",
	{ | freq=400, dur=0.4, att=0.01, amp=0.3, num=4, pan=0 |
		Out.ar(0, Pan2.ar(
				Blip.ar(freq,  num) * EnvGen.kr(Env.perc(att, dur, 1, -2), doneAction: Done.freeSelf),
				pan,
				amp))
}).writeDefFile(~resourcePath);

SynthDef("s2",
	{ | freq=400, amp=0.3, num=4, pan=0, lg=0.1, gate=1 |
		Out.ar(0, Pan2.ar(
				Blip.ar(freq.lag(lg),  num) * EnvGen.kr(Env.asr(0.0, 1.0, 1.0), gate, doneAction: Done.freeSelf)),
				pan.lag(lg),
				amp.lag(lg))
}).writeDefFile(~resourcePath);
