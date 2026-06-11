% Demo 02 — Critical path and the pipeline timeline.
% Try:  pipeforge-cli audit 02_normalize3d.m         (or open in the GUI)
% Expect: 48-cycle critical path at 16/12 dominated by the divider (28
% cycles); the timeline shows ux/uy/uz as long orange divider bars and the
% RECIP finding suggests removing two of the three dividers.

n2 = x .* x + y .* y + z .* z;
n  = sqrt(n2);
ux = x ./ n;
uy = y ./ n;
uz = z ./ n;
