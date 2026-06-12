% Demo 07 (MATLAB bridge) — regenerates params.mat (run inside MATLAB).
% params.mat is the ".mat alone" demo: browse it with
%   pipeforge-cli matlab snapshot params.mat
% It packs one of everything the Workspace view can show: scalars, vectors,
% a matrix, integer/logical/single classes, nested struct fields (dotted in
% the table), negative ranges, and a long signal that truncates the preview.

% -- original quartet (kept for the docs/comments that reference them) ----
gain = 0.5;
fc = 2400;
taps = [0.25 -0.5 0.125 0.0625];
filt.order = 4;
filt.ripple = 0.1;

% -- nested struct: browse dotted fields like cfg.adc.vref ----------------
cfg.fs = 48000;
cfg.label = 'demo channel';
cfg.adc.bits = 12;
cfg.adc.vref = 3.3;
cfg.agc.attack = 0.005;
cfg.agc.release = 0.250;
cfg.agc.enabled = true;

% -- assorted classes: Class/Size/Min/Max columns -------------------------
counts = int16([-300 0 150 2047]);
mask = uint8([1 2 4 8 16 32 64 128]);
flags = logical([1 0 1 1]);
temperature = single(36.6);
mixer = [0.7071 -0.7071; 0.7071 0.7071];        % 2x2 rotation
window_coeffs = 0.54 - 0.46 * cos(2*pi*(0:32)' / 32);  % 33-tap Hamming
iq = [1+2i, 3-4i, -2+0.5i];                      % complex: real part shown

% -- big vector: exceeds the 4096-value preview cap (shows ", ...") -------
chirp_signal = sin(2*pi*(0:4999).^2 / 1e6) * 0.9;

save('params.mat', 'gain', 'fc', 'taps', 'filt', 'cfg', 'counts', 'mask', ...
    'flags', 'temperature', 'mixer', 'window_coeffs', 'iq', 'chirp_signal');
