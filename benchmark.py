#!/usr/local/bin/python2.7

# pylint: disable=old-style-class, no-init, missing-docstring, line-too-long
# pylint: disable=too-few-public-methods
# pylint: disable= C0103

'''
Created on Dec 05, 2019

Author: Oleksandr Shamray <oleksandrs@mellanox.com>
Version: 1.0

Description: This util provide automation for the  benchmarking remote system with ONYX

1. Command line parameters:

usage: benchmark.py [-h] -i HOST [--cli_user CLI_USER] [--cli_pass CLI_PASSWD]
                    [--shell_user SHELL_USER] [--shell_pass SHELL_PASSWD]
                    [-c CONFIG] [-l] [-v VERBOSE] [-o {csv,xls}] [-f]

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


output results :
2. ./01_01_2019_12_00/
           test_summary.log
           test1_cpu.csv
           test2_cpu.csv
           ...
           tes3_cpu.csv

test_summary.log format:
[test1_name]: start=10/10/10 10:10:10; end=10/10/10 10:11:15; overal_duration=65; test_duration=65,
[test2_name]: start=10/10/10 10:11:20; end=10/10/10 10:12:43; overal_duration=65; test_duration=83
...


cpu_load.csv format:

'''


#############################
# Global imports
#############################
import sys
import json
import argparse
import subprocess
import threading
import os.path
import paramiko
import re
import time
import socket
from datetime import datetime
from collections import OrderedDict

try:
    xls_format_ena = True
    import openpyxl
except ImportError:
    xls_format_ena = False
    # module doesn't exist, deal with it.

import bench_report
import pdb

#############################
# Global const
#############################
# default name of benchmark config. Used in not specified in cmd line parameters
CONFIG_NAME_DEF = 'benchmark_plan.json'

# name of benchmark log file
LOG_FILENAME = 'test.log'

# date-time format of test results in benchmark summary file
TEST_REPORT_DATETIME_FORMAT = "%H:%M:%S"

# remote switch filename of CPU mon log
CPUMON_FILENAME = '/tmp/cpu_mon'


CPUMON_POLL_TIME_DEF = 1

# remote switch filename of log file form whichgor start/stop tests timestump
REMOTE_LOG_FILE = '/var/log/messages'

# set 'test_begin_mark'/'test_end_mark' to is value in json config if we want to use gettime instead of log analising
NONE_MARK = ''

# regexp to extract time from the switch messages log
# 12:25:23
TIMESTAMP_REGEXP = '[0-2]?[0-9]:[0-5]?[0-9]:[0-5]?[0-9]'

CLI_CMD_LINE_REGEX = "\[\S.*\].* [>|#]|Rebooting...|Type 'YES' to confirm reset|Resetting and rebooting the system|Do you want to use the wizard for initial configuration"

TEST_REPORT_FORMAT = "Test [{test_name}]: start={start}; end={end}; overal_duration={overal_time}, test_duration={test_time} extra: {extra_info}"

# Maximum CMD execution time. Since it can take much of time we set it 1 hour
CMD_TIMEOUT = 3600

RCV_POLL_TIME = 120

# default credentials for ONYX
SHELL_USER = 'root'
SHELL_PASS = ''
CLI_USER = 'admin'
CLI_PASS = 'admin'


#############################
# Global variables
#############################
config = {}


