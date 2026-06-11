% Demo 03 — A matched MATLAB/SystemVerilog pair (see 03_pipeline.sv).
% Try:  pipeforge-cli lint 03_pipeline.sv                       (clean)
%       pipeforge-cli codegen 03_pipeline.m -m demo_pipeline    (compare!)
%       pipeforge-cli cosim 03_pipeline.m --sv 03_pipeline.sv \
%           --top demo_pipeline --include <matlib rtl> --source <deps...>
% Expect: the lint is clean; codegen emits an equivalent module; co-sim
% matches the golden model bit-for-bit on every vector.

prod = a .* b;
y = prod + c;
