% Demo 01 — Audit findings: every optimization the auditor knows.
% Try:  pipeforge-cli audit 01_findings.m
% Expect: RECIP, CDIV (x2), SERDIV, POW, CSE, FUSE, FEEDBACK findings,
% each with a line number, cycle savings, and a concrete rewrite.

% RECIP: three divisions share the divisor n -> compute 1/n once
n2 = x .* x + y .* y + z .* z;
n  = sqrt(n2);
ux = x ./ n;
uy = y ./ n;
uz = z ./ n;

% CDIV: divide by a constant (power of two -> shift; else multiply)
ph = a / 8;
pt = b / 3;

% SERDIV: serial division chain -> combine the divisors
w = c / d / e;

% POW: integer power as a multiply chain -> square-and-multiply
p4 = q ^ 4;

% CSE: (u + v) computed twice -> compute once and PIPE it
s1 = (u + v) .* k1;
s2 = (u + v) .* k2;

% FUSE: a + b + c -> one matadd3 stage
t3 = a + b + c;

% FEEDBACK: acc depends on itself across a non-constant trip count ->
% a true recurrence; the initiation interval is reported. (A *constant*
% bound would unroll into pipeline stages instead: the UNROLL finding.)
for i = 1:niter
    acc = acc + t3;
end
