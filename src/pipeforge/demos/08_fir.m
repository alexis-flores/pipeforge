% Demo 08 — Streaming state: a 3-tap FIR with z^-1 delay taps (SD-1).
% delay(x) is the previous sample — one register, zero schedule cycles.
% Co-simulation proves the generated RTL matches the stateful golden model
% bit for bit. To run this same file in MATLAB, see the delay() stub in
% the README ("The MATLAB subset PipeForge understands").

x1 = delay(x);                          % x[k-1]
x2 = delay(x1);                         % x[k-2]
y  = 0.5 .* x + 0.25 .* x1 + 0.25 .* x2;
