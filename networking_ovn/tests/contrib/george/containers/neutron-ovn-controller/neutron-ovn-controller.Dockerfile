FROM registry.centos.org/centos/centos
ARG RDO_REPO=https://trunk.rdoproject.org/centos7-master/current/delorean.repo
RUN yum install -y epel-release wget centos-release-openstack-stein && \
    wget $RDO_REPO -O /etc/yum.repos.d/delorean.repo && \
    yum install -y bash openvswitch openvswitch-ovn-* tcpdump netstat nmap-ncat strace net-tools
RUN yum install -y autoconf automake libtool gcc patch make git openssl-devel python3 python3-devel python3-pip
# REMOVE
RUN pip3 install six
RUN alternatives --install /usr/bin/python python /usr/bin/python3.6 60
RUN git clone https://github.com/openvswitch/ovs.git
RUN cd ovs && ./boot.sh && ./configure --prefix=/usr --localstatedir=/var && make -j 4
RUN git clone https://github.com/cubeek/ovn.git
RUN cd ovn && ./boot.sh && ./configure --prefix=/usr --localstatedir=/var --with-ovs-source=/ovs && make -j 4 && make install
RUN mkdir /var/run/ovn
COPY containers/neutron-ovn-controller/start_services.sh /usr/bin/.
CMD bash /usr/bin/start_services.sh
