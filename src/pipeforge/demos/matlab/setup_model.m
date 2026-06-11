% Demo 07 (MATLAB bridge) — workspace setup: defines what model.m needs.
% Used as: pipeforge-cli matlab snapshot model.m --setup setup_model.m
cfg.gain = 0.5;
cfg.order = 4;
x = [0.25, -0.5, 0.125, 0.0625];
offset = 0.0625;