class logger(object):
    '''
    Logger fot savre log to sile and print results to screen
    '''

    def __init__(self):
        self.logfile_name = ''
        self.logfile = None
        self.verbose = 0

    def open(self, logfile, mode="w+", verbose=0):
        '''
        @summary: prepare looger to operate
        @param logfile: logfile name. Set '' if not logfile needed
        @param logfile write mode: can be 'w' rewrite file
               even it exists or 'w+' - append if file exists
        @param verbose: set default erbose level. Logger will
               not display/save mesasges with verbose lower then set
        '''
        self.logfile_name = logfile
        self.verbose = int(verbose)
        if logfile:
            try:
                self.logfile = open(logfile, mode)
            except IOError as err:
                print "I/O error({0}): {1} with log file {2}".format(err.errno,
                                                                     err.strerror,
                                                                     self.logfile)

    def info(self, msg='', verbose_level=0):
        '''
        @summary: print information log message. Will also save message to
                  file if it defined in 'open'
        @param msg: message string
        @param verbose_level: mesage verbose level. logger will not print msg
               if it have verbese lower then defined in 'open'
        '''
        if self.verbose >= verbose_level:
            if self.logfile:
                self.logfile.write("[INFO] {}: {}\n".format(datetime.now().time(), msg))
            print msg

    def err(self, msg='', verbose_level=0):
        '''
        @summary: print error log message. Will also save message to file
                  if it defined in 'open'
        @param msg: message string
        @param verbose_level: mesage verbose level. logger will not print msg
               if it have verbese lower then defined in 'open'
        '''
        if self.verbose >= verbose_level:
            if self.logfile:
                self.logfile.write("[ERR] {}: {}\n".format(datetime.now().time(), msg))
            print msg

    def __del__(self):
        if self.logfile is not None:
            self.logfile.close()


log = logger()

#------------------------------------------------------------

class Command(object):
    '''
    @summary: Run system commands with timeout
    '''

    def __init__(self, cmd):
        self.cmd = cmd
        self.process = None
        self.out = None
        self.err = ''

    def run_command(self, capture=False):
        if not capture:
            self.process = subprocess.Popen(self.cmd, shell=True)
            self.process.communicate()
            return
        # capturing the outputs of shell commands
        self.process = subprocess.Popen(self.cmd, shell=True,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        stdin=subprocess.PIPE)
        out, err = self.process.communicate()
        self.err = err
        if len(out) > 0:
            self.out = out
        else:
            self.out = None

    # set default timeout to 2 minutes
    def run(self, capture=False, timeout=120):
        thread = threading.Thread(target=self.run_command, args=(capture,))
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self.process.terminate()
            self.process.kill()
            thread.join()
            self.out = None
            self.err = "Command timeout, kill it: \"%s\" " % self.cmd
        return self.out, self.err

#------------------------------------------------------------

def ping_system(host_ip, timeout=120):
    '''
    @summary: ping selected host
    @param ip: host ip
    @return: False if ping not successfull
    '''
    res = False
    time_start = time.time()
    while time.time() - time_start < timeout:
        cmd = 'ping -c 1 -w 1 {}'.format(host_ip)

        output, __ = Command(cmd).run(True)

        pattern = '(?P<transmitted>\d+) packets transmitted, (?P<received>\d+) received,'
        match = re.search(pattern, output, re.MULTILINE | re.DOTALL)
        if match is None:
            log.err("Ping command failed to run correctly.\nOutput:\n{}".format(output))
            break

        ping_dict = match.groupdict()
        if ping_dict["transmitted"] == ping_dict["received"]:
            res = True
            break
        log.info("Ping not recieved. Continue...", 1)
    
    if not res:
        log.err("system {} no responding:\n{}".format(host_ip, output))
    else:
        log.info("Ping recived in {} sec".format(int(time.time() - time_start)), 2)
    return res

#------------------------------------------------------------

def parse_cli_cmd_output(output, regex=CLI_CMD_LINE_REGEX):
    if not re.findall(regex, output):
        return None

    output_lines = output.splitlines()
    return '\n\r'.join(output_lines[1:-1])

#------------------------------------------------------------

def open_ssh_conn(host, user, password, port=22, timeout=120):

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=host, username=user, password=password, port=port, timeout=timeout)
    client_shell = client.invoke_shell()
    time.sleep(2)
    return client, client_shell

#------------------------------------------------------------

