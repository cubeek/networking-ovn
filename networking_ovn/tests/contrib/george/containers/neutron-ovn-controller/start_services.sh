#!/bin/bash

/usr/share/openvswitch/scripts/ovs-ctl start --system-id=random
#/usr/share/openvswitch/scripts/ovn-ctl start_controller

echo "Starting OVN controller"
ovn-controller unix:/var/run/openvswitch/db.sock -vconsole:emer -vsyslog:err -vfile:dbg --no-chdir --log-file=/var/log/openvswitch/ovn-controller.log --pidfile=/var/run/openvswitch/ovn-controller.pid --monitor
