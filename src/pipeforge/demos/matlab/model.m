% Demo 07 (MATLAB bridge) — the DSP script, run after setup_model.m.
% Try:  pipeforge-cli matlab snapshot model.m --setup setup_model.m
%       pipeforge-cli matlab validate model.m --setup setup_model.m
% Expect: snapshot lists cfg.gain/cfg.order as dotted struct fields with
% types and values; validate reports y bit-clean and n within an LSB.

y = cfg.gain * x + offset;
n = norm(x);