def wait_cli_conn_login(ssh_shell, timeout=CMD_TIMEOUT):
    '''

    '''
    ssh_shell.send('\n')
    ssh_shell.settimeout(RCV_POLL_TIME)

    output = ssh_shell.recv(65535)
    data = parse_cli_cmd_output(output)

    time_start = time.time()
    while not data and (time.time() - time_start < timeout):
        try:
            output += ssh_shell.recv(65535)
        except socket.timeout:
            pass
        data = parse_cli_cmd_output(output)
        if data:
            break
        time.sleep(10)
    res = data is not None    
    if not res:
        log.err("login to clifailed")
    else:
        log.info("logged to cli in {} sec".format(int(time.time() - time_start)), 2)

    return data is not None

#------------------------------------------------------------

def run_ssh_cmd(conn, cmd, force=False):
    '''
    @summary run cmd on remote host with ssh
    @param  conn: ssh connection
    @param cmd: command which we want to run
    @return: out, err: cmd output from stdout, stder streams
    '''

    log.info("run shell cmd: {}".format(cmd), 1)
    __, stdout, stderr = conn.exec_command(cmd)
    err = stderr.read()
    if err:
        log.err("Command '{}' returned error message '{}'".format(cmd, err))

    data = stdout.read() + err
    return data, err

#------------------------------------------------------------

def run_mlnx_cmd_cli(ssh_shell, cmd, timeout=CMD_TIMEOUT, force=False):
    '''
    @summary run cmd on remote host with cli ssh
    @param  conn: ssh shell session
    @param cmd: command which we want to run
    @return: cmd output
    '''
    log.info("run cli cmd: {}".format(cmd), 1)
    ssh_shell.settimeout(5)
    if ssh_shell.recv_ready():
        # dummy read to clean buffer
        output = ssh_shell.recv(65535)
    ssh_shell.send('{}\n'.format(cmd))
    if force:
        return
    ssh_shell.settimeout(RCV_POLL_TIME)

    output = ssh_shell.recv(65535)
    data = parse_cli_cmd_output(output)

    time_start = time.time()
    while not data and (time.time() - time_start < timeout):
        try:
            output += ssh_shell.recv(65535)
        except socket.timeout:
            pass
        data = parse_cli_cmd_output(output)
        if data:
            break

    return data

#------------------------------------------------------------

def start_cpu_mon(conn, period):
    '''
    @summary start cpu usage monitor on remote system
    @param conn: ssh connection
    @param period: cpumon poll period in seconds
    @return: True if cpu monitoing successfully started
    '''
    try:
        period = int(period)
    except BaseException:
        log.err("None integer value in cpu monitor period {}".format(period))
        return False
    run_ssh_cmd(conn, "rm -f {}".format(CPUMON_FILENAME))
    __, err = run_ssh_cmd(conn, "mpstat -P ALL {} > {} &".format(period, CPUMON_FILENAME))
    return err == ''

#------------------------------------------------------------

def stop_cpu_mon(conn):
    '''
    @summary stop cpu usage monitor on remote system
    @param conn: ssh connection
    @param period: cpumon poll period in seconds
    @return: True if cpu monitoing successfully stopped
    '''
    __, err = run_ssh_cmd(conn, "killall -q mpstat")
    return err == ''

#------------------------------------------------------------

def ssh_download(host_ip, user, password, src, dst):
    '''
    @summary:        this function performs scp file from host system
    @param host_ip:       destination host ip
    @param user:     user name in destination server
    @param password: user's password in destination server
    @param src:      full path to file in local server
    @param dst:      full path to file in destination server
    @return:         True if no errors
    '''

    if password:
        password = "-p {}".format(password)
    scp_cmd = 'sshpass {} scp -o PubkeyAuthentication=no -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {}@{}:{} {}'.format(password,
                                                                                                                                         user, host_ip,
                                                                                                                                         src, dst)
    log.info("{}".format(scp_cmd), 2)
    ret = os.system(scp_cmd)
    if ret != 0:
        log.err("Failed copy {0} using SCP from {1} (run command '{2}')".format(src, host_ip, scp_cmd))

    return ret == 0

#------------------------------------------------------------

