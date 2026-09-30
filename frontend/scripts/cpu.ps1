# Three one-second samples of total CPU load, one number per line (used by smoke_live.ts).
Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 3 |
  ForEach-Object { '{0:N1}' -f $_.CounterSamples[0].CookedValue }
