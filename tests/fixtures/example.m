% example.m — nkMatlib latency audit showcase
% Sections exercise each finding the auditor knows about.

% 3D vector normalization (RECIP showcase)
n2 = x .* x + y .* y + z .* z;
n  = sqrt(n2);
ux = x ./ n;
uy = y ./ n;
uz = z ./ n;

% Constant divisions (CDIV)
ph = a / 8;     % power of two -> shift
pt = b / 3;     % multiply by 1/3

% Serial division (SERDIV)
w = c / d / e;

% Integer power (POW)
p4 = q ^ 4;

% Common subexpression (CSE)
s1 = (u + v) .* k1;
s2 = (u + v) .* k2;

% Fusible three-input add (FUSE)
t3 = a + b + c;

% Feedback accumulator (FEEDBACK)
for i = 1:16
    acc = acc + t3;
end
