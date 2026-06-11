% builds the workspace demo.m operates on
cfg.gain = 0.5;
cfg.filter.taps = 4;
x = [0.25, -0.5, 0.125];
A = [1 2; 3 4] * 0.125;
offset = 0.0625;
if exist('fi', 'file')
    z = fi(0.75, 1, 18, 14);
else
    z = 0.75;
end
big = linspace(-1, 1, 6000);
