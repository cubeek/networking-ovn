FROM registry.centos.org/centos/centos
ARG RDO_REPO=https://trunk.rdoproject.org/centos7-master/current/delorean.repo
ARG NET_OVN_REPO=https://git.openstack.org/openstack/networking-ovn.git
RUN yum install -y epel-release wget centos-release-openstack-stein python3 python3-devel && \
    wget $RDO_REPO -O /etc/yum.repos.d/delorean.repo && \
    yum install -y bash git python3-pip openvswitch openvswitch-ovn-* git gcc tcpdump netstat nmap-ncat strace net-tools
RUN alternatives --install /usr/bin/python python /usr/bin/python3.6 60
RUN git clone $NET_OVN_REPO
RUN cd networking-ovn && pip3 install .
RUN pip3 install pymysql
COPY containers/neutron-server-ovn/start_services.sh /usr/bin/.
EXPOSE 6641/tcp
EXPOSE 6642/tcp
EXPOSE 9696/tcp
CMD bash /usr/bin/start_services.sh