def get_host_timestamp(conn):
    '''
    @summary get remote host time by send 'date command
    @param conn: ssh connection
    @return: date_time_obj
    '''
    res, err = run_ssh_cmd(conn, "date '+%D %T'")
    if err:
        log.err("get system time error: {}", err)
        return None
    date_time_obj = datetime.strptime(res, '%m/%d/%y %H:%M:%S\n')
    return date_time_obj

#------------------------------------------------------------

def lines_that_contain(string, lines_list):
    ''''
    @summary get list of all lines which contains sring
    @param string: string to search
    @param lines_list: list of thre lines
    @return: list of all lines which contains sring
    '''
    return [line for line in lines_list if string in line]

#------------------------------------------------------------

def get_log_timestump(conn, test_entry):
    '''
    @summary get timestumps from l=the log on remote host
    @param conn: ssh connection
    @param test_entry: dict
        example:
        {"test_name": "sensors",
            "cpu_usage" : {
                "enabled": "True",
                "period": "1"
            } ,
            "test_begin_mark": "",
            "test_end_mark": "",
            "test_command_flow" : ["sensors"]
        }
    @return: begin_time_obj, end_time_obj
    '''
    start_time_obj = None
    end_time_obj = None
    if (test_entry['test_begin_mark'] == NONE_MARK) or (test_entry['test_end_mark'] == NONE_MARK):
        return start_time_obj, end_time_obj

    syslog_name = "{}/system.log".format(config['test_pathname'])
    output = ssh_download(config['ip'],
                          SHELL_USER,
                          SHELL_PASS,
                          REMOTE_LOG_FILE,
                          syslog_name)

    if not os.path.isfile(syslog_name):
        log.err('err downloading from {} file {}:\n{}'.format(config['ip'],
                                                              REMOTE_LOG_FILE,
                                                              output))
        os.remove(REMOTE_LOG_FILE)
        return None, None

    with open(syslog_name) as log_file_data:
        log_lines = log_file_data.readlines()

    lines_start = lines_that_contain(test_entry['test_begin_mark'], log_lines)
    if lines_start:
        log.info("begin mark found:{}".format(lines_start[-1]), 1)
        start_time_obj = datetime.strptime(re.findall(TIMESTAMP_REGEXP, lines_start[-1])[0], '%H:%M:%S')
    else:
        log.err("Can't find begin mark: '{}'".format(test_entry['test_begin_mark']))

    lines_end = lines_that_contain(test_entry['test_end_mark'], log_lines)
    if lines_end:
        log.info("end mark found:{}".format(lines_end[-1]), 1)
        end_time_obj = datetime.strptime(re.findall(TIMESTAMP_REGEXP, lines_end[-1])[0], '%H:%M:%S')
    else:
        log.err("Can't find end mark: '{}'".format(test_entry['test_end_mark']))

    os.remove(syslog_name)
    return start_time_obj, end_time_obj

#------------------------------------------------------------

def get_diff_time(test_start_timestamp, test_stop_timestamp):
    '''
    @summary get difference in sec betwin 2 time_obj
    @return diff in sec
    '''
    diff = test_stop_timestamp - test_start_timestamp
    diff_sec = diff.total_seconds()
    return diff_sec

#------------------------------------------------------------

def close_ssh_all():
    '''
    @summary close ssh connections to switch
    '''
    if 'shell_conn' in config.keys() and config['shell_conn']:
        config['shell_conn'].close()
        config['shell_conn'] = None

    if 'cli_conn' in config.keys() and config['cli_conn']:
        config['cli_conn'].close()
        config['cli_conn'] = None
        config['cli_conn_shell'] = None

#------------------------------------------------------------

