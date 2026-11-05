# Circuit: 3-stage amplifier (CS - CE - CC), VCC = 15 V
- Source: 10 kOhm source resistance, 1 kHz signal. Load RL = 250 Ohm (AC coupled).
- Stage 1, CS: NMOS M1 (2N7000), gate bias RG1=3M / RG2=1.5M, RD1=620, RS1=200 (bypassed). Node d1 = drain.
- Stage 2, CE: NPN Q2 (BF=150, VAF=80), base bias R1=R2=2k, RC2=7.46k, emitter resistor RE2 (bypassed by C4). Node c2 = collector.
- Stage 3, CC (emitter follower): NPN Q3 (BF=80, VAF=60), base bias R3=50k / R4=100k, emitter resistor RE3. Node e3 = emitter, AC-coupled to RL.
- Stages are AC-coupled with 10 uF capacitors.
Measurements: gain = |vout/vs|, rin = input resistance seen after the 10k source resistor, rout = resistance looking into e3 (RL removed),
av1/av2/av3 = per-stage gains, vce2/vce3/vds1 = DC operating voltages, ic2/ic3/id1 = DC currents.
