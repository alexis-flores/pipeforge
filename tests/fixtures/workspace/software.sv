// Hand-written `software` mirror of params.mat (WS-2 fixture).
// Reconciled against the .mat by WS-3; values intentionally mirror make_params.m.

typedef struct {
  real gain;
  real fc;
  real taps [0:3];
} software_t;

localparam software_t software = '{
  gain: 0.5,                                   // scalar constant
  fc:   2400.0,
  taps: '{0.25, -0.5, 0.125, 0.0625},          // 1x4 vector
  filt: '{ order: 4.0, ripple: 0.1 },          // nested struct
  cfg:  '{
    fs:  48000.0,
    adc: '{ bits: 12.0, vref: 3.3 }            // doubly nested
  },
  mixer: '{ '{0.7071, -0.7071}, '{0.7071, 0.7071} }  // 2x2 matrix
};
