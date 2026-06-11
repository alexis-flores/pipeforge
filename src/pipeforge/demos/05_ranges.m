% Demo 05 — Range analysis: overflow, divide-by-near-zero, and an honest
% format recommendation.
%
% Try:   pipeforge-cli ranges 05_ranges.m --range sig=-3:3 --range ref=-1:1 --recommend 0.01
% Expect: 'energy' flagged OVERFLOW RISK at 16/12 (reaches +/-18, max is 8);
%         'ratio' flagged NEAR-ZERO DIVISOR (ref crosses 0) — and the
%         recommendation reports the error budget NOT met: no WIDTH/SCALE can
%         fix a divide whose denominator can hit zero. Fix the math first.
%
% Then:  pipeforge-cli ranges 05_ranges.m --range sig=-3:3 --range ref=0.5:1 --recommend 0.01
% Expect: hazard gone; the recommendation now validates empirically.

energy = sig .* sig * 2;
ratio  = sig ./ ref;
soft   = sqrt(abs(ref)) + 0.5;
