% Demo 07 (MATLAB bridge) — regenerates params.mat (run inside MATLAB).
% params.mat is the ".mat alone" demo: browse it with
%   pipeforge-cli matlab snapshot params.mat
gain = 0.5;
fc = 2400;
taps = [0.25 -0.5 0.125 0.0625];
filt.order = 4;
filt.ripple = 0.1;
save('params.mat', 'gain', 'fc', 'taps', 'filt');
