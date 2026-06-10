% 3D vector normalization — RECIP showcase fixture
n2 = x .* x + y .* y + z .* z;
n  = sqrt(n2);
ux = x ./ n;
uy = y ./ n;
uz = z ./ n;
