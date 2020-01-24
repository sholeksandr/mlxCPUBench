#!/bin/bash
set -x

BASEDIR=$(dirname $0)
SWITCH_IP=$1
cd $BASEDIR

export PYTHONPATH=$BASEDIR/sx_fit_regression
export REGRESSION_BASE_DIR=$BASEDIR

/auto/app/Python-2.release/bin/python $BASEDIR/sx_fit_regression/l3/bgp/functional/bgp_scale_for_cpu_benchmark/bgp_scale_for_cpu_benchmark.py $SWITCH_IP 653919204 NONE test_bgp_scale_cpu_benchmark router_iface=1/20 iface_speed=10000 ixia_card=1 ixia_port=13 ixia_username=ixia3 ixia_password=ixia3 ixia_chassis_ip=10.210.24.212 ixia_mgmt_ip=10.210.25.35 ixia_tcl_port=8003
#/auto/app/Python-2.release/bin/python $BASEDIR/sx_fit_regression/l3/bgp/functional/bgp_scale_for_cpu_benchmark/bgp_scale_for_cpu_benchmark.py $SWITCH_IP 653919204 NONE test_bgp_scale_cpu_benchmark router_iface=1/23 iface_speed=10000 ixia_card=2 ixia_port=1 ixia_username=ixia11 ixia_password=ixia11 ixia_chassis_ip=10.210.24.212 ixia_mgmt_ip=10.210.25.35 ixia_tcl_port=8511