def establish_ssh_all(timeout=60, force=False):
    '''
    @summary establish ssh connections to switch
    @param timeout: timeout for ssh connection waiting
    @return False on error
    '''
    if 'shell_conn' not in config.keys() or not config['shell_conn']:
        log.info("Establishing shell ssh connection {}".format(config['ip']), 1)
        try:
            shell_conn, __ = open_ssh_conn(config['ip'], config['shell_user'], config['shell_pass'], timeout=timeout)
        except paramiko.BadAuthenticationType:
            shell_conn = None
        if not shell_conn:
            log.err("Can't establish SSH connection to the client {}".format(config['ip']))
            if not force:
                return False
        config['shell_conn'] = shell_conn

    if 'cli_conn' not in config.keys() or not config['cli_conn']:
        log.info("Establishing cli ssh connection {}".format(config['ip']), 1)
        try:
            cli_conn, cli_conn_shell = open_ssh_conn(config['ip'], config['cli_user'], config['cli_pass'], timeout=timeout)
        except paramiko.BadAuthenticationType:
            cli_conn = None
        if not cli_conn:
            log.err("Can't establish SSH connection to the client {}".format(config['ip']))
            if not force:
                close_ssh_all()
                return False
            
        config['cli_conn'] = cli_conn
        config['cli_conn_shell'] = cli_conn_shell
        if not wait_cli_conn_login(cli_conn_shell):
            log.err("Can't login cli to the client {}".format(config['ip']))
            if not force:
                close_ssh_all()
                return False

    return True

#------------------------------------------------------------

def wait_cli_msg(ssh_shell, msg, timeout=CMD_TIMEOUT):
    '''

    '''
    ssh_shell.settimeout(RCV_POLL_TIME)

    output = ssh_shell.recv(65535)
    #print("ssh wait: {}".format(msg))
    #print("ssh recived: {}".format(output))
    data = parse_cli_cmd_output(output, msg)

    time_start = time.time()
    while data is None and (time.time() - time_start < timeout):
        try:
            output += ssh_shell.recv(65535)
        except socket.timeout:
            pass
        data = parse_cli_cmd_output(output, msg)
        if data:
            break
        time.sleep(10)

    return data is not None

def run_sys_cmd_cli(cmd, force=False):
    '''
    @summary execute special system command
    @param cmd: command to execute
        command list:
        ping {sec}
        login
        logout
        cpu_usage {start/stop}
        sleep {sec}
    @return command output
    '''
    cmd = cmd.split(' ')
    if cmd[0] == 'ping':
        if len(cmd) >= 2:
            timeout = int(cmd[1])
        else:
            timeout = 60
        if not ping_system(config['ip'], timeout):
            return "ping {} failure".format(config['ip'])
    elif cmd[0] == 'login':
        if len(cmd) >= 2:
            timeout = int(cmd[1])
        else:
            timeout = 60
        if not establish_ssh_all(timeout, force):
            return 'Fail to loginn {}'.format(config['ip'])
    elif cmd[0] == 'logout':
        close_ssh_all()
        return ''
    elif cmd[0] == 'cpu_usage':
        if cmd[1] == 'start':
            if 'cpumon_poll_time' not in config.keys() or not start_cpu_mon(config['shell_conn'], config['cpumon_poll_time']):
                log.err("Fail to start CPU usage monitor on client {}".format(config['ip']))
                return None
            config['cpu_mon_start_time'] = get_host_timestamp(config['shell_conn'])
            config['cpu_mon'] = True

        elif cmd[1] == 'stop':
            stop_cpu_mon(config['shell_conn'])
        else:
            log.err("Unknown cmd {}".format(cmd))
            return None
        return ''
    elif cmd[0] == 'sleep':
        seconds = int(cmd[1])
        time.sleep(seconds)
        return ''
    elif cmd[0] == 'reset_factory_wizard':
        run_mlnx_cmd_cli(config['cli_conn_shell'], '\n', force=True)
        wait_cli_msg(config['cli_conn_shell'], 'Do you want to use the wizard for initial configuration?')
        run_mlnx_cmd_cli(config['cli_conn_shell'], 'n', force=True)
        
        wait_cli_msg(config['cli_conn_shell'], "New password for 'admin'")
        run_mlnx_cmd_cli(config['cli_conn_shell'], 'admin', force=True)
        
        wait_cli_msg(config['cli_conn_shell'], 'Confirm:')
        run_mlnx_cmd_cli(config['cli_conn_shell'], 'admin', force=True)
        
        wait_cli_msg(config['cli_conn_shell'], "New password for 'monitor'")
        run_mlnx_cmd_cli(config['cli_conn_shell'], 'monitor', force=True)
        
        wait_cli_msg(config['cli_conn_shell'], 'Confirm:')
        run_mlnx_cmd_cli(config['cli_conn_shell'], 'monitor', force=True)
        
        wait_cli_conn_login(config['cli_conn_shell'])
        #wait_cli_msg(config['cli_conn_shell'], '] > ')  
    else:
        return 'Unknown command {}'.format(cmd)

