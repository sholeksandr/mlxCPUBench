# mlxCPUBench
<pre>
cmdline rguments:

[oleksandrs@mtr-vdi-114 benchmark]$ ./benchmark.py --help
usage: benchmark.py [-h] -i HOST [--cli_user CLI_USER] [--cli_pass CLI_PASSWD]
                    [--shell_user SHELL_USER] [--shell_pass SHELL_PASSWD]
                    [-c CONFIG] [-l] [-v VERBOSE] [-o {csv,xls}] [-f]
                    [--prefix OUT_PREFIX]

optional arguments:
  -h, --help            show this help message and exit
  -i HOST, --ip HOST    Remote host ip address
  --cli_user CLI_USER   cli login
  --cli_pass CLI_PASSWD
                        cli password
  --shell_user SHELL_USER
                        shell login
  --shell_pass SHELL_PASSWD
                        shell password
  -c CONFIG, --config CONFIG
                        benchmark config file name
  -l, --log             Save benchmark test flow output to log file
  -v VERBOSE, --verbose VERBOSE
                        Output verbose level
  -o {csv,xls}, --output_format {csv,xls}
                        Output format for cpu log
  -f, --forse           Don't stop test if found error on bench commands
  --prefix OUT_PREFIX   Test name prefix


Run example:

./benchmark.py -i=10.210.24.195 --config=benchmark_plan_BR.json -v=2 -o=xls -l --prefix=BW_D1527_BOOST
</pre>