#------------------------------------------------------------

def run_local_cmd(cmd, force=False):
    '''
    @summary execute command on local host
    @param cmd: command to execute
    @return command output
    '''
    output, __ = Command(cmd).run(True, timeout=240)
    return output

#------------------------------------------------------------

def STP_res_parcer(str):
    lines_list = str.splitlines()
    res = lines_that_contain("BPDU received", lines_list)
    val = re.findall(".*BPDU received:\s+(\d+)", res[-1])
    return int(val[0])

#------------------------------------------------------------

def parse_cmd_time(cmd):
    '''
    @summary pase output from 'time' command
    @param cmd: output string of 'time' command
    @return dict:
    {'real': 7.37, 'sys': 0.11, 'user': 0.36}
    '''
    
    search_regexp = ".*real\s?([0-9,.]*).?\suser\s?([0-9,.]*).?\ssys\s?([0-9,.]*)"
    time_res = re.search(search_regexp, cmd)
    if not time_res:
        return 0

    time_ret = {}
    time_ret['real'] = float(time_res.group(1))
    time_ret['user'] = float(time_res.group(2))
    time_ret['sys'] = float(time_res.group(3))
    return time_ret['real']

#------------------------------------------------------------

def run_test(test_entry,iteration):
    '''
    @summary run single test case
    @param test_entry: dict
        example:
        {"test_name": "sensors",
            "cpu_usage" : {
                "period": "1"
            } ,
            "test_begin_mark": "",
            "test_end_mark": "",
            "test_command_flow" : ["sensors"]
        }
    @return: results dict if test successfull or None on failed
    '''
    test_start_obj = None
    test_stop_obj = None
    results = {}
    results['extra_info'] = ''
    results['cpu_log_align'] = False
    config['cpu_mon'] = False
    if 'cpu_usage' in test_entry.keys():
        cpu_usage_conf = test_entry['cpu_usage']
        config['cpumon_poll_time'] = cpu_usage_conf['period']
        if 'align' in cpu_usage_conf.keys():
            results['cpu_log_align'] = cpu_usage_conf['align']
    else:
        config['cpumon_poll_time'] = CPUMON_POLL_TIME_DEF

    if not establish_ssh_all():
        log.err("Fail to establish ssh connections to on client {}".format(config['ip']))
        return None

    test_overal_start_obj = get_host_timestamp(config['shell_conn'])
    if not test_overal_start_obj:
        return None

    test_time_duration = float(0)
    for test_cmd_entry in test_entry['test_command_flow']:
        cmd = test_cmd_entry['cmd']
        type = test_cmd_entry['type']
        time = None
        force = False
        if 'time' in test_cmd_entry.keys():
            time = test_cmd_entry['time']

            if time == 'start':
                cmd_time_start_obj = get_host_timestamp(config['shell_conn'])
            elif time == '+':
                cmd = "time -p {}".format(cmd)
        cmd = cmd.format(SWITCH_IP=config["ip"], LOCAL_PATH=config['pathname'])
        if cmd[0] == '#':
            log.info("cmd: {} skip".format(cmd), 1)
            continue
        
        if 'force' in test_cmd_entry.keys():
            force = test_cmd_entry['force']
        
        log.info("cmd: {}".format(cmd), 1)
        if type == 'shell':
            ret, _ = run_ssh_cmd(config['shell_conn'], cmd, force=force)
        elif type == 'cli':
            ret = run_mlnx_cmd_cli(config['cli_conn_shell'], cmd, force=force)
        elif type == 'sys':
            ret = run_sys_cmd_cli(cmd, force=force)
        elif type == 'local':
            ret = run_local_cmd(cmd, force=force)
        else:
            log.err("Unknown cmd:{} type:{}".format(type))
            continue
        log.info("return: {}".format(ret), 2)

        if time == '+':
            cmd_time = parse_cmd_time(ret)
            test_time_duration += cmd_time
        elif time == 'stop':
            cmd_time_stop_obj = get_host_timestamp(config['shell_conn'])
            diff_time = get_diff_time(cmd_time_start_obj, cmd_time_stop_obj)
            test_time_duration += diff_time
        if 'output_parcer' in test_cmd_entry.keys():
            parcer = globals()[test_cmd_entry["output_parcer"]]
            extra_info = parcer(ret)
            results['extra_info'] = extra_info

    test_overal_stop_obj = get_host_timestamp(config['shell_conn'])
    if not test_overal_stop_obj:
        return None

    if config['cpu_mon']:
        stop_cpu_mon(config['shell_conn'])
        cpu_log_name = "{}/{}_i{}_cpu".format(config['test_pathname'],
                                          test_entry['test_name'],
                                          iteration
                                          )
        ssh_download(config['ip'],
                     config['shell_user'],
                     config['shell_pass'],
                     CPUMON_FILENAME,
                     cpu_log_name)
        if os.path.isfile(cpu_log_name):
            results['cpu_log'] = cpu_log_name
            results['cpu_log_start_time'] = config['cpu_mon_start_time']

    test_start_obj, test_stop_obj = get_log_timestump(config["shell_conn"], test_entry)

    if test_start_obj and test_stop_obj:
        diff_timestamp = get_diff_time(test_start_obj, test_stop_obj)
        results['test_duration'] = diff_timestamp
    else:
        test_start_obj = test_overal_start_obj
        test_stop_obj = test_overal_stop_obj
        results['test_duration'] = test_time_duration

    overal_diff_timestamp = get_diff_time(test_overal_start_obj, test_overal_stop_obj)

    results['start_time'] = test_start_obj
    results['stop_time'] = test_stop_obj
    results['overal_duration'] = overal_diff_timestamp

    test_report = TEST_REPORT_FORMAT.format(test_name=test_entry['test_name'],
                                            start=results['start_time'].strftime(TEST_REPORT_DATETIME_FORMAT),
                                            end=results['stop_time'].strftime(TEST_REPORT_DATETIME_FORMAT),
                                            test_time=results['test_duration'],
                                            overal_time=results['overal_duration'],
                                            extra_info = results['extra_info'])
    log.info("{}".format(test_report))
    return results

#------------------------------------------------------------

def run_bench(bench_config):
    '''
    @summary mauin benchmark test loop
    @param bench_config: configuration dict
    @return: Tru on ptests passed
    '''
    now = datetime.now()
    date_time_folder = now.strftime("%Y_%m_%d_%H_%M")
    if config['prefix']:
        date_time_folder = "{}_{}".format(config['prefix'], date_time_folder)

    config['test_pathname'] = '{}/{}'.format(config['pathname'],
                                             date_time_folder)
    config['date_time'] = date_time_folder
    if not os.path.isdir(config['test_pathname']):
        os.mkdir(config['test_pathname'])

    if config['log']:
        log_filename = "{}/{}".format(config['test_pathname'], config['log'])
    else:
        log_filename = None
    log.open(log_filename, verbose=config['verbose'])

    log.info("Begin benchmarking system {}".format(config['ip']))

    config['test_results'] = OrderedDict([])
    test_count = len(bench_config)
    test_succeed_count = 0

    for idx, test_entry in enumerate(bench_config):
        test_entry['test_name'] = test_entry['test_name'].replace(' ', '_')
        log.info("==========================================================", 0)
        log.info("Start test {} of {}: '{}'".format(idx + 1,
                                                    test_count,
                                                    test_entry['test_name']))
        log.info("==========================================================", 0)
        if 'skip' in test_entry.keys() and test_entry['skip'] == 1:
            log.info("(Skipped)", 0)
            continue

        averege = 1
        if 'averege' in test_entry.keys():
            averege = test_entry['averege']

        if not ('no_report' in test_entry.keys() and test_entry['no_report']):
            config['test_results'][test_entry['test_name']] = []

        for test_iter in range(averege):
            log.info("(Iteration {} of {})".format(test_iter+1, averege),0)
            results = run_test(test_entry, test_iter)
            if not results:
                log.err("Benchmark filed on test: '{}' iteration {}".format(test_entry['test_name'], test_iter))
                if not config['force']:
                    return False
            else:
                if not ('no_report' in test_entry.keys() and test_entry['no_report']):
                    config['test_results'][test_entry['test_name']].append(results)

            close_ssh_all()
        test_succeed_count += 1

    config['test_count'] = test_count
    config['test_succeed_count'] = test_succeed_count

    log.info("Start to process results")
    ret = bench_report.process_results(config)
    if not ret:
        log.err("Process results faild")
    else:
        log.info("Process results finished")

    log.info("Results saved in {}".format(config['test_pathname']))
    return ret

#------------------------------------------------------------

def load_benchmark_conf(file_name):
    '''
    @summary: load benchmark config from file
    @param file_name: JSON config file name
    @return dict loaded fron config file
    '''
    if not file_name:
        file_name = CONFIG_NAME_DEF

    pathname = os.path.dirname(file_name)
    if pathname == "":
        pathname = os.path.dirname(os.path.realpath(__file__))
        config['pathname'] = pathname
        file_name = pathname + "/" + file_name

    if not os.path.isfile(file_name):
        return None

    with open(file_name) as config_file:
        data = json.load(config_file, object_pairs_hook=OrderedDict)
    config['bench_plan'] = file_name 
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--ip', dest='host', required=True, help='Remote host ip address')
    parser.add_argument('--cli_user', dest='cli_user', help='cli login', default=CLI_USER)
    parser.add_argument('--cli_pass', dest='cli_passwd', help='cli  password', default=CLI_PASS)
    parser.add_argument('--shell_user', dest='shell_user', help='shell login ', default=SHELL_USER)
    parser.add_argument('--shell_pass', dest='shell_passwd', help='shell password', default=SHELL_PASS)
    parser.add_argument('-c', '--config', dest='config', help='benchmark config file name', default=CONFIG_NAME_DEF)
    parser.add_argument('-l', '--log', dest='log', help='Save benchmark test flow output to log file', action='store_const', const=True)
    parser.add_argument('-v', '--verbose', dest='verbose', help='Output verbose level', default=0)
    parser.add_argument('-o', '--output_format', dest='out_format', help='Output format for cpu log', default='xls', choices=['csv', 'xls'])
    parser.add_argument('-f', '--forse', dest='force', help="Don't stop test if found error on bench commands", action='store_const', const=True),
    parser.add_argument('--prefix', dest='out_prefix', help='Test name prefix', default='')

    args = parser.parse_args()

    benchmark_config = load_benchmark_conf(args.config)

    if benchmark_config is None:
        print "Can't load config JSON file"
        sys.exit(1)

    if (args.out_format == 'xls') and not xls_format_ena:
        print("Not possible to export to XLS format because python libraries: openpyxl are not installed")
        print("run 'sudo pip install openpyxl '")
        print("or chose other format to output reports")
        sys.exit(1)
    
    config['ip'] = args.host
    config['cli_user'] = args.cli_user
    config['cli_pass'] = args.cli_passwd
    config['shell_user'] = args.shell_user
    config['shell_pass'] = args.shell_passwd
    config['verbose'] = int(args.verbose)
    config['format'] = args.out_format
    config['prefix'] = args.out_prefix
    if args.log:
        config['log'] = LOG_FILENAME
    else:
        config['log'] = ''

    if args.force:
        config['force'] = True
    else:
        config['force'] = False

    res = run_bench(benchmark_config)
    sys.exit(0)
